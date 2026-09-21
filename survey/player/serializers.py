"""The JSON the player renders from.

Odoo ships pre-rendered HTML fragments over RPC and swaps innerHTML. We send
data instead: skip logic needs the client to show and hide questions as the
respondent types, which it cannot do with opaque markup, and a survey page is
public — there is no reason to ship the same chrome on every page turn.

Nothing here reads a field the respondent should not see. Correct answers in
particular are only ever included when the survey's scoring mode says to
reveal them, and never before the page has been submitted.
"""

import frappe
from frappe.utils import cint, flt, get_datetime_str, get_url, now_datetime

from survey.constants import (
	CHOICE_TYPES,
	SCORING_AFTER_PAGE,
	SCORING_NONE,
	SCORING_TYPES_REVEALING_ANSWERS,
	TIME_LIMIT_WARNING_SECONDS,
	TYPE_MATRIX,
	TYPE_SCALE,
)
from survey.player import navigation
from survey.player.navigation import Page

# Fields safe to hand a respondent. Anything not listed is withheld by
# omission rather than by redaction, so a new field on the DocType is private
# until somebody decides otherwise.
QUESTION_FIELDS = (
	"name",
	"title",
	"description",
	"question_type",
	"placeholder",
	"mandatory",
	"mandatory_error_message",
	"validation_error_message",
	"validate_entry",
	"validate_email",
	"min_length",
	"max_length",
	"min_value",
	"max_value",
	"min_date",
	"max_date",
	"min_datetime",
	"max_datetime",
	"allow_comments",
	"comments_message",
	"comment_counts_as_answer",
	"matrix_subtype",
	"scale_min",
	"scale_max",
	"scale_min_label",
	"scale_mid_label",
	"scale_max_label",
	"section",
)

#: Loaded with every question but never serialised. These drive server-side
#: behaviour (identity capture, scoring) and must not reach the respondent —
#: `correct_number` in a payload is the answer key.
QUESTION_INTERNAL_FIELDS = (
	"save_as_email",
	"save_as_nickname",
	"is_scored",
	"score",
	"correct_number",
	"correct_date",
	"correct_datetime",
)


def serialize_state(access, page: Page | None, extra: dict | None = None) -> dict:
	"""The whole payload for one screen."""
	survey, response = access.survey, access.response

	if response and response.status == "Completed":
		return serialize_finished(access)

	if not page:
		return serialize_finished(access)

	payload = {
		"state": "in_progress" if (response and response.status != "New") else "new",
		"response_token": response.access_token if response else None,
		"survey": serialize_survey(survey),
		"page": serialize_page(survey, response, page),
		"progress": navigation.get_progress(survey, response, page.id),
		"navigation": serialize_navigation(survey, response, page),
		"timer": serialize_timer(survey, response),
		"breadcrumb": navigation.get_breadcrumb(survey, response, page.id),
		"answers": serialize_given_answers(response, page),
		"conditional": serialize_conditional(survey, response),
		"background_image": get_background_image(survey, page),
	}

	if extra:
		payload.update(extra)

	return payload


def serialize_survey(survey) -> dict:
	return {
		"name": survey.name,
		"title": survey.title,
		"description": survey.description,
		"pagination": survey.pagination,
		"scoring_type": survey.scoring_type,
		"is_scored": survey.scoring_type != SCORING_NONE,
		"reveals_answers_per_page": survey.scoring_type == SCORING_AFTER_PAGE,
		"allow_roaming": bool(survey.allow_roaming),
		"progress_display": survey.progress_display,
		"is_certification": bool(survey.is_certification),
		"is_time_limited": bool(survey.is_time_limited),
		"time_limit": survey.time_limit,
		"background_image": survey.background_image,
	}


def serialize_page(survey, response, page: Page) -> dict:
	questions = load_questions(page.questions)

	return {
		"id": page.id,
		"kind": page.kind,
		"section": serialize_section(page.section) if page.section else None,
		"questions": [serialize_question(question) for question in questions],
	}


def serialize_section(name: str) -> dict | None:
	row = frappe.db.get_value(
		"Survey Question", name, ["name", "title", "description"], as_dict=True
	)
	return dict(row) if row else None


