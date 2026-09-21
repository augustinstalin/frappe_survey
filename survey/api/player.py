"""Public endpoints for taking a survey.

Every method here is reachable by an anonymous visitor, so each one:

1. passes its tokens through `player.access.resolve`, which is the only place
   authorisation happens;
2. then works with `ignore_permissions=True`, because a respondent has no
   roles and no document permissions by design;
3. returns a plain dict the player renders — never a Document, which would
   serialise fields nobody outside should see.

`start` and `submit_page` are rate limited: they are public endpoints that
write rows. Odoo relies on the token being unguessable and nothing else,
which is fine against a guesser and useless against somebody who has a valid
link and a loop.
"""

import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from survey.constants import (
	ACCESS_INVITED,
	RESPONSE_COMPLETED,
	SCORING_AFTER_PAGE,
	TIME_LIMIT_GRACE_SECONDS,
)
from survey.player import navigation, persistence, serializers, validation
from survey.player.access import (
	NO_ATTEMPTS_LEFT,
	SurveyAccessError,
	can_answer,
	resolve,
)

#: How long a respondent's cookie keeps them attached to their response.
RESPONSE_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


# ----------------------------------------------------------------------
# Entry
# ----------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30, seconds=60 * 60)
def start(survey_token: str, response_token: str | None = None, email: str | None = None) -> dict:
	"""Find or create this visitor's response, and hand back its token.

	Called once, when somebody opens a survey link. An existing token (from a
	cookie or a personal invitation link) is reused so that reopening the link
	resumes rather than starting over.
	"""
	access = _safe_resolve(survey_token, response_token, require_response=False)
	if isinstance(access, dict):
		return access

	if access.response:
		return get_state_payload(access)

	if access.survey.access_mode == ACCESS_INVITED:
		# Nothing to create: an invitation is the only way in.
		return serializers.serialize_error(
			"response_required", _("This survey is open to invited people only.")
		)

	response = create_response(access.survey, email=email)
	access.response = response

	_set_response_cookie(access.survey.access_token, response.access_token)

	return get_state_payload(access)


