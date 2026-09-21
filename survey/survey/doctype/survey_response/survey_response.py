# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

import random

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, time_diff_in_seconds

from survey.constants import (
	ACCESS_PUBLIC,
	CHOICE_TYPES,
	DIRECTLY_SCORABLE_TYPES,
	RESPONSE_COMPLETED,
	RESPONSE_IN_PROGRESS,
	RESPONSE_NEW,
	SCORING_NONE,
	SELECTION_RANDOM,
)
from survey.utils.sequencing import sequence_key
from survey.utils.tokens import generate_token


class SurveyResponse(Document):
	# ------------------------------------------------------------------
	# Hooks
	# ------------------------------------------------------------------

	def before_insert(self):
		if not self.access_token:
			self.access_token = generate_token()
		if not self.predefined_questions:
			self.snapshot_question_set()
		self.set_identity_defaults()

	def validate(self):
		self.validate_answer_rows()
		self.validate_answers_belong_to_survey()
		self.score_answers()
		self.compute_result()
		self.sync_status()
		self.compute_duration()

	def before_submit(self):
		"""Submitting is what "Completed" means; everything else is in progress."""
		self.prune_unreachable_questions()
		self.score_answers()
		self.compute_result()

		if not self.completed_on:
			self.completed_on = now_datetime()
		self.status = RESPONSE_COMPLETED
		self.compute_duration()
		self.set_attempt_counters()

	def on_submit(self):
		# Certification (badge award + certificate email) is wired through
		# `doc_events` in hooks.py -> `survey.certification.on_response_submit`,
		# not here: it is a distinct concern with its own module, and keeping
		# it off this controller means the certification module can be read
		# (or deleted) without touching the response lifecycle.
		frappe.publish_realtime(
			"survey_response_submitted",
			{"response": self.name, "survey": self.survey, "passed": bool(self.passed)},
			doctype="Survey",
			docname=self.survey,
			after_commit=True,
		)

	def on_cancel(self):
		self.status = RESPONSE_IN_PROGRESS

	def before_print(self, print_settings=None):
		"""Feed the certificate everything it needs.

		Both the direct download (`certification.download_certificate`) and
		the emailed copy (`frappe.attach_print`, from `on_response_submit`)
		render through `frappe.get_print`, which calls this before handing the
		document to the template — so the computation lives in exactly one
		place rather than being duplicated between the two callers.
		"""
		from survey.certification import build_certificate_context

		for key, value in build_certificate_context(self).items():
			setattr(self, key, value)

	# ------------------------------------------------------------------
	# Question set
	# ------------------------------------------------------------------

	def snapshot_question_set(self):
		"""Freeze which questions this respondent has to answer.

		Done once, at creation, so that a randomised survey deals the same
		hand every time the respondent resumes, and so that editing the survey
		mid-flight cannot change what somebody is being asked. Every scoring
		denominator is computed against this set.
		"""
		survey = frappe.get_cached_doc("Survey", self.survey)
		self.set("predefined_questions", [])

		for question in select_questions_for_respondent(survey):
			self.append("predefined_questions", {"question": question})

	def prune_unreachable_questions(self):
		"""Drop conditional questions this respondent never unlocked.

		Without this, somebody who answered honestly and was never shown the
		follow-up question would be marked down for "missing" it, because the
		question would still be in their scoring denominator.
		"""
		inactive = self.get_inactive_questions()
		if not inactive:
			return

		self.set(
			"predefined_questions",
			[row for row in self.predefined_questions if row.question not in inactive],
		)

	def get_question_names(self) -> list[str]:
		return [row.question for row in self.predefined_questions]

	def get_selected_options(self) -> set[str]:
		"""Every option this respondent has picked, across all questions."""
		return {
			row.selected_option
			for row in self.answers
			if row.selected_option and not row.skipped
		}

	def get_inactive_questions(self) -> set[str]:
		"""Questions whose display condition is not currently satisfied.

		A question with triggers is visible when *at least one* of them is
		selected (OR semantics). Chained conditions need no recursion: a
		question that is itself hidden can have no selected answers, so
		anything depending on it is hidden too, and falls out of this same
		pass.
		"""
		triggers = get_triggering_options_map(self.survey)
		if not triggers:
			return set()

		selected = self.get_selected_options()
		return {
			question
			for question, required in triggers.items()
			if required and not (required & selected)
		}

	# ------------------------------------------------------------------
	# Identity
	# ------------------------------------------------------------------

	def set_identity_defaults(self):
		if self.user and not self.email:
			self.email = frappe.db.get_value("User", self.user, "email")

		if self.user and not self.nickname:
			self.nickname = frappe.db.get_value("User", self.user, "full_name")

		if not self.nickname and self.email:
			self.nickname = self.email

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_answer_rows(self):
		"""Run each answer row's own integrity rule.

		Frappe only applies field-level validation to child rows — a child
		DocType's `validate()` is never called by the framework — so without
		this the "skipped xor answered" rule would silently never run.
		"""
		for row in self.answers:
			row.validate_skipped_xor_answered()

	def validate_answers_belong_to_survey(self):
		"""Refuse answers to questions this respondent was never dealt.

		The public endpoints take a question id from the client, so this is a
		real boundary, not a sanity check: without it a respondent could post
		answers to another survey's questions, or to the questions a
		randomised draw withheld from them.
		"""
		if not self.answers:
			return

		allowed = set(self.get_question_names())
		stray = {row.question for row in self.answers if row.question not in allowed}

		if stray:
			titles = frappe.get_all(
				"Survey Question", filters={"name": ["in", list(stray)]}, pluck="title"
			) or list(stray)
			frappe.throw(
				_("These questions are not part of this response: {0}").format(", ".join(titles)),
				title=_("Unexpected Answer"),
			)

	# ------------------------------------------------------------------
	# Scoring
	# ------------------------------------------------------------------

	def score_answers(self):
		"""Freeze a score and a correctness flag onto every answer row.

		Scores are computed here rather than read live from the answer key so
		that editing the key afterwards does not silently restate historical
		results. `Survey.recompute_scores()` re-runs this deliberately.
		"""
		scoring_type = frappe.db.get_value("Survey", self.survey, "scoring_type")
		if scoring_type == SCORING_NONE:
			for row in self.answers:
				row.score = 0
				row.is_correct = 0
			return

		questions = self.get_question_meta()
		option_scores = self.get_option_score_map()

		for row in self.answers:
			score, correct = score_answer_row(row, questions.get(row.question), option_scores)
			row.score = score
			row.is_correct = 1 if correct else 0

	def get_question_meta(self) -> dict[str, dict]:
		names = {row.question for row in self.answers} | set(self.get_question_names())
		if not names:
			return {}

		rows = frappe.get_all(
			"Survey Question",
			filters={"name": ["in", list(names)]},
			fields=[
				"name",
				"question_type",
				"is_scored",
				"score",
				"correct_number",
				"correct_date",
				"correct_datetime",
				"mandatory",
				"section",
				"sequence",
				"title",
			],
		)
		return {row.name: row for row in rows}

	def get_option_score_map(self) -> dict[str, dict]:
		option_names = {row.selected_option for row in self.answers if row.selected_option}
		if not option_names:
			return {}

		rows = frappe.get_all(
			"Survey Question Option",
			filters={"name": ["in", list(option_names)]},
			fields=["name", "score", "is_correct"],
		)
		return {row.name: row for row in rows}

	def compute_result(self):
		"""Total the frozen answer scores against what was obtainable.

		The denominator comes from `predefined_questions`, not from the whole
		survey, so a randomised draw or an untriggered conditional question
		never counts against the respondent.
		"""
		survey = frappe.get_cached_doc("Survey", self.survey)

		if survey.scoring_type == SCORING_NONE:
			self.total_score = 0
			self.score_percentage = 0
			self.passed = 0
			return

		obtainable = self.get_obtainable_score()
		earned = sum(flt(row.score) for row in self.answers)

		self.total_score = flt(earned, 2)

		if obtainable <= 0:
			self.score_percentage = 0
		else:
			percentage = (earned / obtainable) * 100
			# Negative option scores can push a respondent below zero; report
			# that as 0 rather than as a negative percentage.
			self.score_percentage = flt(max(percentage, 0), 2)

		self.passed = 1 if flt(self.score_percentage) >= flt(survey.passing_score) else 0

	def get_obtainable_score(self) -> float:
		"""The most this respondent could have scored on their question set."""
		names = self.get_question_names()
		if not names:
			return 0.0

		from survey.survey.doctype.survey.survey import _sum_max_obtainable

		questions = frappe.get_all(
			"Survey Question",
			filters={"name": ["in", names]},
			fields=["name", "question_type", "is_scored", "score"],
		)
		return _sum_max_obtainable(questions)

	def get_section_breakdown(self) -> list[dict]:
		"""Correct / partial / incorrect / skipped, grouped by section.

		Only *scored* questions are classified — an unscored question (plain
		text, a rating scale) has no notion of "correct", and is left out
		rather than forced into a bucket that would misrepresent it.

		"Partial" only ever applies to Multiple Choice: the respondent picked
		some but not all of the correct options, or mixed a correct pick with
		a wrong one. Single Choice and the directly-scorable types
		(Numeric/Date/Datetime) are binary — there is nothing to be partially
		right about when only one answer is possible.
		"""
		questions = self.get_question_meta()
		scored = {name: q for name, q in questions.items() if q.is_scored}
		if not scored:
			return []

		rows_by_question: dict[str, list] = {}
		for row in self.answers:
			rows_by_question.setdefault(row.question, []).append(row)

		correct_option_counts = _correct_option_counts(
			[name for name, q in scored.items() if q.question_type in CHOICE_TYPES]
		)

		sections: dict[str | None, dict] = {}
		order: list[str | None] = []

		for name, question in scored.items():
			key = question.section
			if key not in sections:
				sections[key] = {
					"section": key,
					"title": _section_title(key),
					"correct": 0,
					"partial": 0,
					"incorrect": 0,
					"skipped": 0,
					"total": 0,
				}
				order.append(key)

			bucket = sections[key]
			bucket["total"] += 1
			bucket[
				_classify_question(question, rows_by_question.get(name, []), correct_option_counts)
			] += 1

		return [sections[key] for key in order]

	def rescore(self):
		"""Re-apply the survey's current answer key to this response."""
		self.score_answers()
		self.compute_result()

		self.db_set(
			{
				"total_score": self.total_score,
				"score_percentage": self.score_percentage,
				"passed": self.passed,
			},
			update_modified=False,
		)
		for row in self.answers:
			frappe.db.set_value(
				"Survey Response Answer",
				row.name,
				{"score": row.score, "is_correct": row.is_correct},
				update_modified=False,
			)

	# ------------------------------------------------------------------
	# Status and counters
	# ------------------------------------------------------------------

	def sync_status(self):
		if self.docstatus == 1:
			self.status = RESPONSE_COMPLETED
		elif self.started_on or self.answers:
			if self.status != RESPONSE_COMPLETED:
				self.status = RESPONSE_IN_PROGRESS
		else:
			self.status = RESPONSE_NEW

	def compute_duration(self):
		if self.started_on and self.completed_on:
			self.duration = flt(time_diff_in_seconds(self.completed_on, self.started_on) / 60, 2)
		else:
			self.duration = 0

	def set_attempt_counters(self):
		"""Rank this attempt within its pool.

		The pool is "the same person on the same survey": matched by invite
		token when there is one, otherwise by user, contact or email. Test
		entries never count.
		"""
		if self.is_test:
			self.attempt_number = 1
			self.attempt_count = 1
			return

		siblings = frappe.get_all(
			"Survey Response",
			filters=self.get_attempt_pool_filters(),
			fields=["name", "creation"],
			order_by="creation asc",
		)
		names = [row.name for row in siblings]

		if self.name in names:
			# Re-counting an already submitted attempt (a rescore, say).
			self.attempt_count = len(names)
			self.attempt_number = names.index(self.name) + 1
		else:
			# Called from before_submit: this attempt is not in the pool yet,
			# because the pool only counts submitted responses.
			self.attempt_count = len(names) + 1
			self.attempt_number = self.attempt_count

	def get_attempt_pool_filters(self) -> dict:
		filters = {
			"survey": self.survey,
			"is_test": 0,
			"docstatus": 1,
		}
		if self.invite_token:
			filters["invite_token"] = self.invite_token
		elif self.user:
			filters["user"] = self.user
		elif self.contact:
			filters["contact"] = self.contact
		elif self.email:
			filters["email"] = self.email
		else:
			# Anonymous and un-invited: there is no pool to speak of.
			filters["name"] = self.name

		return filters

	# ------------------------------------------------------------------
	# Progress helpers used by the player (phase 2)
	# ------------------------------------------------------------------

	def mark_in_progress(self):
		if self.status != RESPONSE_NEW:
			return
		self.db_set({"status": RESPONSE_IN_PROGRESS, "started_on": now_datetime()})

	def is_expired(self) -> bool:
		return bool(self.deadline and now_datetime() > self.deadline)

	def time_remaining(self) -> float | None:
		"""Seconds left on the survey's overall time limit.

		`None` means the survey is not timed, which is a different answer from
		`0` and callers must not conflate the two. The clock starts at
		`started_on` — the moment the respondent left the intro screen — and
		keeps running whether or not the tab is open, which is the whole point
		of a time limit.

		The value can go negative; that is what tells the caller by how much
		the deadline was missed.
		"""
		survey = frappe.get_cached_doc("Survey", self.survey)
		if not survey.is_time_limited or not flt(survey.time_limit):
			return None

		if not self.started_on:
			# Not begun yet, so nothing has been spent.
			return flt(survey.time_limit) * 60

		elapsed = time_diff_in_seconds(now_datetime(), self.started_on)
		return flt(survey.time_limit) * 60 - elapsed

	def has_time_left(self, grace: float = 0) -> bool:
		"""Whether the survey's overall time limit still allows answering.

		`grace` buys the respondent a few seconds past the deadline so that a
		page submitted right on the buzzer is not thrown away over network
		latency. It exists to be generous to a slow connection, not to let a
		stopped client clock buy extra time — the server is the only clock
		that counts here.
		"""
		remaining = self.time_remaining()
		if remaining is None:
			return True

		return remaining + grace > 0


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def select_questions_for_respondent(survey) -> list[str]:
	"""Pick the questions one respondent will be asked, in order.

	With "All Questions" this is simply every question. With "Randomized Per
	Section" each section contributes `random_questions_count` of its
	questions, drawn once, here; questions that sit outside any section are
	always included.
	"""
	rows = sorted(
		frappe.get_all(
			"Survey Question",
			filters={"survey": survey.name},
			fields=["name", "sequence", "is_section", "section", "random_questions_count"],
		),
		key=sequence_key,
	)

	questions = [row for row in rows if not row.is_section]

	if survey.question_selection != SELECTION_RANDOM:
		return [row.name for row in questions]

	sections = {row.name: row for row in rows if row.is_section}
	chosen: list[str] = []
	by_section: dict[str | None, list] = {}

	for question in questions:
		by_section.setdefault(question.section, []).append(question)

	for section_name, members in by_section.items():
		if not section_name:
			# Questions outside a section are never randomised away.
			chosen.extend(row.name for row in members)
			continue

		wanted = cint(sections[section_name].random_questions_count)
		if 0 < wanted < len(members):
			chosen.extend(row.name for row in random.sample(members, wanted))
		else:
			chosen.extend(row.name for row in members)

	# Restore survey order: the random draw must not reorder the survey.
	order = {row.name: index for index, row in enumerate(questions)}
	return sorted(chosen, key=lambda name: order[name])


