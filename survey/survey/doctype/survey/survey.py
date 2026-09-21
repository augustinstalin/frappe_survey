# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from survey.constants import (
	ACCESS_INVITED,
	ACCESS_PUBLIC,
	PAGINATION_ONE_PAGE,
	PAGINATION_PER_QUESTION,
	PAGINATION_PER_SECTION,
	ROLE_MANAGER,
	SCORING_AFTER_PAGE,
	SCORING_NONE,
	SCORING_WITH_ANSWERS,
	SELECTION_ALL,
	STATUS_CLOSED,
	STATUS_DRAFT,
	STATUS_OPEN,
	SURVEY_TYPE_ASSESSMENT,
	SURVEY_TYPE_LIVE_SESSION,
	SURVEY_TYPE_SURVEY,
)
from survey.utils.sequencing import recompute_sections, sequence_key
from survey.utils.tokens import generate_token


class Survey(Document):
	# ------------------------------------------------------------------
	# Hooks
	# ------------------------------------------------------------------

	def before_insert(self):
		if not self.access_token:
			self.access_token = generate_token()
		if not self.responsible:
			self.responsible = frappe.session.user

	def validate(self):
		self.apply_type_defaults()
		# Derived first: validate_timing_and_attempts reads
		# has_conditional_questions, which is one of the derived values.
		self.set_derived_fields()
		self.validate_scoring()
		self.validate_timing_and_attempts()
		self.validate_roaming()
		self.validate_certification()
		self.validate_restriction()
		self.validate_ready_to_open()

	def on_update(self):
		recompute_sections(self.name)

	def on_trash(self):
		self.validate_no_responses()
		self.delete_questions()
		self.release_badge()

	def release_badge(self):
		if self.badge:
			frappe.db.set_value("Survey Badge", self.badge, "survey", None, update_modified=False)

	# ------------------------------------------------------------------
	# Defaults
	# ------------------------------------------------------------------

	def apply_type_defaults(self):
		"""Apply the settings each survey type implies.

		Only applied when the type actually changes (or on insert), so that a
		manager who deliberately tweaks a setting afterwards does not have it
		reverted on the next save. Odoo applies these in an onchange, which
		has the same "only when the user switches" semantics.
		"""
		before = self.get_doc_before_save()
		type_changed = self.is_new() or (before and before.survey_type != self.survey_type)

		if not type_changed:
			return

		if self.survey_type == SURVEY_TYPE_SURVEY:
			# Plain feedback: never scored, never timed.
			self.scoring_type = SCORING_NONE
			self.is_certification = 0
			self.is_time_limited = 0

		elif self.survey_type == SURVEY_TYPE_ASSESSMENT:
			self.access_mode = ACCESS_INVITED
			if self.scoring_type == SCORING_NONE:
				self.scoring_type = SCORING_WITH_ANSWERS

		elif self.survey_type == SURVEY_TYPE_LIVE_SESSION:
			# Live sessions are driven by a host, one question at a time, for
			# everyone at once. Most per-respondent settings make no sense.
			self.access_mode = ACCESS_PUBLIC
			self.pagination = PAGINATION_PER_QUESTION
			self.question_selection = SELECTION_ALL
			self.progress_display = "Percentage"
			self.allow_roaming = 0
			self.limit_attempts = 0
			self.is_time_limited = 0
			self.is_certification = 0
			if self.scoring_type == SCORING_NONE:
				self.scoring_type = SCORING_WITH_ANSWERS

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_scoring(self):
		if self.scoring_type == SCORING_NONE:
			self.is_certification = 0
			self.passing_score = 0
			return

		if not 0 <= flt(self.passing_score) <= 100:
			frappe.throw(_("The required score must be between 0 and 100."))

	def validate_timing_and_attempts(self):
		if self.is_time_limited and flt(self.time_limit) <= 0:
			frappe.throw(_("A time-limited survey needs a positive time limit."))

		if self.limit_attempts and cint(self.attempts_limit) <= 0:
			frappe.throw(_("Set a positive number of attempts, or turn off the attempt limit."))

		# Attempt limiting needs a stable identity to count against, and a
		# stable question set to compare attempts across. Neither holds for an
		# anonymous public survey or one with conditional questions, so the
		# setting is switched off rather than silently misbehaving.
		if self.limit_attempts:
			if self.access_mode == ACCESS_PUBLIC and not self.login_required:
				self.limit_attempts = 0
			elif self.has_conditional_questions:
				self.limit_attempts = 0

	def validate_roaming(self):
		"""Roaming and per-page answer reveal cannot coexist.

		Revealing the answers after a page and then letting the respondent
		walk back into that page would let them correct a scored answer they
		have already been shown.
		"""
		if self.allow_roaming and self.scoring_type == SCORING_AFTER_PAGE:
			frappe.throw(
				_(
					"Roaming cannot be combined with \"Scoring With Answers After Page\": "
					"respondents would be able to go back and fix an answer they have "
					"already been shown."
				)
			)

		if self.pagination == PAGINATION_ONE_PAGE:
			self.allow_roaming = 0

	def validate_certification(self):
		if not self.is_certification:
			self.give_badge = 0

		if self.is_certification and self.scoring_type == SCORING_NONE:
			frappe.throw(_("A certification needs a scoring mode."))

		if self.give_badge and not self.login_required:
			# A badge belongs to a user account; an anonymous respondent has
			# nowhere to put it.
			self.give_badge = 0

		if not self.give_badge:
			self.badge = None
		elif not self.badge:
			frappe.throw(_("Pick a badge to award, or turn off Give a Badge."))

		self.sync_badge_ownership()

	def sync_badge_ownership(self):
		"""Point the chosen badge back at this survey, one-to-one, and release
		whichever badge this survey no longer uses.

		`Survey Badge.survey` is set here rather than on the badge's own form —
		the same direction `Survey Question.survey` is set from the question
		side, never edited by hand. A badge already claimed by a different
		survey is refused outright rather than silently reassigned: two
		certifications quietly sharing one badge is exactly the kind of thing
		Odoo's unique constraint on `certification_badge_id` exists to catch.
		"""
		previous = self.get_doc_before_save()
		old_badge = previous.badge if previous else None

		if old_badge and old_badge != self.badge:
			frappe.db.set_value("Survey Badge", old_badge, "survey", None, update_modified=False)

		if not self.badge:
			return

		owner = frappe.db.get_value("Survey Badge", self.badge, "survey")
		if owner and owner != self.name:
			frappe.throw(_("Badge {0} already belongs to survey {1}.").format(self.badge, owner))

		if owner != self.name:
			frappe.db.set_value("Survey Badge", self.badge, "survey", self.name, update_modified=False)

	def validate_restriction(self):
		"""The responsible must keep access to a survey they are responsible for."""
		if not self.restricted_to or not self.responsible:
			return

		listed = {row.user for row in self.restricted_to}
		if self.responsible in listed:
			return

		if ROLE_MANAGER in frappe.get_roles(self.responsible):
			# Managers see everything anyway.
			return

		frappe.throw(
			_(
				"{0} is responsible for this survey but is not in the restricted list, "
				"and would lose access to it."
			).format(frappe.bold(self.responsible)),
			title=_("Responsible Would Lose Access"),
		)

	def validate_ready_to_open(self):
		"""Gate the Draft -> Open transition on the survey actually working.

		Odoo runs these checks only when you try to send an invitation, which
		means a broken survey can sit Open and silently fail for respondents.
		Checking on the transition catches it earlier.
		"""
		before = self.get_doc_before_save()
		opening = self.status == STATUS_OPEN and (self.is_new() or (before and before.status != STATUS_OPEN))

		if not opening or self.flags.ignore_open_checks:
			return

		for message in self.get_readiness_problems():
			frappe.throw(message, title=_("Survey Is Not Ready"))

	def get_readiness_problems(self) -> list[str]:
		"""Everything that would make this survey unusable for a respondent."""
		problems = []
		questions = self.get_questions()
		real_questions = [q for q in questions if not q.is_section]

		if not real_questions:
			problems.append(_("This survey has no questions yet."))

		if self.scoring_type != SCORING_NONE and flt(self.max_obtainable_score) <= 0:
			problems.append(
				_(
					"A scored survey needs at least one question that awards points. "
					"Check the answers and their scores."
				)
			)

		if self.pagination == PAGINATION_PER_SECTION:
			sections = [q for q in questions if q.is_section]
			if not sections:
				problems.append(_("\"One Page Per Section\" needs at least one section."))
			elif not any(q.section for q in real_questions):
				problems.append(_("Every section is empty. Move the questions under a section."))

		misplaced = [q.title for q in real_questions if q.is_misplaced_trigger]
		if misplaced:
			problems.append(
				_("These questions come before the answer that reveals them, so they would never show: {0}").format(
					", ".join(misplaced)
				)
			)

		return problems

	def validate_no_responses(self):
		if frappe.db.exists("Survey Response", {"survey": self.name}):
			frappe.throw(
				_("This survey has responses. Close it instead of deleting it."),
				title=_("Cannot Delete"),
			)

	def delete_questions(self):
		"""Cascade to the questions and their options.

		Frappe does not cascade `Link` fields, so without this a deleted
		survey would leave its questions behind as unreachable rows that still
		show up in reports.
		"""
		names = frappe.get_all("Survey Question", filters={"survey": self.name}, pluck="name")
		if not names:
			return

		# Triggers first: deleting a question that another one depends on is
		# blocked by design, and that guard is pointless while the whole
		# survey is going away.
		frappe.db.delete("Survey Question Trigger", {"parent": ["in", names]})

		for name in names:
			doc = frappe.get_doc("Survey Question", name)
			doc.flags.ignore_response_guard = True
			doc.delete(ignore_permissions=True)

	# ------------------------------------------------------------------
	# Derived fields
	# ------------------------------------------------------------------

	def set_derived_fields(self):
		"""Recompute the fields that depend on the survey's questions.

		Frappe has no dependency graph, so these are refreshed here (on the
		survey's own save) and pushed from `Survey Question` /
		`Survey Question Option` when those change.
		"""
		if self.is_new():
			self.question_count = 0
			self.max_obtainable_score = 0
			self.has_conditional_questions = 0
			return

		values = compute_derived_values(self.name, scoring_type=self.scoring_type)
		self.question_count = values["question_count"]
		self.max_obtainable_score = values["max_obtainable_score"]
		self.has_conditional_questions = values["has_conditional_questions"]

	# ------------------------------------------------------------------
	# Reads
	# ------------------------------------------------------------------

	def get_questions(self, include_sections: bool = True) -> list[dict]:
		"""Every row of the builder list, in display order."""
		filters = {"survey": self.name}
		if not include_sections:
			filters["is_section"] = 0

		rows = frappe.get_all(
			"Survey Question",
			filters=filters,
			fields=[
				"name",
				"title",
				"sequence",
				"is_section",
				"section",
				"question_type",
				"mandatory",
				"is_scored",
				"score",
				"is_misplaced_trigger",
				"random_questions_count",
			],
		)
		return sorted(rows, key=sequence_key)

	def get_sections(self) -> list[dict]:
		return [row for row in self.get_questions() if row.is_section]

	@property
	def is_open(self) -> bool:
		return self.status == STATUS_OPEN

	@property
	def reveals_answers(self) -> bool:
		return self.scoring_type in (SCORING_AFTER_PAGE, SCORING_WITH_ANSWERS)

	def get_start_url(self) -> str:
		"""The public link handed to respondents."""
		return f"/s/{self.access_token}"

	# ------------------------------------------------------------------
	# Actions
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def regenerate_access_token(self) -> str:
		"""Invalidate every link already shared for this survey."""
		self.check_permission("write")
		self.access_token = generate_token()
		self.save()
		frappe.msgprint(
			_("A new link has been generated. Links shared earlier no longer work."),
			alert=True,
		)
		return self.access_token

	@frappe.whitelist()
	def recompute_scores(self) -> dict:
		"""Re-score every response against the survey's current answer key.

		Scores are frozen on the answer rows when they are saved, so editing a
		correct answer afterwards does not change historical results. That is
		deliberate — but when the answer key was genuinely wrong, this makes
		fixing it an explicit, auditable act rather than a silent one.
		"""
		self.check_permission("write")

		responses = frappe.get_all(
			"Survey Response", filters={"survey": self.name, "docstatus": ["!=", 2]}, pluck="name"
		)
		for name in responses:
			response = frappe.get_doc("Survey Response", name)
			response.flags.ignore_validate_update_after_submit = True
			response.rescore()

		# Deliberately no `db.commit()` here. Frappe commits a successful
		# request on the way out, so an explicit commit buys nothing — and it
		# costs two things: the rescore stops being atomic with whatever the
		# caller was doing, and under test it flushes the transaction the
		# runner relies on for rollback, leaving every fixture created so far
		# permanently on the site.
		return {"rescored": len(responses)}


