"""`/my/surveys` — a signed-in respondent's own survey history.

Login-required, same as any other `/my/*` portal page: a guest is bounced to
`/login?redirect-to=/my/surveys` rather than shown an empty list. Anonymous,
un-invited responses have no `user` to match against and never appear here —
that is the whole reason the cookie/token pair exists for them instead.
"""

from urllib.parse import quote

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(frappe.request.path)
		raise frappe.Redirect

	context.responses = get_my_responses()
	return context


def get_my_responses() -> list[dict]:
	rows = frappe.get_all(
		"Survey Response",
		filters={"user": frappe.session.user},
		fields=[
			"name",
			"survey",
			"status",
			"docstatus",
			"access_token",
			"total_score",
			"score_percentage",
			"passed",
			"started_on",
			"completed_on",
		],
		order_by="creation desc",
	)

	surveys = frappe.get_all(
		"Survey",
		filters={"name": ["in", [row.survey for row in rows]]} if rows else {"name": ["in", []]},
		fields=["name", "title", "access_token", "scoring_type"],
	)
	survey_by_name = {row.name: row for row in surveys}

	for row in rows:
		survey = survey_by_name.get(row.survey)
		row["survey_title"] = survey.title if survey else row.survey
		row["is_scored"] = bool(survey and survey.scoring_type != "No Scoring")
		row["url"] = (
			f"/s/{survey.access_token}?r={row.access_token}" if survey else None
		)
		row["is_completed"] = row.status == "Completed" or row.docstatus == 1

	return rows
