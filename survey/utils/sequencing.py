"""Ordering of questions within a survey, and the section each one belongs to.

The survey builder is a single flat, ordered list in which a row is either a
*section* (`is_section = 1`) or a *question*. A question belongs to the last
section that appears before it in that order. That relationship is stored on
`Survey Question.section` so answers and reports can join on it, but it is
**derived** — reordering the list re-parents questions silently, exactly as it
does in the Odoo original.
"""

import frappe

from survey.constants import SEQUENCE_STEP


def sequence_key(row) -> tuple:
	"""Sort key matching the DocType's own ordering (`sequence`, then `name`).

	Ties on `sequence` are broken by `name` so the order is total and stable,
	which matters because trigger validity is defined in terms of "appears
	before".
	"""
	if isinstance(row, dict):
		return (row.get("sequence") or 0, row.get("name") or "")
	return (row.sequence or 0, row.name or "")


def next_sequence(survey: str) -> int:
	"""Return the sequence to give a question appended to the end of `survey`."""
	# Not `max(sequence)`: Frappe v16 rejects SQL functions passed to
	# `get_value` as strings. Ordering descending gives the same answer.
	current_max = frappe.db.get_value(
		"Survey Question", {"survey": survey}, "sequence", order_by="sequence desc"
	)
	return (current_max or 0) + SEQUENCE_STEP


def get_ordered_rows(survey: str) -> list[dict]:
	"""Return every row of the builder list, in display order."""
	rows = frappe.get_all(
		"Survey Question",
		filters={"survey": survey},
		fields=["name", "sequence", "is_section", "section"],
	)
	return sorted(rows, key=sequence_key)


def recompute_sections(survey: str) -> int:
	"""Re-derive `section` for every question of `survey`.

	Returns the number of rows actually changed, so callers can skip a
	`db.commit` / cache clear when nothing moved.

	Writes go through `db.set_value` with `update_modified=False`: this is a
	derived value, not a user edit, and we do not want it to churn the
	document's modification stamp (or trigger another round of hooks).
	"""
	changed = 0
	current_section = None

	for row in get_ordered_rows(survey):
		if row.is_section:
			current_section = row.name
			expected = None
		else:
			expected = current_section

		if row.section != expected:
			frappe.db.set_value(
				"Survey Question", row.name, "section", expected, update_modified=False
			)
			changed += 1

	return changed


def reorder_questions(survey: str, ordered_names: list[str]) -> None:
	"""Persist a new builder order.

	`ordered_names` must be the complete list of question names for `survey`;
	anything missing would silently lose its position, so we refuse instead.
	"""
	existing = {row.name for row in get_ordered_rows(survey)}
	incoming = set(ordered_names)

	if existing != incoming:
		frappe.throw(
			frappe._("The submitted question order does not match this survey's questions."),
			title=frappe._("Cannot Reorder"),
		)

	for index, name in enumerate(ordered_names, start=1):
		frappe.db.set_value(
			"Survey Question",
			name,
			"sequence",
			index * SEQUENCE_STEP,
			update_modified=False,
		)

	recompute_sections(survey)
