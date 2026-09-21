# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from survey.constants import (
	SCORING_AFTER_PAGE,
	SCORING_NONE,
	SCORING_WITH_ANSWERS,
	STATUS_OPEN,
	SURVEY_TYPE_ASSESSMENT,
	SURVEY_TYPE_SURVEY,
)
from survey.tests.factories import make_option, make_question, make_survey


class TestSurvey(IntegrationTestCase):

	# -- tokens --------------------------------------------------------

	def test_access_token_is_generated_and_unique(self):
		first = make_survey()
		second = make_survey()

		self.assertTrue(first.access_token)
		self.assertNotEqual(first.access_token, second.access_token)
		self.assertEqual(len(first.access_token), 32)

	def test_regenerating_the_token_changes_the_public_link(self):
		survey = make_survey()
		original = survey.access_token

		survey.regenerate_access_token()

		self.assertNotEqual(survey.access_token, original)
		self.assertIn(survey.access_token, survey.get_start_url())

	# -- type defaults -------------------------------------------------

	def test_plain_survey_type_turns_off_scoring(self):
		survey = make_survey(survey_type=SURVEY_TYPE_SURVEY, scoring_type=SCORING_WITH_ANSWERS)
		self.assertEqual(survey.scoring_type, SCORING_NONE)

	def test_assessment_defaults_to_invited_and_scored(self):
		survey = make_survey(survey_type=SURVEY_TYPE_ASSESSMENT)
		self.assertEqual(survey.access_mode, "Invited Only")
		self.assertEqual(survey.scoring_type, SCORING_WITH_ANSWERS)

	def test_defaults_are_not_reapplied_on_later_saves(self):
		"""A manager's deliberate override must survive the next save."""
		survey = make_survey(survey_type=SURVEY_TYPE_ASSESSMENT)
		survey.access_mode = "Public"
		survey.save()
		survey.reload()

		self.assertEqual(survey.access_mode, "Public")

	# -- constraints ---------------------------------------------------

	def test_roaming_conflicts_with_per_page_answer_reveal(self):
		survey = make_survey(scoring_type=SCORING_AFTER_PAGE)
		survey.allow_roaming = 1

		self.assertRaises(frappe.ValidationError, survey.save)

	def test_passing_score_must_be_a_percentage(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		survey.passing_score = 140

		self.assertRaises(frappe.ValidationError, survey.save)

	def test_time_limit_must_be_positive_when_enabled(self):
		survey = make_survey()
		survey.is_time_limited = 1
		survey.time_limit = 0

		self.assertRaises(frappe.ValidationError, survey.save)

	def test_certification_requires_scoring(self):
		survey = make_survey(scoring_type=SCORING_NONE)
		survey.is_certification = 1
		survey.save()

		# Cleared rather than thrown: the checkbox is hidden without scoring.
		self.assertFalse(survey.is_certification)

	def test_responsible_must_keep_access_to_a_restricted_survey(self):
		user = make_user("restricted-officer@example.com", "Survey User")
		other = make_user("other-officer@example.com", "Survey User")

		survey = make_survey(responsible=user)
		survey.append("restricted_to", {"user": other})

		self.assertRaises(frappe.ValidationError, survey.save)

	# -- derived fields ------------------------------------------------

	def test_max_obtainable_score_sums_the_best_answers(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)

		single = make_question(survey, question_type="Single Choice")
		make_option(single, "Right", is_correct=1, score=5)
		make_option(single, "Also right", is_correct=1, score=3)

		multiple = make_question(survey, question_type="Multiple Choice")
		make_option(multiple, "A", is_correct=1, score=2)
		make_option(multiple, "B", is_correct=1, score=2)
		make_option(multiple, "Wrong", score=-1)

		numeric = make_question(survey, question_type="Numeric", correct_number=42, score=4)

		survey.reload()

		# 5 (best single) + 4 (both positive multiples) + 4 (numeric) = 13.
		self.assertEqual(survey.max_obtainable_score, 13)
		self.assertEqual(survey.question_count, 3)

	def test_conditional_questions_disable_attempt_limits(self):
		"""With skip logic, two attempts are not comparable, so the limit goes."""
		survey = make_survey(access_mode="Invited Only")
		survey.limit_attempts = 1
		survey.attempts_limit = 2
		survey.save()
		self.assertTrue(survey.limit_attempts)

		trigger = make_question(survey, question_type="Single Choice")
		option = make_option(trigger, "Yes")
		dependent = make_question(survey, question_type="Single Line Text")
		dependent.append("triggering_options", {"option": option.name})
		dependent.save()

		survey.reload()
		self.assertTrue(survey.has_conditional_questions)
		self.assertFalse(survey.limit_attempts)

	def test_public_survey_without_login_cannot_limit_attempts(self):
		survey = make_survey(access_mode="Public")
		survey.limit_attempts = 1
		survey.attempts_limit = 3
		survey.save()

		self.assertFalse(survey.limit_attempts)

	# -- readiness -----------------------------------------------------

	def test_cannot_open_a_survey_with_no_questions(self):
		survey = make_survey()
		survey.status = STATUS_OPEN

		self.assertRaises(frappe.ValidationError, survey.save)

	def test_cannot_open_a_scored_survey_worth_no_points(self):
		survey = make_survey(scoring_type=SCORING_WITH_ANSWERS)
		make_question(survey, question_type="Single Line Text")

		survey.reload()
		survey.status = STATUS_OPEN

		self.assertRaises(frappe.ValidationError, survey.save)

	def test_a_complete_survey_can_be_opened(self):
		survey = make_survey()
		make_question(survey, question_type="Single Line Text")

		survey.reload()
		survey.status = STATUS_OPEN
		survey.save()

		self.assertTrue(survey.is_open)

	# -- deletion ------------------------------------------------------

	def test_cannot_delete_a_survey_that_has_responses(self):
		from survey.tests.factories import make_response

		survey = make_survey()
		make_question(survey, question_type="Single Line Text")
		make_response(survey)

		self.assertRaises(frappe.ValidationError, frappe.delete_doc, "Survey", survey.name)

	def test_deleting_a_survey_removes_its_questions(self):
		survey = make_survey()
		question = make_question(survey, question_type="Single Line Text")

		frappe.delete_doc("Survey", survey.name)

		self.assertFalse(frappe.db.exists("Survey Question", question.name))


def make_user(email: str, role: str) -> str:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles(role)
	return email
