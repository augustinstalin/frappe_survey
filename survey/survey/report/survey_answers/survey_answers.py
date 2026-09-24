# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""One row per answer given to a submitted (non-test) response.

`Survey Response Answer.get_value()` is already documented as "the answer as
a plain Python value, for reports and exports" — this is that report. The
resolved *display* text for an option answer (rather than the option's raw
docname) is looked up separately since it is not on the answer row itself.
"""

import frappe
from frappe import _
from frappe.query_builder import Order


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "response", "label": _("Response"), "fieldtype": "Link", "options": "Survey Response", "width": 160},
		{"fieldname": "survey", "label": _("Survey"), "fieldtype": "Link", "options": "Survey", "width": 160},
		{"fieldname": "respondent", "label": _("Respondent"), "fieldtype": "Data", "width": 160},
		{"fieldname": "question", "label": _("Question"), "fieldtype": "Link", "options": "Survey Question", "width": 200},
		{"fieldname": "question_title", "label": _("Question Title"), "fieldtype": "Data", "width": 220},
		{"fieldname": "answer", "label": _("Answer"), "fieldtype": "Data", "width": 220},
		{"fieldname": "skipped", "label": _("Skipped"), "fieldtype": "Check", "width": 80},
		{"fieldname": "is_correct", "label": _("Correct"), "fieldtype": "Check", "width": 80},
		{"fieldname": "score", "label": _("Score"), "fieldtype": "Float", "width": 80},
		{"fieldname": "completed_on", "label": _("Submitted On"), "fieldtype": "Datetime", "width": 160},
	]


def get_data(filters: dict) -> list[dict]:
	answer = frappe.qb.DocType("Survey Response Answer")
	response = frappe.qb.DocType("Survey Response")

	query = (
		frappe.qb.from_(answer)
		.join(response)
		.on(answer.parent == response.name)
		.select(
			response.name.as_("response"),
			response.survey.as_("survey"),
			response.email.as_("email"),
			response.nickname.as_("nickname"),
			response.user.as_("user"),
			response.completed_on.as_("completed_on"),
			answer.question.as_("question"),
			answer.question_title.as_("question_title"),
			answer.skipped.as_("skipped"),
			answer.answer_type.as_("answer_type"),
			answer.value_text.as_("value_text"),
			answer.value_long_text.as_("value_long_text"),
			answer.value_number.as_("value_number"),
			answer.value_scale.as_("value_scale"),
			answer.value_date.as_("value_date"),
			answer.value_datetime.as_("value_datetime"),
			answer.selected_option.as_("selected_option"),
			answer.is_correct.as_("is_correct"),
			answer.score.as_("score"),
		)
		.where(response.docstatus == 1)
		.where(response.is_test == 0)
		.where(answer.answer_type != "Comment")
		.orderby(response.completed_on, order=Order.desc)
	)

	if filters.get("survey"):
		query = query.where(response.survey == filters["survey"])
	if filters.get("question"):
		query = query.where(answer.question == filters["question"])
	if filters.get("from_date"):
		query = query.where(response.completed_on >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(response.completed_on <= filters["to_date"])

	rows = query.run(as_dict=True)

	option_names = {row.selected_option for row in rows if row.answer_type == "Option" and row.selected_option}
	option_labels = (
		{
			r.name: r.label
			for r in frappe.get_all(
				"Survey Question Option", filters={"name": ["in", list(option_names)]}, fields=["name", "label"]
			)
		}
		if option_names
		else {}
	)

	return [_format_row(row, option_labels) for row in rows]


def _format_row(row: dict, option_labels: dict) -> dict:
	if row.skipped:
		answer_text = ""
	elif row.answer_type == "Option":
		answer_text = option_labels.get(row.selected_option, row.selected_option or "")
	else:
		answer_text = (
			row.value_text
			or row.value_long_text
			or row.value_number
			or row.value_scale
			or row.value_date
			or row.value_datetime
			or ""
		)

	return {
		"response": row.response,
		"survey": row.survey,
		"respondent": row.nickname or row.user or row.email or _("Anonymous"),
		"question": row.question,
		"question_title": row.question_title,
		"answer": answer_text,
		"skipped": row.skipped,
		"is_correct": row.is_correct,
		"score": row.score,
		"completed_on": row.completed_on,
	}
