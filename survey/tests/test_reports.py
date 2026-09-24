# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

"""Phase 5: the Query Reports and the cross-question filtering API."""

import frappe
from frappe.tests import IntegrationTestCase

from survey.api import player, reports
from survey.constants import SCORING_WITH_ANSWERS, STATUS_OPEN
from survey.survey.report.score_distribution import score_distribution
from survey.survey.report.survey_answer_distribution import survey_answer_distribution
from survey.survey.report.survey_answers import survey_answers
from survey.tests.factories import make_option, make_question, make_survey


def open_survey(**values):
	values.setdefault("status", "Draft")
	return make_survey(**values)


def publish(survey):
	survey.reload()
	survey.status = STATUS_OPEN
	survey.save(ignore_permissions=True)
	return survey


class TestReports(IntegrationTestCase):
	"""One scored survey, one Single Choice question with a right and a
	wrong option, completed once each way — small enough to hand-check every
	report's output against."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.survey = open_survey(scoring_type=SCORING_WITH_ANSWERS, passing_score=50)
		self.question = make_question(self.survey, question_type="Single Choice", title="Colour?")
		self.correct = make_option(self.question, "Blue", is_correct=1, score=1)
		self.wrong = make_option(self.question, "Red")
		publish(self.survey)

		self.correct_response = self._answer(self.correct.name)
		self.wrong_response = self._answer(self.wrong.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _answer(self, option: str) -> str:
		token = player.start(self.survey.access_token)["response_token"]
		player.begin(self.survey.access_token, token)
		page = player.get_state(self.survey.access_token, token)["page"]
		player.submit_page(
			self.survey.access_token, token, page["id"], {self.question.name: {"value": option}}
		)
		return frappe.db.get_value("Survey Response", {"access_token": token}, "name")

	def test_survey_answers_lists_one_row_per_answer(self):
		_columns, data = survey_answers.execute({"survey": self.survey.name})
		self.assertEqual(len(data), 2)
		answers = {row["response"]: row["answer"] for row in data}
		self.assertEqual(answers[self.correct_response], "Blue")
		self.assertEqual(answers[self.wrong_response], "Red")

	def test_survey_answers_filters_by_question(self):
		_columns, data = survey_answers.execute(
			{"survey": self.survey.name, "question": self.question.name}
		)
		self.assertEqual(len(data), 2)

	def test_survey_answer_distribution_splits_by_option(self):
		_columns, data = survey_answer_distribution.execute({"survey": self.survey.name})
		by_option = {row["option_label"]: row["count"] for row in data}
		self.assertEqual(by_option["Blue"], 1)
		self.assertEqual(by_option["Red"], 1)
		for row in data:
			self.assertEqual(row["percentage"], 50.0)

	def test_score_distribution_buckets_by_percentage(self):
		_columns, data = score_distribution.execute({"survey": self.survey.name})
		total = sum(row["count"] for row in data)
		self.assertEqual(total, 2)

		passed_bucket = next(r for r in data if r["passed_count"] > 0)
		self.assertEqual(passed_bucket["passed_count"], 1)

	def test_dashboard_summary_counts_and_averages(self):
		summary = reports.get_dashboard_summary(self.survey.name)
		self.assertEqual(summary["total_responses"], 2)
		self.assertEqual(summary["completed_responses"], 2)
		self.assertEqual(summary["completion_rate"], 100.0)
		self.assertEqual(summary["average_score"], 50.0)
		self.assertEqual(summary["pass_rate"], 50.0)

	def test_get_choice_questions_lists_the_question_and_its_options(self):
		questions = reports.get_choice_questions(self.survey.name)
		self.assertEqual(len(questions), 1)
		labels = {opt["label"] for opt in questions[0]["options"]}
		self.assertEqual(labels, {"Blue", "Red"})

	def test_filtered_responses_matches_only_the_chosen_option(self):
		result = reports.get_filtered_responses(
			self.survey.name, [{"question": self.question.name, "option": self.correct.name}]
		)
		self.assertEqual(result["total"], 1)
		self.assertEqual(result["rows"][0]["name"], self.correct_response)

	def test_filtered_responses_with_no_filters_returns_everyone(self):
		result = reports.get_filtered_responses(self.survey.name, [])
		self.assertEqual(result["total"], 2)

	def test_filtered_responses_ands_across_rows(self):
		# A second filter row on the same single-choice question can never be
		# satisfied alongside the first (one answer per question), so the
		# intersection must come back empty rather than erroring.
		result = reports.get_filtered_responses(
			self.survey.name,
			[
				{"question": self.question.name, "option": self.correct.name},
				{"question": self.question.name, "option": self.wrong.name},
			],
		)
		self.assertEqual(result["total"], 0)