def get_triggering_options_map(survey: str) -> dict[str, set[str]]:
	"""`{question: {options that reveal it}}` for one survey.

	Deliberately uncached. A request cache here would go stale the moment a
	trigger is added or an option is deleted mid-request, and a wrong answer
	to "is this question visible?" silently corrupts a respondent's score.
	It is two indexed joins; buy the correctness.

	TODO(phase-3): if the player's page turns show this in the profile, cache
	it against the survey's `modified` stamp rather than against its name.
	"""
	rows = frappe.db.sql(
		"""
		select q.name as question, t.option as option
		from `tabSurvey Question Trigger` t
		inner join `tabSurvey Question` q on q.name = t.parent
		where q.survey = %s
		""",
		survey,
		as_dict=True,
	)

	mapping: dict[str, set[str]] = {}
	for row in rows:
		mapping.setdefault(row.question, set()).add(row.option)

	return mapping


def score_answer_row(row, question, option_scores: dict[str, dict]) -> tuple[float, bool]:
	"""Score one answer row against its question.

	Choice questions score per selected option, which is what allows a wrong
	choice to carry a negative score. The direct types score all-or-nothing
	against the question's own correct answer. Text, long text, scale and
	matrix answers are never scored, matching Odoo.
	"""
	if not question or row.skipped or not question.is_scored:
		return 0.0, False

	if question.question_type in CHOICE_TYPES:
		if row.answer_type != "Option" or not row.selected_option:
			return 0.0, False
		option = option_scores.get(row.selected_option)
		if not option:
			return 0.0, False
		return flt(option.score), bool(option.is_correct)

	if question.question_type in DIRECTLY_SCORABLE_TYPES:
		expected = {
			"Numeric": question.correct_number,
			"Date": question.correct_date,
			"Datetime": question.correct_datetime,
		}[question.question_type]

		actual = {
			"Numeric": row.value_number,
			"Date": row.value_date,
			"Datetime": row.value_datetime,
		}[question.question_type]

		if expected is None or actual is None:
			return 0.0, False

		if question.question_type == "Numeric":
			matches = flt(actual) == flt(expected)
		else:
			matches = str(actual) == str(expected)

		return (flt(question.score), True) if matches else (0.0, False)

	return 0.0, False


