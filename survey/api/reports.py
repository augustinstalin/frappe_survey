"""Results dashboard with cross-question answer filtering.

This is the one piece of Phase 5 that a plain Query Report genuinely cannot
express: "show me every respondent who answered Q1=B *and* Q3=Yes" needs
AND-able filter rows built at request time, not a fixed `GROUP BY`. Backs the
`survey-results` Desk Page.

Desk-only throughout — a Survey Manager/User looking at their own results,
never guest-callable like `survey.api.player`.
"""

import json

import frappe
from frappe import _


@frappe.whitelist()
def get_dashboard_summary(survey: str) -> dict:
	"""The header numbers: how many responses, how they're doing."""
	frappe.has_permission("Survey Response", "read", throw=True)

	base_filters = {"survey": survey, "is_test": 0}
	total = frappe.db.count("Survey Response", base_filters)
	completed = frappe.db.count("Survey Response", {**base_filters, "docstatus": 1})

	survey_doc = frappe.get_cached_doc("Survey", survey)
	average_score = None
	pass_rate = None

	if survey_doc.scoring_type != "No Scoring" and completed:
		scored = frappe.get_all(
			"Survey Response",
			filters={**base_filters, "docstatus": 1},
			fields=["score_percentage", "passed"],
		)
		average_score = round(sum(r.score_percentage or 0 for r in scored) / len(scored), 1)
		pass_rate = round(sum(1 for r in scored if r.passed) / len(scored) * 100, 1)

	return {
		"total_responses": total,
		"completed_responses": completed,
		"completion_rate": round(completed / total * 100, 1) if total else 0,
		"average_score": average_score,
		"pass_rate": pass_rate,
	}


@frappe.whitelist()
def get_choice_questions(survey: str) -> list[dict]:
	"""Every Single/Multiple Choice question and its options.

	What the filter-row builder in the results page offers to pick from —
	only choice questions have the fixed, discrete answers a "Q = option"
	filter row needs.
	"""
	frappe.has_permission("Survey Response", "read", throw=True)

	questions = frappe.get_all(
		"Survey Question",
		filters={"survey": survey, "question_type": ["in", ["Single Choice", "Multiple Choice"]]},
		fields=["name", "title"],
		order_by="sequence asc",
	)
	for question in questions:
		question["options"] = frappe.get_all(
			"Survey Question Option",
			filters={"question": question.name, "is_matrix_row": 0},
			fields=["name", "label"],
			order_by="sequence asc",
		)

	return questions


@frappe.whitelist()
def get_filtered_responses(survey: str, filters: list | str | None = None) -> dict:
	"""Respondents matching every filter row, ANDed together.

	Each row is `{"question": <name>, "option": <name>}`; a respondent
	matches only if they picked that option on that question. Rows are
	intersected in Python rather than built as SQL `EXISTS` subqueries — one
	indexed lookup per row, narrowing a plain Python `set` — which stays
	simple and correct for the handful of filter rows a person would
	actually build in this UI, without hand-rolling per-row subquery
	aliasing in the query builder for a repeated join against the same
	table.
	"""
	frappe.has_permission("Survey Response", "read", throw=True)

	rows = _parse_filters(filters)

	names = set(
		frappe.get_all(
			"Survey Response",
			filters={"survey": survey, "docstatus": 1, "is_test": 0},
			pluck="name",
		)
	)

	for row in rows:
		question, option = row.get("question"), row.get("option")
		if not question or not option:
			continue

		names &= set(
			frappe.get_all(
				"Survey Response Answer",
				filters={
					"question": question,
					"selected_option": option,
					"parent": ["in", list(names)],
				},
				pluck="parent",
			)
		)
		if not names:
			break

	if not names:
		return {"total": 0, "rows": []}

	responses = frappe.get_all(
		"Survey Response",
		filters={"name": ["in", list(names)]},
		fields=[
			"name",
			"user",
			"email",
			"nickname",
			"total_score",
			"score_percentage",
			"passed",
			"completed_on",
		],
		order_by="completed_on desc",
	)

	for response in responses:
		response["respondent"] = response.nickname or response.user or response.email or _("Anonymous")

	return {"total": len(responses), "rows": responses}


def _parse_filters(filters) -> list[dict]:
	if not filters:
		return []
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except (ValueError, TypeError):
			frappe.throw(_("Could not read the filter rows."))
	if not isinstance(filters, list):
		frappe.throw(_("Could not read the filter rows."))
	return [row for row in filters if isinstance(row, dict)]
