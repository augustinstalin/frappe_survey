# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from survey.constants import (
	SCORING_NONE,
	TYPE_MATRIX,
	TYPES_WITH_OPTIONS,
)


class SurveyQuestionOption(Document):
	def validate(self):
		self.validate_owner_question()
		self.validate_value_present()
		self.validate_scoring()
		self.set_value_label()

	def after_insert(self):
		self.sync_parent_survey()

	def on_update(self):
		self.sync_parent_survey()

	def on_trash(self):
		self.detach_triggers()

	def after_delete(self):
		self.sync_parent_survey()

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_owner_question(self):
		"""An option only makes sense on a question that presents options."""
		question = frappe.db.get_value(
			"Survey Question",
			self.question,
			["is_section", "question_type", "title"],
			as_dict=True,
		)
		if not question:
			frappe.throw(_("Question {0} does not exist.").format(self.question))

		if question.is_section:
			frappe.throw(_("Sections cannot have answer options."))

		if question.question_type not in TYPES_WITH_OPTIONS:
			frappe.throw(
				_("{0} questions do not have answer options.").format(_(question.question_type))
			)

		if self.is_matrix_row and question.question_type != TYPE_MATRIX:
			frappe.throw(_("Only matrix questions can have rows."))

	def validate_value_present(self):
		"""Mirror Odoo: an option needs text, an image, or both — never neither."""
		if not (self.label or "").strip() and not self.image:
			frappe.throw(_("An answer needs a label, an image, or both."))

		if self.is_matrix_row and not (self.label or "").strip():
			frappe.throw(_("A matrix row needs a label."))

	def validate_scoring(self):
		"""Matrix cells and unscored surveys carry no score."""
		scoring_type = frappe.db.get_value("Survey", self.survey, "scoring_type") if self.survey else None

		if self.question_type == TYPE_MATRIX or scoring_type == SCORING_NONE:
			self.is_correct = 0
			self.score = 0

	def set_value_label(self):
		"""Image-only answers get a letter so they can be referred to and typed.

		The letter is the option's position in its question, matching Odoo's
		A, B, C... behaviour. Options past Z fall back to the empty string
		rather than producing confusing two-letter keys.
		"""
		label = (self.label or "").strip()
		if label:
			self.value_label = label
			return

		siblings = frappe.get_all(
			"Survey Question Option",
			filters={"question": self.question, "is_matrix_row": self.is_matrix_row},
			fields=["name", "sequence"],
			order_by="sequence asc, name asc",
		)
		index = next((i for i, row in enumerate(siblings) if row.name == self.name), None)

		if index is None:
			# Not yet persisted: it will be appended, so it takes the next letter.
			index = len(siblings)

		self.value_label = chr(ord("A") + index) if index < 26 else ""

	# ------------------------------------------------------------------
	# Side effects
	# ------------------------------------------------------------------

	def detach_triggers(self):
		"""Deleting an option must not leave dangling skip-logic references.

		Frappe does not cascade `Link` fields, so a trigger row pointing at a
		deleted option would silently make its question permanently invisible.
		We remove those rows instead.
		"""
		orphaned = frappe.get_all(
			"Survey Question Trigger",
			filters={"option": self.name},
			fields=["name", "parent"],
		)
		for row in orphaned:
			frappe.db.delete("Survey Question Trigger", {"name": row.name})

		affected_questions = {row.parent for row in orphaned if row.parent}
		for question in affected_questions:
			frappe.clear_document_cache("Survey Question", question)

	def sync_parent_survey(self):
		"""Push the two derived values this option feeds.

		Frappe has no dependency graph, so both recomputes have to be pushed
		from here:

		* the **question's** `is_scored`, which is derived from whether any of
		  its options is marked correct, and
		* the **survey's** `max_obtainable_score`, which sums those options.

		Order matters — `max_obtainable_score` skips questions that are not
		scored, so `is_scored` has to be right first.

		Both are narrow `db.set_value` passes rather than saves: re-saving
		would re-run every validation and could fail on an unrelated field of
		a document the user is not editing.
		"""
		if frappe.flags.in_survey_recompute:
			return

		from survey.survey.doctype.survey.survey import recompute_derived_fields
		from survey.survey.doctype.survey_question.survey_question import recompute_is_scored

		if self.question:
			recompute_is_scored(self.question)

		if self.survey:
			recompute_derived_fields(self.survey)