def _correct_option_counts(choice_question_names: list[str]) -> dict[str, int]:
	"""How many options are marked correct on each of these choice questions.

	Enough on its own to tell "all correct options picked" (Correct) apart
	from "some correct options picked" (Partial) when combined with the
	per-row `is_correct` already frozen on the answer — there is no need to
	fetch the full option list and re-derive what is already scored.
	"""
	if not choice_question_names:
		return {}

	from collections import Counter

	rows = frappe.get_all(
		"Survey Question Option",
		filters={"question": ["in", choice_question_names], "is_correct": 1, "is_matrix_row": 0},
		fields=["question"],
	)
	return dict(Counter(row.question for row in rows))


def _classify_question(question, rows: list, correct_option_counts: dict[str, int]) -> str:
	"""One of "correct" / "partial" / "incorrect" / "skipped" for one question.

	Reads only the answer rows' frozen `score` / `is_correct` — the same
	values `score_answers()` already computed — so this can never disagree
	with the score a respondent was actually given.
	"""
	answered = [row for row in rows if not row.skipped and row.answer_type]
	if not answered:
		return "skipped"

	if question.question_type in CHOICE_TYPES:
		correct_picked = sum(1 for row in answered if row.answer_type == "Option" and row.is_correct)
		wrong_picked = sum(1 for row in answered if row.answer_type == "Option" and not row.is_correct)
		total_correct = correct_option_counts.get(question.name, 0)

		if correct_picked and correct_picked == total_correct and not wrong_picked:
			return "correct"
		if correct_picked:
			return "partial"
		return "incorrect"

	# The directly-scorable types (Numeric/Date/Datetime) are one row, binary.
	return "correct" if answered[0].is_correct else "incorrect"


def _section_title(section: str | None) -> str:
	if not section:
		return _("General")

	return frappe.db.get_value("Survey Question", section, "title") or _("General")