def load_questions(names: list[str]) -> list:
	"""Load questions in the order they were asked for."""
	if not names:
		return []

	rows = frappe.get_all(
		"Survey Question",
		filters={"name": ["in", names]},
		fields=list(QUESTION_FIELDS) + list(QUESTION_INTERNAL_FIELDS),
	)
	by_name = {row.name: row for row in rows}
	return [by_name[name] for name in names if name in by_name]


def serialize_question(question) -> dict:
	# Only QUESTION_FIELDS: anything loaded for internal use stays internal.
	payload = {field: question.get(field) for field in QUESTION_FIELDS}
	payload["id"] = question.name

	if question.question_type in CHOICE_TYPES or question.question_type == TYPE_MATRIX:
		payload["options"] = serialize_options(question.name, matrix_rows=False)

	if question.question_type == TYPE_MATRIX:
		payload["rows"] = serialize_options(question.name, matrix_rows=True)

	if question.question_type == TYPE_SCALE:
		payload["scale_values"] = list(range(cint(question.scale_min), cint(question.scale_max) + 1))

	return payload


def serialize_options(question: str, matrix_rows: bool = False) -> list[dict]:
	"""Answer options, without ever leaking which one is correct."""
	rows = frappe.get_all(
		"Survey Question Option",
		filters={"question": question, "is_matrix_row": 1 if matrix_rows else 0},
		fields=["name", "label", "value_label", "image"],
		order_by="sequence asc, creation asc",
	)

	return [
		{
			"id": row.name,
			"label": row.label,
			"key": row.value_label,
			"image": get_url(row.image) if row.image else None,
		}
		for row in rows
	]


def serialize_navigation(survey, response, page: Page) -> dict:
	is_last = navigation.is_last_page(survey, response, page.id)
	previous = navigation.get_previous_page(survey, response, page.id) if survey.allow_roaming else None

	# Pages elsewhere that still owe a mandatory answer. The current page is
	# excluded because answering it is what the button in front of them does.
	pending = (
		[
			p
			for p in navigation.get_outstanding_pages(survey, response, page.id)
			if p.id != page.id
		]
		if survey.allow_roaming
		else []
	)

	if pending and (is_last or response.first_submitted):
		# Telling them "Submit" and then bouncing them backwards would be a
		# lie about what the button does.
		label = "next_skipped"
	elif is_last and not pending:
		label = "submit"
	else:
		label = "continue"

	return {
		"is_last": is_last,
		"can_go_back": bool(previous),
		"previous_page": previous.id if previous else None,
		"submit_label": label,
		"skipped_remaining": len(pending),
		"is_revisiting": bool(response.first_submitted),
	}


def serialize_timer(survey, response) -> dict | None:
	"""What the countdown needs, or None when the survey is untimed.

	`time_left` is a *duration*, deliberately not a deadline: the client
	anchors its countdown to its own clock at the moment it receives this, so
	a browser whose clock is wrong — or in another timezone — still counts
	down correctly. Every page turn re-sends it, which re-syncs the client
	against the server and quietly corrects any drift.

	`server_time` is along for diagnostics only; nothing depends on the client
	agreeing with it.
	"""
	if not survey.is_time_limited:
		return None

	remaining = response.time_remaining()
	if remaining is None:
		return None

	return {
		"limit_seconds": flt(survey.time_limit) * 60,
		"time_left": max(remaining, 0),
		"warn_at": TIME_LIMIT_WARNING_SECONDS,
		"server_time": get_datetime_str(now_datetime()),
	}


def serialize_given_answers(response, page: Page) -> dict:
	"""What this respondent already answered on this page.

	Used to repopulate the form when they resume or navigate back. Keyed the
	same way the client submits, so it round-trips without translation.
	"""
	if not response or not page.questions:
		return {}

	wanted = set(page.questions)
	types = {
		row.name: row.question_type
		for row in frappe.get_all(
			"Survey Question", filters={"name": ["in", list(wanted)]}, fields=["name", "question_type"]
		)
	}

	given: dict[str, dict] = {}

	for row in response.answers:
		if row.question not in wanted or row.skipped:
			continue

		entry = given.setdefault(row.question, {"value": None, "comment": None})
		question_type = types.get(row.question)

		if row.answer_type == "Comment":
			entry["comment"] = row.value_text
			continue

		if question_type == TYPE_MATRIX:
			matrix = entry["value"] or {}
			matrix.setdefault(row.matrix_row, []).append(row.selected_option)
			entry["value"] = matrix
		elif question_type == "Multiple Choice":
			entry["value"] = (entry["value"] or []) + [row.selected_option]
		elif question_type in CHOICE_TYPES:
			entry["value"] = row.selected_option
		else:
			entry["value"] = row.get_value()

	return given


