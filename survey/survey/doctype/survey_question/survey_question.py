# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from survey.constants import (
	CHOICE_TYPES,
	COMMENTABLE_TYPES,
	DIRECTLY_SCORABLE_TYPES,
	MATRIX_SINGLE,
	PLACEHOLDER_TYPES,
	SCALE_ABSOLUTE_MAX,
	SCALE_ABSOLUTE_MIN,
	SCORING_NONE,
	TRIGGER_CAPABLE_TYPES,
	TYPE_MATRIX,
	TYPE_SCALE,
	TYPE_SHORT_TEXT,
	TYPES_WITH_OPTIONS,
	VALIDATABLE_TYPES,
)
from survey.utils.sequencing import next_sequence, recompute_sections, sequence_key


class SurveyQuestion(Document):
	# ------------------------------------------------------------------
	# Hooks
	# ------------------------------------------------------------------

	def before_insert(self):
		if not self.sequence:
			self.sequence = next_sequence(self.survey)

	def validate(self):
		self.validate_survey_is_editable()
		self.normalise_section()
		self.validate_question_type()
		self.validate_scale()
		self.validate_limits()
		self.validate_score()
		self.clear_inapplicable_fields()
		self.validate_triggers()
		self.set_is_scored()

	def on_update(self):
		self.sync_survey()

	def on_trash(self):
		self.validate_survey_is_editable()
		self.validate_not_a_trigger_source()
		self.delete_options()
		self.detach_own_triggers()

	def after_delete(self):
		self.sync_survey()

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_survey_is_editable(self):
		"""Refuse structural edits to a survey that already has responses.

		Editing a question that people have already answered silently changes
		the meaning of historical data — a renamed option, a flipped
		`is_correct`, a new mandatory flag. Odoo allows this freely; for an
		assessment product it is a data-integrity hazard, so we block it and
		point the user at duplicating the survey instead.

		Only *structural* changes are blocked. Cosmetic edits (title wording,
		description, placeholder, messages) stay allowed so typos remain
		fixable.
		"""
		if self.flags.ignore_response_guard or frappe.flags.in_survey_recompute:
			return

		if self.is_new():
			structural_change = True
		else:
			structural_change = bool(self.get_structural_changes())

		if not structural_change:
			return

		if not frappe.db.exists("Survey Response", {"survey": self.survey, "docstatus": ["!=", 2]}):
			return

		frappe.throw(
			_(
				"This survey already has responses, so its questions can no longer be "
				"changed. Duplicate the survey to make a new version."
			),
			title=_("Survey Is Locked"),
		)

	def get_structural_changes(self) -> list[str]:
		"""Fields whose change would alter the meaning of existing answers."""
		watched = (
			"survey",
			"is_section",
			"question_type",
			"mandatory",
			"matrix_subtype",
			"scale_min",
			"scale_max",
			"is_scored",
			"score",
			"correct_number",
			"correct_date",
			"correct_datetime",
			"validate_entry",
			"validate_email",
			"min_length",
			"max_length",
			"min_value",
			"max_value",
			"min_date",
			"max_date",
			"min_datetime",
			"max_datetime",
		)
		before = self.get_doc_before_save()
		if not before:
			return []

		return [field for field in watched if self.get(field) != before.get(field)]

	def normalise_section(self):
		"""A section is not a question: it has no type and no answer options."""
		if not self.is_section:
			return

		self.question_type = None
		self.section = None
		self.mandatory = 0
		self.is_scored = 0
		self.triggering_options = []

		if self.random_questions_count is None:
			self.random_questions_count = 1

	def validate_question_type(self):
		if self.is_section:
			return

		if not self.question_type:
			frappe.throw(_("Pick a question type."))

		if self.question_type == TYPE_MATRIX and not self.matrix_subtype:
			self.matrix_subtype = MATRIX_SINGLE

		if self.save_as_email and (self.question_type != TYPE_SHORT_TEXT or not self.validate_email):
			# Mirrors Odoo: only an email-validated single-line answer is
			# trustworthy enough to become the respondent's address.
			self.save_as_email = 0

		if self.save_as_nickname and self.question_type != TYPE_SHORT_TEXT:
			self.save_as_nickname = 0

	def validate_scale(self):
		if self.question_type != TYPE_SCALE:
			return

		if not (SCALE_ABSOLUTE_MIN <= (self.scale_min or 0) < (self.scale_max or 0) <= SCALE_ABSOLUTE_MAX):
			frappe.throw(
				_("The scale must be a growing range between {0} and {1}.").format(
					SCALE_ABSOLUTE_MIN, SCALE_ABSOLUTE_MAX
				)
			)

	def validate_limits(self):
		if not self.validate_entry or self.question_type not in VALIDATABLE_TYPES:
			return

		pairs = (
			("min_length", "max_length", _("length")),
			("min_value", "max_value", _("value")),
			("min_date", "max_date", _("date")),
			("min_datetime", "max_datetime", _("datetime")),
		)
		for min_field, max_field, label in pairs:
			minimum, maximum = self.get(min_field), self.get(max_field)
			if minimum and maximum and minimum > maximum:
				frappe.throw(_("The maximum {0} cannot be smaller than the minimum.").format(label))

		if (self.min_length or 0) < 0 or (self.max_length or 0) < 0:
			frappe.throw(_("A length cannot be negative."))

	def validate_score(self):
		"""A question's own score is a ceiling, so it cannot be negative.

		This used to live in `validate_limits`, which returns early unless
		`validate_entry` is on — meaning the rule only applied to questions
		that happened to have entry validation enabled. Penalties belong on
		individual options, where a negative score is meaningful.
		"""
		if (self.score or 0) < 0:
			frappe.throw(
				_("A question score cannot be negative. Penalise wrong answers per option instead.")
			)

	def clear_inapplicable_fields(self):
		"""Blank out settings that do not apply to the chosen type.

		Without this, a question switched from Numeric to Single Choice would
		keep a stale `min_value` that the player would then enforce.
		"""
		if self.is_section:
			return

		if self.question_type not in PLACEHOLDER_TYPES:
			self.placeholder = None

		if self.question_type not in COMMENTABLE_TYPES:
			self.allow_comments = 0

		if not self.allow_comments:
			self.comment_counts_as_answer = 0

		if self.question_type != TYPE_MATRIX:
			self.matrix_subtype = None

		if self.question_type != TYPE_SCALE:
			self.scale_min_label = self.scale_mid_label = self.scale_max_label = None

		if self.question_type not in VALIDATABLE_TYPES:
			self.validate_entry = 0

		if self.question_type != TYPE_SHORT_TEXT:
			self.validate_email = 0

		if not self.validate_entry:
			for field in (
				"min_length",
				"max_length",
				"min_value",
				"max_value",
				"min_date",
				"max_date",
				"min_datetime",
				"max_datetime",
			):
				self.set(field, 0 if field.endswith(("length", "value")) else None)

		if self.question_type not in DIRECTLY_SCORABLE_TYPES:
			self.correct_number = 0
			self.correct_date = None
			self.correct_datetime = None
			self.score = 0

		if self.question_type != "Numeric":
			self.correct_number = 0

		if self.question_type != "Date":
			self.correct_date = None

		if self.question_type != "Datetime":
			self.correct_datetime = None

	def validate_triggers(self):
		"""Skip logic: a trigger must be an *earlier choice question* here.

		Three separate failure modes, each with its own message so the builder
		can tell them apart:

		1. the trigger belongs to a different survey (a dangling reference);
		2. the trigger is not a choice question (nothing discrete to match on);
		3. the trigger sits at or after this question, so it could never have
		   been answered by the time this question is reached.

		(3) is recorded on `is_misplaced_trigger` rather than thrown, because
		while a survey is being built questions get reordered constantly and
		hard-failing would make the builder unusable. It is thrown only on the
		Survey itself, when the survey is moved to Open.
		"""
		self.is_misplaced_trigger = 0

		if self.is_section or not self.triggering_options:
			self.triggering_options = self.triggering_options or []
			return

		option_names = [row.option for row in self.triggering_options if row.option]
		if not option_names:
			return

		options = frappe.get_all(
			"Survey Question Option",
			filters={"name": ["in", option_names]},
			fields=["name", "question", "survey", "is_matrix_row"],
		)
		by_name = {row.name: row for row in options}

		trigger_question_names = {row.question for row in options}
		questions = frappe.get_all(
			"Survey Question",
			filters={"name": ["in", list(trigger_question_names)]} if trigger_question_names else {"name": ""},
			fields=["name", "survey", "question_type", "sequence", "is_section"],
		)
		questions_by_name = {row.name: row for row in questions}

		own_key = sequence_key(self)

		for row in self.triggering_options:
			option = by_name.get(row.option)
			if not option:
				frappe.throw(_("Triggering answer {0} no longer exists.").format(row.option))

			trigger = questions_by_name.get(option.question)
			if not trigger:
				frappe.throw(_("Triggering answer {0} has no question.").format(row.option))

			if trigger.survey != self.survey:
				frappe.throw(
					_("{0} belongs to another survey and cannot trigger this question.").format(
						trigger.name
					)
				)

			if trigger.is_section or trigger.question_type not in TRIGGER_CAPABLE_TYPES:
				frappe.throw(
					_(
						"Only single- and multiple-choice questions can trigger another "
						"question. {0} cannot."
					).format(trigger.name)
				)

			if option.is_matrix_row:
				frappe.throw(_("A matrix row cannot be used as a trigger."))

			if trigger.name == self.name:
				frappe.throw(_("A question cannot trigger itself."))

			if sequence_key(trigger) >= own_key:
				self.is_misplaced_trigger = 1

	def set_is_scored(self):
		"""Derive whether this question contributes to the score.

		Mirrors Odoo's `_compute_is_scored_question`: presence of a correct
		answer is what makes a question scored, not a separate switch. The
		only manual-looking case is Numeric, where a correct answer of 0.0 is
		indistinguishable from "unset" — there we require a non-zero score to
		treat it as scored, same as Odoo.
		"""
		if self.is_section or (self.scoring_type or SCORING_NONE) == SCORING_NONE:
			self.is_scored = 0
			return

		if self.question_type in CHOICE_TYPES:
			self.is_scored = 1 if self.has_correct_option() else 0
		elif self.question_type == "Date":
			self.is_scored = 1 if self.correct_date else 0
		elif self.question_type == "Datetime":
			self.is_scored = 1 if self.correct_datetime else 0
		elif self.question_type == "Numeric":
			self.is_scored = 1 if (self.correct_number or self.score) else 0
		else:
			self.is_scored = 0

	def has_correct_option(self) -> bool:
		if self.is_new():
			return False
		return bool(
			frappe.db.exists(
				"Survey Question Option",
				{"question": self.name, "is_correct": 1, "is_matrix_row": 0},
			)
		)

	def validate_not_a_trigger_source(self):
		"""Deleting a question that drives skip logic would orphan the rule."""
		dependents = frappe.db.sql(
			"""
			select distinct t.parent
			from `tabSurvey Question Trigger` t
			inner join `tabSurvey Question Option` o on o.name = t.option
			where o.question = %s and t.parent != %s
			""",
			(self.name, self.name),
			as_dict=True,
		)
		if dependents:
			titles = frappe.get_all(
				"Survey Question",
				filters={"name": ["in", [row.parent for row in dependents]]},
				pluck="title",
			)
			frappe.throw(
				_("These questions are shown based on an answer to this one: {0}").format(
					", ".join(titles)
				),
				title=_("Question Is in Use"),
			)

	# ------------------------------------------------------------------
	# Side effects
	# ------------------------------------------------------------------

	def delete_options(self):
		for name in frappe.get_all("Survey Question Option", filters={"question": self.name}, pluck="name"):
			frappe.delete_doc("Survey Question Option", name, force=True, ignore_permissions=True)

	def detach_own_triggers(self):
		frappe.db.delete("Survey Question Trigger", {"parent": self.name})

	def sync_survey(self):
		"""Re-derive the section chain and the survey's aggregate fields."""
		if frappe.flags.in_survey_recompute or not self.survey:
			return

		from survey.survey.doctype.survey.survey import recompute_derived_fields

		frappe.flags.in_survey_recompute = True
		try:
			recompute_sections(self.survey)
		finally:
			frappe.flags.in_survey_recompute = False

		recompute_derived_fields(self.survey)

	# ------------------------------------------------------------------
	# Read helpers used by the player and the reports
	# ------------------------------------------------------------------

	def get_options(self, matrix_rows: bool = False) -> list[dict]:
		"""Return this question's options (or its matrix rows), in order."""
		return frappe.get_all(
			"Survey Question Option",
			filters={"question": self.name, "is_matrix_row": 1 if matrix_rows else 0},
			fields=["name", "label", "value_label", "image", "is_correct", "score", "sequence"],
			order_by="sequence asc, creation asc",
		)

	def get_max_obtainable_score(self) -> float:
		"""The most points this single question can yield.

		Single choice awards the best option; multiple choice awards every
		positive option; the direct types award the question's own score.
		Negative option scores never reduce the ceiling — they only ever
		reduce what a respondent actually earns.
		"""
		if self.is_section or not self.is_scored:
			return 0.0

		if self.question_type in CHOICE_TYPES:
			scores = [
				row.score for row in self.get_options() if (row.score or 0) > 0
			]
			if not scores:
				return 0.0
			return float(max(scores)) if self.question_type == "Single Choice" else float(sum(scores))

		if self.question_type in DIRECTLY_SCORABLE_TYPES:
			return float(self.score or 0)

		return 0.0


def recompute_is_scored(question: str) -> bool:
	"""Re-derive `is_scored` for one question and store it if it changed.

	Frappe has no dependency graph, so this has to be pushed from whatever
	changed the inputs. It matters because `is_scored` is derived from the
	question's *options*, which are separate documents created after the
	question itself: without this, adding a correct answer to a choice
	question would leave `is_scored` at 0 forever and the whole survey would
	silently score zero.

	Returns whether anything changed, so callers can skip a pointless
	`db.set_value`.
	"""
	# The question can already be gone: deleting a question cascades to its
	# options, and each of those deletions calls back into here.
	if not frappe.db.exists("Survey Question", question):
		return False

	doc = frappe.get_doc("Survey Question", question)
	before = doc.is_scored
	doc.set_is_scored()

	if doc.is_scored == before:
		return False

	# A narrow write rather than a save: re-running validation here would
	# re-enter this path through the option sync and could fail on an
	# unrelated field of a question the user is not editing.
	frappe.db.set_value("Survey Question", question, "is_scored", doc.is_scored, update_modified=False)
	return True
