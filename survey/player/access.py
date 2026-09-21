"""The gate every public survey request passes through.

Respondents have no roles and no document permissions. What authorises them
is a pair of unguessable tokens: one identifying the survey, one identifying
their own response. Everything past this module therefore runs with
`ignore_permissions=True`, which is precisely why *all* of the checking lives
here, in one auditable place, rather than being sprinkled across endpoints.

The check order matters and mirrors Odoo's `_check_validity`: report the most
fundamental problem first, so a respondent with a stale link is told the link
is wrong rather than that the survey is closed.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import now_datetime

from survey.constants import (
	ACCESS_INVITED,
	PAGINATION_PER_SECTION,
	RESPONSE_COMPLETED,
	STATUS_OPEN,
)

# Validity codes. The player maps each to a screen; keep them stable.
VALID = "valid"
SURVEY_MISSING = "survey_missing"
SURVEY_CLOSED = "survey_closed"
SURVEY_EMPTY = "survey_empty"
RESPONSE_MISSING = "response_missing"
RESPONSE_REQUIRED = "response_required"
RESPONSE_EXPIRED = "response_expired"
LOGIN_REQUIRED = "login_required"
WRONG_USER = "wrong_user"
NO_ATTEMPTS_LEFT = "no_attempts_left"

#: Human-facing copy for each code. Deliberately vague about *why* a token
#: failed: telling a stranger "that survey exists but you are the wrong user"
#: leaks more than it helps.
MESSAGES = {
	SURVEY_MISSING: _("This survey link is not valid."),
	SURVEY_CLOSED: _("This survey is closed and is no longer accepting answers."),
	SURVEY_EMPTY: _("This survey has no questions yet."),
	RESPONSE_MISSING: _("This survey link is not valid."),
	RESPONSE_REQUIRED: _("This survey is open to invited people only."),
	RESPONSE_EXPIRED: _("The deadline for this survey has passed."),
	LOGIN_REQUIRED: _("Please sign in to take this survey."),
	WRONG_USER: _("This link belongs to somebody else."),
	NO_ATTEMPTS_LEFT: _("You have used all of your attempts at this survey."),
}


class SurveyAccessError(frappe.ValidationError):
	"""Raised when a public request fails the gate.

	Carries the validity code so the endpoint can render the right screen
	instead of a generic error.
	"""

	def __init__(self, code: str, message: str | None = None):
		self.code = code
		super().__init__(message or MESSAGES.get(code, _("This survey link is not valid.")))


@dataclass
class Access:
	"""What a validated request is allowed to touch."""

	survey: "frappe.Document"
	response: "frappe.Document | None"
	code: str = VALID

	@property
	def ok(self) -> bool:
		return self.code == VALID


def resolve(
	survey_token: str,
	response_token: str | None = None,
	require_response: bool = True,
	allow_closed: bool = False,
) -> Access:
	"""Validate a token pair and return the documents behind it.

	:param require_response: endpoints that answer questions need a response;
		the landing page does not, because it is what creates one.
	:param allow_closed: the review/print views stay readable after a survey
		closes, so they opt out of that one check.
	:raises SurveyAccessError: on any failure, carrying the validity code.
	"""
	survey = get_survey_by_token(survey_token)
	if not survey:
		raise SurveyAccessError(SURVEY_MISSING)

	response = None
	if response_token:
		response = get_response_by_token(survey.name, response_token)
		if not response:
			# A token that matches no response is indistinguishable from a
			# forged one, and is usually a cookie from a deleted response.
			raise SurveyAccessError(RESPONSE_MISSING)

	# A test entry belongs to a survey user trying their own draft, so it
	# deliberately bypasses the "is this survey open" checks below.
	is_test = bool(response and response.is_test)

	if not is_test:
		check_survey_is_open(survey, allow_closed=allow_closed)

	check_survey_has_content(survey)

	if survey.login_required and frappe.session.user == "Guest":
		raise SurveyAccessError(LOGIN_REQUIRED)

	if not response and require_response:
		raise SurveyAccessError(RESPONSE_REQUIRED)

	if not response and survey.access_mode == ACCESS_INVITED:
		# There is no link that lets a stranger into an invite-only survey.
		raise SurveyAccessError(RESPONSE_REQUIRED)

	if response:
		check_response_is_usable(survey, response)

	return Access(survey=survey, response=response)


# ----------------------------------------------------------------------
# Individual checks
# ----------------------------------------------------------------------


def check_survey_is_open(survey, allow_closed: bool = False) -> None:
	if allow_closed:
		return
	if survey.status != STATUS_OPEN:
		raise SurveyAccessError(SURVEY_CLOSED)


def check_survey_has_content(survey) -> None:
	"""A survey with nothing to show would render a blank page.

	"One Page Per Section" additionally needs at least one section holding a
	question, or every page would be empty.
	"""
	if not survey.question_count:
		raise SurveyAccessError(SURVEY_EMPTY)

	if survey.pagination == PAGINATION_PER_SECTION:
		has_populated_section = frappe.db.exists(
			"Survey Question", {"survey": survey.name, "is_section": 0, "section": ["is", "set"]}
		)
		if not has_populated_section:
			raise SurveyAccessError(SURVEY_EMPTY)


def check_response_is_usable(survey, response) -> None:
	"""The response exists — may *this* visitor use it, and is it still live?"""
	if response.deadline and now_datetime() > response.deadline:
		# An expired response can still be read once completed (to review
		# answers), but never answered further.
		if response.status != RESPONSE_COMPLETED:
			raise SurveyAccessError(RESPONSE_EXPIRED)

	check_response_belongs_to_visitor(response)


def check_response_belongs_to_visitor(response) -> None:
	"""Guard against a shared or stale cookie handing over someone's answers.

	Two directions to catch:

	* a signed-in visitor holding a token for a different account's response;
	* a signed-out visitor holding a token for a response that belongs to an
	  account (usually their own, from before they logged out).

	An anonymous response has no `user`, so anyone holding its token is by
	definition its owner — that is the whole security model for public
	surveys, and the token is the secret that makes it work.
	"""
	current = frappe.session.user

	if current == "Guest":
		if response.user:
			raise SurveyAccessError(WRONG_USER)
		return

	if response.user and response.user != current:
		raise SurveyAccessError(WRONG_USER)


# ----------------------------------------------------------------------
# Lookups
#
# `db.get_value` by token, then `get_doc` by name: a token is user input, and
# looking a document up by an indexed unique column keeps the query planner
# honest and the error handling in one place.
# ----------------------------------------------------------------------


def get_survey_by_token(token: str | None):
	if not token:
		return None

	name = frappe.db.get_value("Survey", {"access_token": token}, "name")
	return frappe.get_doc("Survey", name) if name else None


def get_response_by_token(survey: str, token: str | None):
	if not token:
		return None

	name = frappe.db.get_value(
		"Survey Response", {"survey": survey, "access_token": token}, "name"
	)
	return frappe.get_doc("Survey Response", name) if name else None


def can_answer(access: Access) -> bool:
	"""Whether the response is still open for new answers."""
	if not access.response:
		return False
	if access.response.docstatus != 0:
		return False
	return access.response.status != RESPONSE_COMPLETED