# ----------------------------------------------------------------------
# Module-level helpers
#
# These are deliberately *not* methods: they are called from the question
# and option controllers, which must be able to refresh the survey's derived
# fields without loading, validating and re-saving the whole Survey document
# (that would re-run every check above and could fail on an unrelated field).
# ----------------------------------------------------------------------


def compute_derived_values(survey: str, scoring_type: str | None = None) -> dict:
	"""Aggregate the question-dependent values for one survey."""
	if scoring_type is None:
		scoring_type = frappe.db.get_value("Survey", survey, "scoring_type")

	questions = frappe.get_all(
		"Survey Question",
		filters={"survey": survey, "is_section": 0},
		fields=["name", "question_type", "is_scored", "score"],
	)

	question_count = len(questions)
	max_score = 0.0

	if scoring_type != SCORING_NONE and questions:
		max_score = _sum_max_obtainable(questions)

	has_conditional = bool(
		frappe.db.sql(
			"""
			select 1
			from `tabSurvey Question Trigger` t
			inner join `tabSurvey Question` q on q.name = t.parent
			where q.survey = %s
			limit 1
			""",
			survey,
		)
	)

	return {
		"question_count": question_count,
		"max_obtainable_score": max_score,
		"has_conditional_questions": 1 if has_conditional else 0,
	}


