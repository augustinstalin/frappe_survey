"""Builders for test fixtures.

Keeps the tests readable: each one states only the thing it is about, and
inherits sensible defaults for everything else.
"""

import frappe

from survey.constants import SEQUENCE_STEP, STATUS_DRAFT


def make_survey(**values):
	values.setdefault("title", frappe.generate_hash(length=8))
	values.setdefault("status", STATUS_DRAFT)
	values.setdefault("survey_type", "Custom")

	return frappe.get_doc({"doctype": "Survey", **values}).insert(ignore_permissions=True)


def make_question(survey, **values):
	name = survey.name if hasattr(survey, "name") else survey

	values.setdefault("title", frappe.generate_hash(length=8))
	values.setdefault("question_type", "Single Choice")

	if "sequence" not in values:
		values["sequence"] = (
			frappe.db.get_value(
				"Survey Question", {"survey": name}, "sequence", order_by="sequence desc"
			)
			or 0
		) + SEQUENCE_STEP

	ignore_guard = values.pop("ignore_response_guard", False)

	doc = frappe.get_doc({"doctype": "Survey Question", "survey": name, **values})
	doc.flags.ignore_response_guard = ignore_guard
	return doc.insert(ignore_permissions=True)


def make_section(survey, **values):
	values["is_section"] = 1
	values.pop("question_type", None)
	return make_question(survey, question_type=None, **values)


def make_option(question, label: str, **values):
	name = question.name if hasattr(question, "name") else question

	if "sequence" not in values:
		values["sequence"] = (
			frappe.db.get_value(
				"Survey Question Option", {"question": name}, "sequence", order_by="sequence desc"
			)
			or 0
		) + SEQUENCE_STEP

	return frappe.get_doc(
		{
			"doctype": "Survey Question Option",
			"question": name,
			"label": label,
			**values,
		}
	).insert(ignore_permissions=True)


def make_response(survey, **values):
	name = survey.name if hasattr(survey, "name") else survey

	return frappe.get_doc({"doctype": "Survey Response", "survey": name, **values}).insert(
		ignore_permissions=True
	)


def answer(response, question, **values):
	"""Append one answer row and save."""
	name = question.name if hasattr(question, "name") else question
	response.append("answers", {"question": name, **values})
	response.save(ignore_permissions=True)
	return response
