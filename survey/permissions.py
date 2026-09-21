"""Row-level access for the Survey app.

Two groups, mirroring Odoo:

* **Survey Manager** sees and edits everything.
* **Survey User** sees a survey when it is unrestricted, *or* when they are
  named in its `restricted_to` list.

That "unrestricted OR listed" shape is why this is a permission query
condition rather than a User Permission: a User Permission can only express
"the value must be one of these", and cannot let an empty restriction list
mean "everyone".

`Survey Respondent` is not handled here at all. Respondents never read these
DocTypes through the permission system — the public endpoints authenticate
them with an access token and then act with `ignore_permissions`.
"""

import frappe

from survey.constants import ROLE_MANAGER


def _is_manager(user: str) -> bool:
	return ROLE_MANAGER in frappe.get_roles(user) or user == "Administrator"


def _restriction_clause(alias: str, user: str) -> str:
	"""SQL that is true when `alias` is a survey this user may work on."""
	escaped = frappe.db.escape(user)
	return f"""(
		{alias} not in (select distinct parent from `tabSurvey User Restriction` where parenttype = 'Survey')
		or {alias} in (
			select parent from `tabSurvey User Restriction`
			where parenttype = 'Survey' and user = {escaped}
		)
	)"""


def get_permission_query_conditions(user: str | None = None) -> str:
	"""For `Survey` itself."""
	user = user or frappe.session.user
	if _is_manager(user):
		return ""
	return _restriction_clause("`tabSurvey`.name", user)


def get_question_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_manager(user):
		return ""
	return _restriction_clause("`tabSurvey Question`.survey", user)


def get_option_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_manager(user):
		return ""
	return _restriction_clause("`tabSurvey Question Option`.survey", user)


def get_response_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_manager(user):
		return ""

	# A respondent may always read their own response, whatever the survey's
	# restriction says.
	escaped = frappe.db.escape(user)
	return f"""(
		{_restriction_clause("`tabSurvey Response`.survey", user)}
		or `tabSurvey Response`.user = {escaped}
		or `tabSurvey Response`.owner = {escaped}
	)"""


# ----------------------------------------------------------------------
# Document-level checks
#
# The query conditions above filter lists and reports; these guard direct
# `frappe.get_doc(...).check_permission()` calls, which bypass them.
# ----------------------------------------------------------------------


def has_survey_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_manager(user):
		return True

	restricted = {row.user for row in (doc.get("restricted_to") or [])}
	return not restricted or user in restricted


def has_question_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_manager(user) or not doc.get("survey"):
		return True

	return _survey_is_allowed(doc.survey, user)


def has_option_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_manager(user):
		return True

	survey = doc.get("survey") or frappe.db.get_value("Survey Question", doc.get("question"), "survey")
	return _survey_is_allowed(survey, user) if survey else True


def has_response_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_manager(user):
		return True

	if doc.get("user") == user or doc.get("owner") == user:
		return True

	return _survey_is_allowed(doc.get("survey"), user)


def _survey_is_allowed(survey: str | None, user: str) -> bool:
	if not survey:
		return True

	restricted = frappe.get_all(
		"Survey User Restriction",
		filters={"parent": survey, "parenttype": "Survey"},
		pluck="user",
	)
	return not restricted or user in restricted


def has_app_permission(user: str | None = None) -> bool:
	"""Whether to show the Survey tile on the apps screen.

	Called by `add_to_apps_screen`. Anyone who can work on surveys at all
	gets the tile; everybody else does not see the app.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))
	return bool(roles & {ROLE_MANAGER, ROLE_USER})
