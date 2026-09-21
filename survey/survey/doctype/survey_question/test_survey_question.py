# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from survey.constants import SCORING_WITH_ANSWERS
from survey.tests.factories import make_option, make_question, make_section, make_survey


class TestSurveyQuestion(IntegrationTestCase):

	# -- sections ------------------------------------------------------

	def test_a_section_has_no_question_type(self):
		survey = make_survey()
		section = make_section(survey, title="Part One")

		self.assertFalse(section.question_type)
		self.assertFalse(section.mandatory)

	def test_questions_belong_to_the_section_above_them(self):
		survey = make_survey()
		first = make_section(survey, title="A")
		q1 = make_question(survey, question_type="Single Line Text")
		second = make_section(survey, title="B")
		q2 = make_question(survey, question_type="Single Line Text")

		q1.reload()
		q2.reload()

		self.assertEqual(q1.section, first.name)
		self.assertEqual(q2.section, second.name)

	def test_a_question_before_any_section_has_none(self):
		survey = make_survey()
		orphan = make_question(survey, question_type="Single Line Text")
		make_section(survey, title="Later")

		orphan.reload()
		self.assertIsNone(orphan.section)

	def test_reordering_reparents_questions(self):
		from survey.utils.sequencing import reorder_questions

		survey = make_survey()
		section_a = make_section(survey, title="A")
		question = make_question(survey, question_type="Single Line Text")
		section_b = make_section(survey, title="B")

		reorder_questions(survey.name, [section_a.name, section_b.name, question.name])

		question.reload()
		self.assertEqual(question.section, section_b.name)

	# -- scale ---------------------------------------------------------

	def test_scale_bounds_must_grow(self):
		survey = make_survey()
		self.assertRaises(
			frappe.ValidationError,
			make_question,
			survey,
			question_type="Scale",
			scale_min=8,
			scale_max=3,
		)

	def test_scale_cannot_exceed_ten(self):
		survey = make_survey()
		self.assertRaises(
			frappe.ValidationError,
			make_question,
			survey,
			question_type="Scale",
			scale_min=0,
			scale_max=50,
		)

	# -- validation limits ---------------------------------------------

	def test_max_cannot_be_smaller_than_min(self):
		survey = make_survey()
		self.assertRaises(
			frappe.ValidationError,
			make_question,
			survey,
			question_type="Numeric",
			validate_entry=1,
			min_value=100,
			max_value=10,
		)

	def test_switching_type_clears_stale_settings(self):
		"""A numeric limit must not survive a change to a choice question."""
		survey = make_survey()
		question = make_question(
			survey, question_type="Numeric", validate_entry=1, min_value=1, max_value=10
		)

		question.question_type = "Single Choice"
		question.save()

		self.assertFalse(question.validate_entry)
		self.assertFalse(question.min_value)
		self.assertFalse(question.max_value)

	def test_save_as_email_needs_email_validation(self):
		survey = make_survey()
		question = make_question(
			survey, question_type="Single Line Text", save_as_email=1, validate_email=0
		)

		self.assertFalse(question.save_as_email)

	# -- scoring -------------------------------------------------------

	def test_choice_question_is_scored_when_an_option_is_correct(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")

		make_option(question, "Wrong")
		question.reload()
		question.save()
		self.assertFalse(question.is_scored)

		make_option(question, "Right", is_correct=1, score=3)
		question.reload()
		question.save()
		self.assertTrue(question.is_scored)

	def test_date_question_is_scored_when_it_has_a_correct_answer(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Date", correct_date="2026-01-01", score=2)

		self.assertTrue(question.is_scored)

	def test_text_questions_are_never_scored(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Multiple Line Text", score=5)

		self.assertFalse(question.is_scored)
		self.assertFalse(question.score)

	def test_marking_an_option_correct_makes_its_question_scored(self):
		"""`is_scored` is derived from the options, which arrive afterwards.

		Frappe has no dependency graph, so nothing recomputes this unless the
		option pushes it. Without that push every scored survey silently
		totals zero, because scoring skips questions that are not scored.
		"""
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")

		self.assertFalse(question.is_scored)

		make_option(question, "Right", is_correct=1, score=5)
		make_option(question, "Wrong", score=0)
		question.reload()

		self.assertTrue(question.is_scored)
		self.assertEqual(frappe.db.get_value("Survey", survey.name, "max_obtainable_score"), 5)

	def test_unmarking_the_last_correct_option_makes_the_question_unscored(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=5)
		question.reload()
		self.assertTrue(question.is_scored)

		right.is_correct = 0
		right.save()
		question.reload()

		self.assertFalse(question.is_scored)

	def test_a_negative_question_score_is_rejected_without_entry_validation(self):
		"""The rule used to sit inside `validate_limits`, which returns early
		unless `validate_entry` is on — so it only fired for questions that
		happened to have entry validation enabled."""
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)

		self.assertRaises(
			frappe.ValidationError,
			make_question,
			survey,
			question_type="Numeric",
			correct_number=1,
			score=-5,
			validate_entry=0,
		)

	def test_question_score_cannot_be_negative(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		self.assertRaises(
			frappe.ValidationError,
			make_question,
			survey,
			question_type="Numeric",
			correct_number=1,
			score=-5,
		)

	# -- skip logic ----------------------------------------------------

	def test_only_choice_questions_can_trigger(self):
		survey = make_survey()
		text = make_question(survey, question_type="Single Line Text")
		# An option cannot even be created on a text question.
		self.assertRaises(frappe.ValidationError, make_option, text, "Nope")

	def test_a_trigger_from_another_survey_is_rejected(self):
		other = make_survey()
		trigger = make_question(other, question_type="Single Choice")
		option = make_option(trigger, "Yes")

		survey = make_survey()
		dependent = make_question(survey, question_type="Single Line Text")
		dependent.append("triggering_options", {"option": option.name})

		self.assertRaises(frappe.ValidationError, dependent.save)

	def test_a_question_placed_before_its_trigger_is_flagged(self):
		survey = make_survey()
		early = make_question(survey, question_type="Single Line Text", sequence=10)
		trigger = make_question(survey, question_type="Single Choice", sequence=20)
		option = make_option(trigger, "Yes")

		early.append("triggering_options", {"option": option.name})
		early.save()

		self.assertTrue(early.is_misplaced_trigger)

	def test_a_correctly_ordered_trigger_is_not_flagged(self):
		survey = make_survey()
		trigger = make_question(survey, question_type="Single Choice", sequence=10)
		option = make_option(trigger, "Yes")
		later = make_question(survey, question_type="Single Line Text", sequence=20)

		later.append("triggering_options", {"option": option.name})
		later.save()

		self.assertFalse(later.is_misplaced_trigger)

	def test_deleting_an_option_removes_the_trigger_that_used_it(self):
		survey = make_survey()
		trigger = make_question(survey, question_type="Single Choice", sequence=10)
		option = make_option(trigger, "Yes")
		dependent = make_question(survey, question_type="Single Line Text", sequence=20)
		dependent.append("triggering_options", {"option": option.name})
		dependent.save()

		frappe.delete_doc("Survey Question Option", option.name)

		dependent.reload()
		self.assertFalse(dependent.triggering_options)

	def test_cannot_delete_a_question_others_depend_on(self):
		survey = make_survey()
		trigger = make_question(survey, question_type="Single Choice", sequence=10)
		option = make_option(trigger, "Yes")
		dependent = make_question(survey, question_type="Single Line Text", sequence=20)
		dependent.append("triggering_options", {"option": option.name})
		dependent.save()

		self.assertRaises(
			frappe.ValidationError, frappe.delete_doc, "Survey Question", trigger.name
		)

	# -- locking -------------------------------------------------------

	def test_structural_edits_are_blocked_once_responses_exist(self):
		from survey.tests.factories import make_response

		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")
		make_response(survey)

		question.mandatory = 1
		self.assertRaises(frappe.ValidationError, question.save)

	def test_cosmetic_edits_stay_allowed_once_responses_exist(self):
		from survey.tests.factories import make_response

		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")
		make_response(survey)

		question.title = "Fixed a typo"
		question.save()

		self.assertEqual(question.title, "Fixed a typo")