def create_response(survey, email: str | None = None, **values):
	"""Create a response for the visitor in front of us.

	Kept separate from `start` so the invitation flow (phase 6) and the
	test-entry action can reuse it without going through the public gate.
	"""
	user = frappe.session.user if frappe.session.user != "Guest" else None

	doc = frappe.get_doc(
		{
			"doctype": "Survey Response",
			"survey": survey.name,
			"user": user,
			"email": email or (frappe.db.get_value("User", user, "email") if user else None),
			**values,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def get_state(survey_token: str, response_token: str | None = None) -> dict:
	"""Everything needed to render the current screen.

	Also the resume path: a respondent returning days later lands here and
	gets the page they left off on.
	"""
	access = _safe_resolve(survey_token, response_token, require_response=False)
	if isinstance(access, dict):
		return access

	return get_state_payload(access)


@frappe.whitelist(allow_guest=True)
def begin(survey_token: str, response_token: str) -> dict:
	"""Leave the start screen and show the first question."""
	access = _safe_resolve(survey_token, response_token)
	if isinstance(access, dict):
		return access

	if not can_answer(access):
		return serializers.serialize_finished(access)

	timed_out = _finish_if_out_of_time(access)
	if timed_out:
		return timed_out

	access.response.mark_in_progress()
	access.response.reload()

	page = navigation.get_first_page(access.survey, access.response)
	if not page:
		return _finish(access)

	_remember_page(access.response, page.id)
	return serializers.serialize_state(access, page)


# ----------------------------------------------------------------------
# Answering
# ----------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=600, seconds=60 * 60)
def submit_page(
	survey_token: str,
	response_token: str,
	page_id: str,
	answers: str | dict | None = None,
	direction: str = "next",
	target_page_id: str | None = None,
) -> dict:
	"""Validate and save one page, then move.

	`direction` is one of:

	* ``next`` — onward, or into the skipped-question queue, or finish;
	* ``back`` — the previous page. Going back still saves: a respondent who
	  types an answer and then hits Back expects to find it there on return;
	* ``jump`` — to ``target_page_id``, which is what the breadcrumb uses. It
	  saves for the same reason;
	* ``timeout`` — the countdown reached zero in the browser. Saves what was
	  on screen (the server re-checks the clock) and finishes.

	Returns either `{"errors": {...}}` with the page untouched, or the next
	screen's payload.
	"""
	access = _safe_resolve(survey_token, response_token)
	if isinstance(access, dict):
		return access

	if not can_answer(access):
		# Already finished. Re-submitting must not reopen or double-count it.
		return serializers.serialize_finished(access)

	# Past the grace window nothing on this page is accepted, however it got
	# here: a stopped clock, a sleeping laptop, or a second tab.
	timed_out = _finish_if_out_of_time(access)
	if timed_out:
		return timed_out

	survey, response = access.survey, access.response
	answers = _parse_answers(answers)

	page = navigation.get_page(survey, response, page_id)
	if not page:
		# The page vanished — usually because an earlier answer changed and
		# hid it. Send them wherever they belong now rather than erroring.
		return get_state_payload(access)

	# Rendering and validation use the page as the respondent currently sees
	# it; saving uses the wider set, so an answer to a question this very page
	# unlocked is not discarded. See `navigation.get_page_for_save`.
	questions = serializers.load_questions(page.questions)

	errors = validation.validate_page(questions, answers, allow_roaming=bool(survey.allow_roaming))
	if errors:
		return {"state": "invalid", "errors": errors}

	save_page = navigation.get_page_for_save(survey, response, page.id) or page
	persistence.save_page_answers(
		response, serializers.load_questions(save_page.questions), answers
	)
	response.reload()

	# An answer may have just hidden a question that was already answered.
	removed = persistence.clear_hidden_answers(response)
	if removed:
		response.save(ignore_permissions=True)
		response.reload()

	_remember_page(response, page.id)

	extra = {}
	if survey.scoring_type == SCORING_AFTER_PAGE:
		extra["correct_answers"] = serializers.serialize_correct_answers(questions)

	if direction == "timeout":
		# The answers above were saved because the server clock still allowed
		# them; the run ends here either way.
		payload = _finish(access, extra)
		payload["timed_out"] = True
		return payload

	if direction == "back":
		previous = navigation.get_previous_page(survey, response, page.id)
		if previous:
			_remember_page(response, previous.id)
			return serializers.serialize_state(access, previous, extra)
		return serializers.serialize_state(access, page, extra)

	if direction == "jump":
		target = navigation.get_page(survey, response, target_page_id)
		if target:
			_remember_page(response, target.id)
			return serializers.serialize_state(access, target, extra)
		return serializers.serialize_state(access, page, extra)

	return _advance(access, page, extra)


def _advance(access, page, extra: dict | None = None) -> dict:
	"""Move forward from `page`: onward, back to a skipped question, or finish.

	Once the respondent has reached the end once (`first_submitted`), forward
	no longer means "the next page" — it means "the next page that still owes
	a mandatory answer". Without that they would walk the whole survey again
	to reach the one question they left blank.
	"""
	survey, response = access.survey, access.response

	if survey.allow_roaming and response.first_submitted:
		return _next_skipped_or_finish(access, page, extra)

	next_page = navigation.get_next_page(survey, response, page.id)
	if next_page:
		_remember_page(response, next_page.id)
		return serializers.serialize_state(access, next_page, extra)

	if survey.allow_roaming:
		# End of the road for the first time. If anything mandatory is still
		# blank the survey does not finish; it doubles back.
		response.db_set("first_submitted", 1, update_modified=False)
		response.reload()
		return _next_skipped_or_finish(access, page, extra)

	return _finish(access, extra)


def _next_skipped_or_finish(access, page, extra: dict | None = None) -> dict:
	survey, response = access.survey, access.response

	pending = [p for p in navigation.get_skipped_pages(survey, response) if p.id != page.id]
	if not pending:
		return _finish(access, extra)

	_remember_page(response, pending[0].id)
	return serializers.serialize_state(access, pending[0], extra)


@frappe.whitelist(allow_guest=True)
def go_back(survey_token: str, response_token: str, page_id: str) -> dict:
	"""Move back without saving. Used by the breadcrumb."""
	access = _safe_resolve(survey_token, response_token)
	if isinstance(access, dict):
		return access

	if not access.survey.allow_roaming:
		return serializers.serialize_error("not_allowed", _("You cannot go back in this survey."))

	target = navigation.get_page(access.survey, access.response, page_id)
	if not target:
		return get_state_payload(access)

	_remember_page(access.response, target.id)
	return serializers.serialize_state(access, target)


# ----------------------------------------------------------------------
# Finishing
# ----------------------------------------------------------------------


def _finish(access, extra: dict | None = None) -> dict:
	"""Submit the response and return the closing screen.

	Submitting is what "completed" means: it freezes the answers, runs the
	scoring, and fires the `on_submit` hooks that certification will hang off.
	"""
	response = access.response

	if response.docstatus == 0:
		response.flags.ignore_permissions = True
		response.submit()
		response.reload()

	payload = serializers.serialize_finished(access)
	if extra:
		payload.update(extra)

	_clear_response_cookie(access.survey.access_token)

	return payload


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _finish_if_out_of_time(access) -> dict | None:
	"""Submit a response whose time is up, and return the closing screen.

	Returns `None` when there is still time, so callers can carry on. Only the
	endpoints that *write* call this: the page render is a GET, and finishing
	a response there would be a write on a read request. The player covers
	that case instead — it is handed `time_left`, sees zero and submits
	immediately, which comes back through here.
	"""
	response = access.response
	if not response or response.has_time_left(grace=TIME_LIMIT_GRACE_SECONDS):
		return None

	payload = _finish(access)
	payload["timed_out"] = True
	return payload


def get_state_payload(access) -> dict:
	"""Render whatever screen this response is currently on.

	Public because the portal page renders the first screen server-side and
	needs exactly this, without going back through HTTP.
	"""
	survey, response = access.survey, access.response

	if not response:
		return serializers.serialize_start(access)

	if response.status == RESPONSE_COMPLETED or response.docstatus == 1:
		return serializers.serialize_finished(access)

	if response.status == "New":
		return serializers.serialize_start(access)

	page = navigation.get_page(survey, response, response.last_displayed_question)
	if not page:
		page = navigation.get_first_page(survey, response)

	if not page:
		return serializers.serialize_finished(access)

	return serializers.serialize_state(access, page)


def _safe_resolve(survey_token, response_token, require_response: bool = True):
	"""Resolve tokens, turning a failure into a renderable error payload.

	Returning a dict rather than raising keeps the client simple: every
	endpoint answers with something it can render, and an access failure is
	just another screen.
	"""
	try:
		return resolve(survey_token, response_token, require_response=require_response)
	except SurveyAccessError as error:
		return serializers.serialize_error(error.code, str(error))


def _parse_answers(answers) -> dict:
	"""Normalise the submitted answers.

	The client always sends `{question: {value, comment}}`. `value` is a
	scalar, a list of option ids, or a `{row: [columns]}` map for a matrix —
	the shape follows the question type. This is deliberately more regular
	than Odoo's positional encoding, where a comment arrives as an extra
	element inside the answer list.
	"""
	if not answers:
		return {}

	if isinstance(answers, str):
		try:
			answers = json.loads(answers)
		except (ValueError, TypeError):
			frappe.throw(_("Could not read the submitted answers."))

	if not isinstance(answers, dict):
		frappe.throw(_("Could not read the submitted answers."))

	normalised = {}
	for question, payload in answers.items():
		if isinstance(payload, dict) and ("value" in payload or "comment" in payload):
			normalised[question] = payload
		else:
			# Tolerate a bare value for the common single-answer case.
			normalised[question] = {"value": payload, "comment": None}

	return normalised


def _remember_page(response, page_id: str) -> None:
	"""Store the resume point without touching the modification stamp."""
	if page_id in ("all", "__intro__"):
		# Synthetic page ids are not questions and cannot be stored in a Link.
		return

	if response.last_displayed_question == page_id:
		return

	frappe.db.set_value(
		"Survey Response", response.name, "last_displayed_question", page_id, update_modified=False
	)
	response.last_displayed_question = page_id


def _set_response_cookie(survey_token: str, response_token: str) -> None:
	"""Attach this browser to its response.

	The cookie is a convenience for public surveys, where there is no account
	to hang the response off. It is not an authorisation mechanism — the token
	inside it is, and it is checked on every request.
	"""
	if not hasattr(frappe.local, "cookie_manager") or not frappe.local.cookie_manager:
		return

	frappe.local.cookie_manager.set_cookie(
		f"survey_{survey_token}", response_token, max_age=RESPONSE_COOKIE_MAX_AGE
	)


def _clear_response_cookie(survey_token: str) -> None:
	if not hasattr(frappe.local, "cookie_manager") or not frappe.local.cookie_manager:
		return

	frappe.local.cookie_manager.delete_cookie(f"survey_{survey_token}")


def get_response_token_from_cookie(survey_token: str) -> str | None:
	return frappe.request.cookies.get(f"survey_{survey_token}") if frappe.request else None