def serialize_conditional(survey, response) -> dict:
	"""The skip-logic maps, for layouts that resolve visibility in the browser.

	On "One Page Per Question" the server decides what comes next, so sending
	these would be noise. On the other two layouts several questions share a
	screen and the client has to show and hide them live as answers change.
	"""
	from survey.survey.doctype.survey_response.survey_response import get_triggering_options_map

	if survey.pagination == "One Page Per Question":
		return {}

	triggers = get_triggering_options_map(survey.name)
	if not triggers:
		return {}

	triggered_by_option: dict[str, list[str]] = {}
	for question, options in triggers.items():
		for option in options:
			triggered_by_option.setdefault(option, []).append(question)

	return {
		"required_options_by_question": {
			question: sorted(options) for question, options in triggers.items()
		},
		"questions_by_option": triggered_by_option,
		"selected_options": sorted(response.get_selected_options()) if response else [],
	}


def get_background_image(survey, page: Page | None) -> str | None:
	"""Section background wins over the survey's, matching Odoo."""
	image = None

	if page and page.section:
		image = frappe.db.get_value("Survey Question", page.section, "background_image")

	image = image or survey.background_image
	return get_url(image) if image else None


# ----------------------------------------------------------------------
# Terminal screens
# ----------------------------------------------------------------------


def serialize_start(access) -> dict:
	"""The screen before the first question."""
	survey = access.survey

	return {
		"state": "new",
		# The respondent's own token, handed back so the player can keep
		# talking to the API without depending on the cookie surviving.
		"response_token": access.response.access_token if access.response else None,
		"survey": serialize_survey(survey),
		"background_image": get_background_image(survey, None),
		"progress": {"current": 0, "total": 0, "percent": 0, "mode": survey.progress_display},
	}


def serialize_finished(access) -> dict:
	"""The screen after the last question."""
	survey, response = access.survey, access.response
	payload = {
		"state": "done",
		"response_token": response.access_token if response else None,
		"survey": serialize_survey(survey),
		"background_image": get_background_image(survey, None),
		"end_message": survey.end_message,
		"result": None,
	}

	if response and survey.scoring_type != SCORING_NONE:
		payload["result"] = {
			"score": response.total_score,
			"percentage": response.score_percentage,
			"passed": bool(response.passed),
			"passing_score": survey.passing_score,
			# The review link is only offered when the survey is willing to
			# show its answers at all.
			"can_review": survey.scoring_type in SCORING_TYPES_REVEALING_ANSWERS,
		}

	return payload


def serialize_error(code: str, message: str) -> dict:
	return {"state": "error", "code": code, "message": message}


def serialize_correct_answers(questions: list) -> dict:
	"""The answer key for one page, revealed after it has been submitted.

	Only ever called for `Scoring With Answers After Page`, and only after the
	answers are saved — calling it earlier would hand the respondent the key
	before they answered.
	"""
	key: dict[str, dict] = {}

	for question in questions:
		if not question.get("is_scored"):
			continue

		if question.question_type in CHOICE_TYPES:
			correct = frappe.get_all(
				"Survey Question Option",
				filters={"question": question.name, "is_correct": 1, "is_matrix_row": 0},
				pluck="name",
			)
			key[question.name] = {"options": correct}
		elif question.question_type == "Numeric":
			key[question.name] = {"value": question.correct_number}
		elif question.question_type == "Date":
			key[question.name] = {"value": str(question.correct_date or "")}
		elif question.question_type == "Datetime":
			key[question.name] = {"value": str(question.correct_datetime or "")}

	return key
