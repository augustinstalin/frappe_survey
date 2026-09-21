# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from survey.constants import (
	RESPONSE_COMPLETED,
	RESPONSE_NEW,
	SCORING_WITH_ANSWERS,
	SELECTION_RANDOM,
)
from survey.tests.factories import make_option, make_question, make_response, make_section, make_survey


class TestSurveyResponse(IntegrationTestCase):

	# -- creation ------------------------------------------------------

	def test_access_token_is_generated(self):
		survey = make_survey()
		make_question(survey, question_type="Single Line Text")
		response = make_response(survey)

		self.assertTrue(response.access_token)
		self.assertEqual(response.status, RESPONSE_NEW)

	def test_question_set_is_snapshotted_at_creation(self):
		survey = make_survey()
		first = make_question(survey, question_type="Single Line Text")
		second = make_question(survey, question_type="Single Line Text")

		response = make_response(survey)

		self.assertEqual(
			[row.question for row in response.predefined_questions], [first.name, second.name]
		)

	def test_questions_added_later_are_not_dealt_to_an_existing_response(self):
		"""The snapshot is what the respondent was dealt, not what exists now.

		Adding a question to a survey that already has responses is blocked by
		`validate_survey_is_editable`, so this goes through the same escape
		hatch an administrator would: the guard is about protecting answers
		that have already been given, and the snapshot is what protects them.
		"""
		survey = make_survey()
		first = make_question(survey, question_type="Single Line Text")
		response = make_response(survey)

		make_question(survey, question_type="Single Line Text", ignore_response_guard=True)
		response.reload()

		self.assertEqual([row.question for row in response.predefined_questions], [first.name])

	def test_randomised_selection_deals_the_configured_number_per_section(self):
		survey = make_survey(question_selection=SELECTION_RANDOM)
		make_section(survey, title="Pool", random_questions_count=2)
		for _ in range(5):
			make_question(survey, question_type="Single Line Text")

		response = make_response(survey)

		self.assertEqual(len(response.predefined_questions), 2)

	def test_questions_outside_a_section_are_never_randomised_away(self):
		survey = make_survey(question_selection=SELECTION_RANDOM)
		loose = make_question(survey, question_type="Single Line Text")
		make_section(survey, title="Pool", random_questions_count=1)
		for _ in range(3):
			make_question(survey, question_type="Single Line Text")

		response = make_response(survey)
		dealt = [row.question for row in response.predefined_questions]

		self.assertIn(loose.name, dealt)
		self.assertEqual(len(dealt), 2)

	# -- answer integrity ----------------------------------------------

	def test_an_answer_is_either_skipped_or_answered(self):
		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")
		response = make_response(survey)

		response.append(
			"answers", {"question": question.name, "skipped": 1, "answer_type": "Text", "value_text": "x"}
		)
		self.assertRaises(frappe.ValidationError, response.save)

	def test_a_row_that_is_both_skipped_and_answered_is_rejected(self):
		"""Frappe never calls a child DocType's own `validate()`, so this rule
		has to be driven from the parent. It went unenforced until it was."""
		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")
		response = make_response(survey)

		response.append(
			"answers",
			{"question": question.name, "skipped": 1, "answer_type": "Text", "value_text": "x"},
		)

		self.assertRaises(frappe.ValidationError, response.save)

	def test_zero_is_a_real_numeric_answer(self):
		survey = make_survey()
		question = make_question(survey, question_type="Numeric")
		response = make_response(survey)

		response.append(
			"answers", {"question": question.name, "answer_type": "Number", "value_number": 0}
		)
		response.save()

		self.assertFalse(response.answers[0].skipped)

	def test_answers_to_foreign_questions_are_rejected(self):
		survey = make_survey()
		make_question(survey, question_type="Single Line Text")
		response = make_response(survey)

		other = make_survey()
		stray = make_question(other, question_type="Single Line Text")

		response.append(
			"answers", {"question": stray.name, "answer_type": "Text", "value_text": "hello"}
		)
		self.assertRaises(frappe.ValidationError, response.save)

	# -- scoring -------------------------------------------------------

	def test_choice_scoring_totals_the_selected_options(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS, passing_score=50)
		question = make_question(survey, question_type="Multiple Choice")
		right = make_option(question, "Right", is_correct=1, score=4)
		also = make_option(question, "Also right", is_correct=1, score=4)
		make_option(question, "Wrong", score=-2)

		response = make_response(survey)
		for option in (right, also):
			response.append(
				"answers",
				{"question": question.name, "answer_type": "Option", "selected_option": option.name},
			)
		response.save()

		self.assertEqual(response.total_score, 8)
		self.assertEqual(response.score_percentage, 100)
		self.assertTrue(response.passed)

	def test_a_wrong_choice_can_subtract_points(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS, passing_score=50)
		question = make_question(survey, question_type="Multiple Choice")
		right = make_option(question, "Right", is_correct=1, score=4)
		wrong = make_option(question, "Wrong", score=-2)

		response = make_response(survey)
		for option in (right, wrong):
			response.append(
				"answers",
				{"question": question.name, "answer_type": "Option", "selected_option": option.name},
			)
		response.save()

		self.assertEqual(response.total_score, 2)
		self.assertEqual(response.score_percentage, 50)

	def test_a_negative_total_reports_as_zero_percent(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Multiple Choice")
		make_option(question, "Right", is_correct=1, score=4)
		wrong = make_option(question, "Very wrong", score=-10)

		response = make_response(survey)
		response.append(
			"answers", {"question": question.name, "answer_type": "Option", "selected_option": wrong.name}
		)
		response.save()

		self.assertEqual(response.score_percentage, 0)
		self.assertFalse(response.passed)

	def test_numeric_question_scores_all_or_nothing(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Numeric", correct_number=42, score=6)

		response = make_response(survey)
		response.append(
			"answers", {"question": question.name, "answer_type": "Number", "value_number": 42}
		)
		response.save()
		self.assertEqual(response.total_score, 6)

		response.answers[0].value_number = 41
		response.save()
		self.assertEqual(response.total_score, 0)

	def test_scores_are_frozen_against_a_later_answer_key_change(self):
		"""Editing the key must not silently restate a historical result."""
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")
		option = make_option(question, "Picked", is_correct=1, score=5)

		response = make_response(survey)
		response.append(
			"answers",
			{"question": question.name, "answer_type": "Option", "selected_option": option.name},
		)
		response.save()
		response.submit()

		option.reload()
		option.score = 50
		option.save()

		response.reload()
		self.assertEqual(response.total_score, 5)

	def test_recompute_scores_applies_the_new_key_deliberately(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")
		option = make_option(question, "Picked", is_correct=1, score=5)

		response = make_response(survey)
		response.append(
			"answers",
			{"question": question.name, "answer_type": "Option", "selected_option": option.name},
		)
		response.save()
		response.submit()

		option.reload()
		option.score = 10
		option.save()

		survey.reload()
		survey.recompute_scores()

		response.reload()
		self.assertEqual(response.total_score, 10)

	def test_unscored_survey_leaves_every_score_at_zero(self):
		survey = make_survey()
		question = make_question(survey, question_type="Single Choice")
		option = make_option(question, "Anything", is_correct=1, score=9)

		response = make_response(survey)
		response.append(
			"answers",
			{"question": question.name, "answer_type": "Option", "selected_option": option.name},
		)
		response.save()

		self.assertEqual(response.total_score, 0)
		self.assertEqual(response.score_percentage, 0)

	# -- conditional questions -----------------------------------------

	def test_untriggered_questions_leave_the_denominator_on_submit(self):
		"""A respondent is not marked down for a question they never unlocked."""
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS, passing_score=50)

		gate = make_question(survey, question_type="Single Choice", sequence=10)
		yes = make_option(gate, "Yes", is_correct=1, score=5)
		make_option(gate, "No", score=0)

		follow_up = make_question(survey, question_type="Numeric", sequence=20, correct_number=1, score=5)
		follow_up.append("triggering_options", {"option": yes.name})
		follow_up.save()

		response = make_response(survey)
		self.assertEqual(len(response.predefined_questions), 2)

		# Answering "No" never unlocks the follow-up.
		no_option = frappe.db.get_value(
			"Survey Question Option", {"question": gate.name, "label": "No"}, "name"
		)
		response.append(
			"answers",
			{"question": gate.name, "answer_type": "Option", "selected_option": no_option},
		)
		response.save()
		response.submit()

		self.assertEqual(len(response.predefined_questions), 1)
		# Denominator is now 5, not 10, so an unanswered follow-up costs nothing.
		self.assertEqual(response.score_percentage, 0)

	def test_a_triggered_question_stays_in_the_denominator(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)

		gate = make_question(survey, question_type="Single Choice", sequence=10)
		yes = make_option(gate, "Yes", is_correct=1, score=5)

		follow_up = make_question(survey, question_type="Numeric", sequence=20, correct_number=1, score=5)
		follow_up.append("triggering_options", {"option": yes.name})
		follow_up.save()

		response = make_response(survey)
		response.append(
			"answers", {"question": gate.name, "answer_type": "Option", "selected_option": yes.name}
		)
		response.save()
		response.submit()

		self.assertEqual(len(response.predefined_questions), 2)
		self.assertEqual(response.score_percentage, 50)

	# -- lifecycle -----------------------------------------------------

	def test_submitting_completes_the_response(self):
		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")

		response = make_response(survey)
		response.mark_in_progress()
		response.reload()
		response.append(
			"answers", {"question": question.name, "answer_type": "Text", "value_text": "hi"}
		)
		response.save()
		response.submit()

		self.assertEqual(response.status, RESPONSE_COMPLETED)
		self.assertTrue(response.completed_on)
		self.assertTrue(response.duration >= 0)

	def test_attempts_are_counted_within_an_invite_pool(self):
		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")

		token = "pool-token"
		attempts = []
		for _ in range(2):
			response = make_response(survey, invite_token=token, email="a@example.com")
			response.append(
				"answers", {"question": question.name, "answer_type": "Text", "value_text": "x"}
			)
			response.save()
			response.submit()
			attempts.append(response)

		self.assertEqual(attempts[0].attempt_number, 1)
		self.assertEqual(attempts[1].attempt_number, 2)
		self.assertEqual(attempts[1].attempt_count, 2)

	def test_test_entries_do_not_join_an_attempt_pool(self):
		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")

		response = make_response(survey, is_test=1, email="a@example.com")
		response.append(
			"answers", {"question": question.name, "answer_type": "Text", "value_text": "x"}
		)
		response.save()
		response.submit()

		self.assertEqual(response.attempt_number, 1)
		self.assertEqual(response.attempt_count, 1)
