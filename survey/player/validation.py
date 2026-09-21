"""Server-side answer validation.

The player runs the same rules in the browser to avoid a round trip, but this
module is the authority: the endpoints are public, so anything the client
checks must be re-checked here.

Every function returns an error *message* or `None`. Nothing throws — a page
submit reports every bad answer at once, so the respondent fixes them in one
pass rather than one per attempt.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from survey.constants import (
	CHOICE_TYPES,
	TYPE_DATE,
	TYPE_DATETIME,
	TYPE_MATRIX,
	TYPE_MULTIPLE_CHOICE,
	TYPE_NUMERIC,
	TYPE_SCALE,
	TYPE_SHORT_TEXT,
	TYPE_SINGLE_CHOICE,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_answer(question, value, comment: str | None = None, allow_roaming: bool = False) -> str | None:
	"""Check one answer. Returns an error message, or None when it is fine.

	:param value: the normalised answer — a scalar, a list of option names, or
		a `{row: [columns]}` map for a matrix.
	:param allow_roaming: when the survey lets respondents move around freely,
		a mandatory question does not block the page; it is recorded as
		skipped and they are walked back to it before finishing.
	"""
	if isinstance(value, str):
		value = value.strip()

	if is_empty(value):
		return _check_required(question, comment, allow_roaming)

	checks = {
		TYPE_SHORT_TEXT: _validate_short_text,
		TYPE_NUMERIC: _validate_numeric,
		TYPE_SCALE: _validate_scale,
		TYPE_DATE: _validate_date,
		TYPE_DATETIME: _validate_datetime,
		TYPE_SINGLE_CHOICE: _validate_choice,
		TYPE_MULTIPLE_CHOICE: _validate_choice,
		TYPE_MATRIX: _validate_matrix,
	}
	check = checks.get(question.question_type)
	return check(question, value) if check else None


def is_empty(value) -> bool:
	"""Whether an answer counts as "not given".

	`0` and `0.0` are real answers to a numeric or scale question, so this
	cannot be a plain truthiness test.
	"""
	if value is None:
		return True
	if isinstance(value, (int, float)):
		return False
	if isinstance(value, str):
		return not value.strip()
	if isinstance(value, (list, tuple, set, dict)):
		return not value
	return False


def _check_required(question, comment: str | None, allow_roaming: bool) -> str | None:
	if not question.mandatory:
		return None

	# On a choice question that accepts comments as answers, a comment alone
	# satisfies the requirement.
	if question.comment_counts_as_answer and (comment or "").strip():
		return None

	if allow_roaming:
		# Recorded as skipped; the respondent is brought back to it before
		# they can finish.
		return None

	return question.mandatory_error_message or _("This question requires an answer.")


# ----------------------------------------------------------------------
# Per type
# ----------------------------------------------------------------------


def _validate_short_text(question, value) -> str | None:
	text = str(value)

	if question.validate_email and not EMAIL_PATTERN.match(text):
		return _("This answer must be an email address.")

	if not question.validate_entry:
		return None

	minimum, maximum = cint(question.min_length), cint(question.max_length)

	# A maximum of 0 means "no upper bound", matching how the field reads in
	# the builder when it is left alone.
	if minimum and len(text) < minimum:
		return _invalid(question)
	if maximum and len(text) > maximum:
		return _invalid(question)

	return None


def _validate_numeric(question, value) -> str | None:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return _("Please enter a number.")

	if not question.validate_entry:
		return None

	minimum, maximum = flt(question.min_value), flt(question.max_value)
	if minimum and number < minimum:
		return _invalid(question)
	if maximum and number > maximum:
		return _invalid(question)

	return None


def _validate_scale(question, value) -> str | None:
	try:
		number = int(value)
	except (TypeError, ValueError):
		return _("Please pick a value on the scale.")

	if not (cint(question.scale_min) <= number <= cint(question.scale_max)):
		return _("Pick a value between {0} and {1}.").format(question.scale_min, question.scale_max)

	return None


def _validate_date(question, value) -> str | None:
	try:
		given = getdate(value)
	except Exception:
		return _("Please enter a valid date.")

	if not question.validate_entry:
		return None

	if question.min_date and given < getdate(question.min_date):
		return _invalid(question)
	if question.max_date and given > getdate(question.max_date):
		return _invalid(question)

	return None


def _validate_datetime(question, value) -> str | None:
	try:
		given = get_datetime(value)
	except Exception:
		return _("Please enter a valid date and time.")

	if not question.validate_entry:
		return None

	if question.min_datetime and given < get_datetime(question.min_datetime):
		return _invalid(question)
	if question.max_datetime and given > get_datetime(question.max_datetime):
		return _invalid(question)

	return None


def _validate_choice(question, value) -> str | None:
	selected = value if isinstance(value, list) else [value]

	if question.question_type == TYPE_SINGLE_CHOICE and len(selected) > 1:
		return _("Please select only one answer.")

	valid = set(
		frappe.get_all(
			"Survey Question Option",
			filters={"question": question.name, "is_matrix_row": 0},
			pluck="name",
		)
	)
	unknown = [option for option in selected if option not in valid]
	if unknown:
		# Not a respondent mistake — the client sent an option that does not
		# belong to this question.
		return _("That answer is not available for this question.")

	return None


def _validate_matrix(question, value) -> str | None:
	if not isinstance(value, dict):
		return _("That answer is not valid for this question.")

	rows = set(
		frappe.get_all(
			"Survey Question Option",
			filters={"question": question.name, "is_matrix_row": 1},
			pluck="name",
		)
	)
	columns = set(
		frappe.get_all(
			"Survey Question Option",
			filters={"question": question.name, "is_matrix_row": 0},
			pluck="name",
		)
	)

	answered_rows = set()
	for row, picked in value.items():
		if row not in rows:
			return _("That answer is not available for this question.")

		picked = picked if isinstance(picked, list) else [picked]
		picked = [column for column in picked if column]

		if any(column not in columns for column in picked):
			return _("That answer is not available for this question.")

		if question.matrix_subtype == "One Choice Per Row" and len(picked) > 1:
			return _("Please select only one answer per row.")

		if picked:
			answered_rows.add(row)

	if question.mandatory and answered_rows != rows:
		return question.mandatory_error_message or _("Please answer every row.")

	return None


def _invalid(question) -> str:
	return question.validation_error_message or _("The answer you entered is not valid.")


# ----------------------------------------------------------------------
# Page-level
# ----------------------------------------------------------------------


def validate_page(questions: list, answers: dict, allow_roaming: bool = False) -> dict[str, str]:
	"""Validate every question on a page. Returns `{question: error}`.

	An empty dict means the page is good to save.
	"""
	errors = {}

	for question in questions:
		payload = answers.get(question.name) or {}
		error = validate_answer(
			question,
			payload.get("value"),
			payload.get("comment"),
			allow_roaming=allow_roaming,
		)
		if error:
			errors[question.name] = error

	return errors
