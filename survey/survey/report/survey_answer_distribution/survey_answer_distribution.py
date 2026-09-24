# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""How respondents split across each choice question's options.

Restricted to `Single Choice`/`Multiple Choice` questions (`answer_type ==
"Option"`, `matrix_row` empty — a matrix cell is a different shape of
question and reads oddly lumped in with plain choice questions). The
percentage is of respondents who actually answered *that* question, not of
every response on the survey — a question skipped by roaming, or one a
trigger hid for most respondents, should not look artificially rare.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Count


def execute(filters=None):
	filters = filters or {}
	if not filters.get("survey"):
		frappe.throw(_("Pick a survey."))

	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "question", "label": _("Question"), "fieldtype": "Link", "options": "Survey Question", "width": 200},
		{"fieldname": "question_title", "label": _("Question Title"), "fieldtype": "Data", "width": 220},
		{"fieldname": "option", "label": _("Option"), "fieldtype": "Link", "options": "Survey Question Option", "width": 160},
		{"fieldname": "option_label", "label": _("Option Label"), "fieldtype": "Data", "width": 200},
		{"fieldname": "count", "label": _("Respondents"), "fieldtype": "Int", "width": 100},
		{"fieldname": "percentage", "label": _("% of Answers"), "fieldtype": "Percent", "width": 120},
	]


def get_data(filters: dict) -> list[dict]:
	answer = frappe.qb.DocType("Survey Response Answer")
	response = frappe.qb.DocType("Survey Response")

	query = (
		frappe.qb.from_(answer)
		.join(response)
		.on(answer.parent == response.name)
		.select(
			answer.question.as_("question"),
			answer.question_title.as_("question_title"),
			answer.selected_option.as_("selected_option"),
			Count("*").as_("count"),
		)
		.where(response.docstatus == 1)
		.where(response.is_test == 0)
		.where(response.survey == filters["survey"])
		.where(answer.answer_type == "Option")
		.where(answer.matrix_row.isnull() | (answer.matrix_row == ""))
		.groupby(answer.question, answer.selected_option)
	)

	if filters.get("question"):
		query = query.where(answer.question == filters["question"])

	rows = query.run(as_dict=True)
	if not rows:
		return []

	option_labels = {
		row.name: row.label
		for row in frappe.get_all(
			"Survey Question Option",
			filters={"name": ["in", list({row.selected_option for row in rows if row.selected_option})]},
			fields=["name", "label"],
		)
	}

	totals_by_question: dict[str, int] = {}
	for row in rows:
		totals_by_question[row.question] = totals_by_question.get(row.question, 0) + row.count

	data = []
	for row in rows:
		total = totals_by_question.get(row.question) or 1
		data.append(
			{
				"question": row.question,
				"question_title": row.question_title,
				"option": row.selected_option,
				"option_label": option_labels.get(row.selected_option, row.selected_option or ""),
				"count": row.count,
				"percentage": round(row.count / total * 100, 1),
			}
		)

	data.sort(key=lambda r: (r["question_title"] or "", -r["count"]))
	return data