def _sum_max_obtainable(questions: list[dict]) -> float:
	"""Highest total a respondent could earn across these questions.

	Single choice contributes its best-scoring option, multiple choice the sum
	of every positive option, and the direct types their own score. Negative
	option scores are ignored here: they can only ever reduce what somebody
	actually earns, never the ceiling.
	"""
	scored = [q for q in questions if q.is_scored]
	if not scored:
		return 0.0

	choice_questions = [q for q in scored if q.question_type in ("Single Choice", "Multiple Choice")]
	total = sum(
		flt(q.score) for q in scored if q.question_type in ("Numeric", "Date", "Datetime")
	)

	if choice_questions:
		option_rows = frappe.get_all(
			"Survey Question Option",
			filters={
				"question": ["in", [q.name for q in choice_questions]],
				"is_matrix_row": 0,
				"score": [">", 0],
			},
			fields=["question", "score"],
		)
		by_question: dict[str, list[float]] = {}
		for row in option_rows:
			by_question.setdefault(row.question, []).append(flt(row.score))

		for question in choice_questions:
			scores = by_question.get(question.name, [])
			if not scores:
				continue
			total += max(scores) if question.question_type == "Single Choice" else sum(scores)

	return flt(total, 2)


def recompute_derived_fields(survey: str) -> None:
	"""Write the derived values straight to the database.

	Uses `db.set_value` rather than a document save on purpose: this runs from
	inside another document's save, and re-entering `Survey.validate` there
	would be both wasteful and a recursion hazard.
	"""
	if frappe.flags.in_survey_recompute:
		return

	frappe.flags.in_survey_recompute = True
	try:
		values = compute_derived_values(survey)
		# Attempt limiting depends on has_conditional_questions, so it has to
		# be re-evaluated whenever the questions change, not only on save.
		if values["has_conditional_questions"]:
			values["limit_attempts"] = 0

		frappe.db.set_value("Survey", survey, values, update_modified=False)
		frappe.clear_document_cache("Survey", survey)
	finally:
		frappe.flags.in_survey_recompute = False


@frappe.whitelist()
def reorder(survey: str, ordered_names: list[str] | str) -> dict:
	"""Persist a new question order from the builder."""
	frappe.has_permission("Survey", "write", doc=survey, throw=True)

	if isinstance(ordered_names, str):
		ordered_names = frappe.parse_json(ordered_names)

	from survey.utils.sequencing import reorder_questions

	reorder_questions(survey, ordered_names)
	recompute_derived_fields(survey)

	return {"ok": True}


@frappe.whitelist()
def get_readiness(survey: str) -> dict:
	"""What still stands between this survey and being opened."""
	frappe.has_permission("Survey", "read", doc=survey, throw=True)
	doc = frappe.get_doc("Survey", survey)
	problems = doc.get_readiness_problems()
	return {"ready": not problems, "problems": problems}
