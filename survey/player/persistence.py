"""Turning a submitted page into `Survey Response Answer` rows.

Shape of the data, which is what makes this fiddly: one answer row holds one
*datum*, not one question. A multiple-choice question with three ticks
produces three rows; a matrix produces one row per answered cell; an "other,
please specify" comment produces its own row alongside the options.

Two write strategies, following Odoo:

* **Simple answers** (text, number, scale, date) overwrite in place — there is
  exactly one row, so it is updated.
* **Choice and matrix answers** are deleted and recreated. Trying to diff two
  sets of selections against existing rows is more code and more bugs than
  rewriting them, and it makes the score recompute fall out naturally.

A question that is shown but left unanswered still gets a row, flagged
`skipped`. Without it, "nobody answered this" and "this was never shown"
would be indistinguishable in the statistics.
"""

import frappe
from frappe.utils import cint, flt

from survey.constants import (
	CHOICE_TYPES,
	QUESTION_TYPE_TO_ANSWER_TYPE,
	TYPE_MATRIX,
	TYPE_SCALE,
	TYPE_NUMERIC,
)
from survey.player.validation import is_empty


def save_page_answers(response, questions: list, answers: dict) -> None:
	"""Persist every answer on one page, then save the response once.

	The single save at the end matters: each save re-scores the whole response
	and re-runs its validation, so doing it per question would be both slow
	and noisy.

	Only questions the submission actually mentions are written. `questions`
	deliberately includes ones that are hidden as far as the *stored* answers
	go, so that a question unlocked on this very page is saved; but a question
	the respondent never saw is not in the payload, and writing a "skipped"
	row for it would record an answer to a question that was never asked.
	"""
	for question in questions:
		if question.name not in answers:
			continue

		payload = answers.get(question.name) or {}
		_replace_answers(response, question, payload.get("value"), payload.get("comment"))

	response.save(ignore_permissions=True)


def _replace_answers(response, question, value, comment: str | None) -> None:
	"""Drop this question's existing rows and write the new ones."""
	_remove_rows(response, question.name)

	rows = _build_rows(question, value, comment)
	for row in rows:
		response.append("answers", row)

	_apply_identity_side_effects(response, question, value)


def _remove_rows(response, question: str) -> None:
	remaining = [row for row in response.answers if row.question != question]
	response.set("answers", remaining)


def _build_rows(question, value, comment: str | None) -> list[dict]:
	"""The rows one answered question becomes."""
	rows: list[dict] = []

	if question.question_type == TYPE_MATRIX:
		rows.extend(_matrix_rows(question, value))
	elif question.question_type in CHOICE_TYPES:
		rows.extend(_choice_rows(question, value))
	else:
		rows.append(_simple_row(question, value))

	if (comment or "").strip():
		rows.append(
			{
				"question": question.name,
				"answer_type": "Comment",
				"value_text": comment.strip(),
				"skipped": 0,
			}
		)

	return rows


def _simple_row(question, value) -> dict:
	if is_empty(value):
		return _skipped_row(question)

	answer_type = QUESTION_TYPE_TO_ANSWER_TYPE.get(question.question_type)
	if not answer_type:
		return _skipped_row(question)

	row = {"question": question.name, "answer_type": answer_type, "skipped": 0}

	if question.question_type == TYPE_NUMERIC:
		row["value_number"] = flt(value)
	elif question.question_type == TYPE_SCALE:
		row["value_scale"] = cint(value)
	elif question.question_type == "Date":
		row["value_date"] = value
	elif question.question_type == "Datetime":
		row["value_datetime"] = value
	elif question.question_type == "Multiple Line Text":
		row["value_long_text"] = value
	else:
		row["value_text"] = value

	return row


def _choice_rows(question, value) -> list[dict]:
	selected = value if isinstance(value, list) else ([value] if not is_empty(value) else [])
	selected = [option for option in selected if option]

	if not selected:
		return [_skipped_row(question)]

	return [
		{
			"question": question.name,
			"answer_type": "Option",
			"selected_option": option,
			"skipped": 0,
		}
		for option in selected
	]


def _matrix_rows(question, value) -> list[dict]:
	if not isinstance(value, dict) or not value:
		return [_skipped_row(question)]

	rows = []
	for row_option, picked in value.items():
		picked = picked if isinstance(picked, list) else [picked]
		for column in picked:
			if not column:
				continue
			rows.append(
				{
					"question": question.name,
					"answer_type": "Option",
					"selected_option": column,
					"matrix_row": row_option,
					"skipped": 0,
				}
			)

	return rows or [_skipped_row(question)]


def _skipped_row(question) -> dict:
	"""A question that was shown and left blank.

	`answer_type` must be empty: the DocType enforces "skipped XOR answered".
	"""
	return {"question": question.name, "skipped": 1, "answer_type": None}


def _apply_identity_side_effects(response, question, value) -> None:
	"""Some answers are about the respondent, not the subject.

	A question flagged `save_as_email` or `save_as_nickname` writes onto the
	response itself, so invitations, certificates and the leaderboard have
	something to address the person by.
	"""
	if is_empty(value) or not isinstance(value, str):
		return

	text = value.strip()

	if question.save_as_email:
		response.email = text

	if question.save_as_nickname:
		response.nickname = text


def clear_hidden_answers(response) -> int:
	"""Delete answers to questions whose trigger is no longer satisfied.

	Reachable state: the respondent ticks "Yes", answers the follow-up, then
	goes back and changes it to "No". The follow-up is hidden again, and its
	answer must not keep counting toward the score or keep unlocking whatever
	*it* triggers.

	Odoo notes the same drawback we inherit: a long free-text answer is lost
	if the respondent flips the trigger back and forth. Fixing that means
	keeping orphaned answers around, which then have to be excluded from
	scoring everywhere — a worse trade.
	"""
	hidden = response.get_inactive_questions()
	if not hidden:
		return 0

	remaining = [row for row in response.answers if row.question not in hidden]
	removed = len(response.answers) - len(remaining)

	if removed:
		response.set("answers", remaining)

	return removed
