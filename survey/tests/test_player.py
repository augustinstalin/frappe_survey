# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

"""End-to-end tests for the public survey-taking flow."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from survey.api import player
from survey.constants import (
	PAGINATION_ONE_PAGE,
	PAGINATION_PER_QUESTION,
	PAGINATION_PER_SECTION,
	SCORING_WITH_ANSWERS,
	STATUS_CLOSED,
	STATUS_OPEN,
)
from survey.player import navigation
from survey.player.access import SurveyAccessError, resolve
from survey.tests.factories import make_option, make_question, make_section, make_survey


def open_survey(**values):
	"""A survey that is actually takeable."""
	values.setdefault("status", "Draft")
	survey = make_survey(**values)
	return survey


def publish(survey):
	survey.reload()
	survey.status = STATUS_OPEN
	survey.save(ignore_permissions=True)
	return survey


class TestPlayerAccess(IntegrationTestCase):
	def test_unknown_survey_token_is_rejected(self):
		with self.assertRaises(SurveyAccessError) as caught:
			resolve("not-a-real-token", require_response=False)

		self.assertEqual(caught.exception.code, "survey_missing")

	def test_closed_survey_is_rejected(self):
		survey = open_survey()
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		survey.status = STATUS_CLOSED
		survey.save(ignore_permissions=True)

		with self.assertRaises(SurveyAccessError) as caught:
			resolve(survey.access_token, require_response=False)

		self.assertEqual(caught.exception.code, "survey_closed")

	def test_empty_survey_is_rejected(self):
		survey = make_survey()
		frappe.db.set_value("Survey", survey.name, "status", STATUS_OPEN, update_modified=False)
		survey.reload()

		with self.assertRaises(SurveyAccessError) as caught:
			resolve(survey.access_token, require_response=False)

		self.assertEqual(caught.exception.code, "survey_empty")

	def test_invited_only_survey_refuses_a_bare_link(self):
		survey = open_survey(access_mode="Invited Only")
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		result = player.start(survey.access_token)
		self.assertEqual(result["state"], "error")
		self.assertEqual(result["code"], "response_required")

	def test_a_response_token_from_another_survey_is_rejected(self):
		first = open_survey()
		make_question(first, question_type="Single Line Text")
		publish(first)

		second = open_survey()
		make_question(second, question_type="Single Line Text")
		publish(second)

		started = player.start(second.access_token)
		foreign_token = started["response_token"]

		with self.assertRaises(SurveyAccessError) as caught:
			resolve(first.access_token, foreign_token)

		self.assertEqual(caught.exception.code, "response_missing")

	def test_a_signed_in_user_cannot_use_an_anonymous_token(self):
		"""Guards against a shared link handing over somebody's answers."""
		survey = open_survey()
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		response = frappe.get_doc(
			{"doctype": "Survey Response", "survey": survey.name, "user": "Administrator"}
		).insert(ignore_permissions=True)

		original = frappe.session.user
		try:
			frappe.set_user("Guest")
			with self.assertRaises(SurveyAccessError) as caught:
				resolve(survey.access_token, response.access_token)
			self.assertEqual(caught.exception.code, "wrong_user")
		finally:
			frappe.set_user(original)


class TestPlayerFlow(IntegrationTestCase):
	def build(self, **values):
		"""Two questions, one per page."""
		survey = open_survey(**values)
		self.q1 = make_question(survey, question_type="Single Line Text", title="Your name")
		self.q2 = make_question(survey, question_type="Numeric", title="Your age")
		return publish(survey)

	def test_start_creates_a_response_and_returns_its_token(self):
		survey = self.build()

		state = player.start(survey.access_token)

		self.assertEqual(state["state"], "new")
		self.assertTrue(state["response_token"])
		self.assertEqual(state["survey"]["title"], survey.title)

	def test_start_reuses_an_existing_response(self):
		survey = self.build()

		first = player.start(survey.access_token)
		second = player.start(survey.access_token, response_token=first["response_token"])

		self.assertEqual(first["response_token"], second["response_token"])

	def test_begin_shows_the_first_question(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]

		state = player.begin(survey.access_token, token)

		self.assertEqual(state["state"], "in_progress")
		self.assertEqual(state["page"]["questions"][0]["id"], self.q1.name)
		self.assertEqual(state["progress"]["total"], 2)
		self.assertFalse(state["navigation"]["is_last"])

	def test_a_full_pass_through_completes_the_response(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.q1.name: {"value": "Ada"}}
		)
		self.assertEqual(state["page"]["questions"][0]["id"], self.q2.name)
		self.assertTrue(state["navigation"]["is_last"])

		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.q2.name: {"value": 36}}
		)

		self.assertEqual(state["state"], "done")

		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertEqual(response.docstatus, 1)
		self.assertEqual(response.status, "Completed")
		self.assertEqual(len(response.answers), 2)

	def test_validation_errors_do_not_advance_the_page(self):
		survey = open_survey()
		question = make_question(
			survey, question_type="Single Line Text", mandatory=1, title="Required"
		)
		make_question(survey, question_type="Single Line Text", title="Second")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		result = player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": ""}}
		)

		self.assertEqual(result["state"], "invalid")
		self.assertIn(question.name, result["errors"])

	def test_answers_to_a_question_not_on_the_page_are_ignored(self):
		"""The client picks the question ids, so this is a real boundary."""
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		player.submit_page(
			survey.access_token,
			token,
			state["page"]["id"],
			{self.q1.name: {"value": "Ada"}, self.q2.name: {"value": 99}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		answered = {row.question for row in response.answers}

		# q2 lives on the next page; its answer must not have been saved here.
		self.assertEqual(answered, {self.q1.name})

	def test_resuming_returns_to_the_last_page(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.q1.name: {"value": "Ada"}}
		)

		resumed = player.get_state(survey.access_token, token)

		self.assertEqual(resumed["state"], "in_progress")
		self.assertEqual(resumed["page"]["questions"][0]["id"], self.q2.name)

	def test_going_back_repopulates_the_given_answer(self):
		survey = self.build(allow_roaming=1)
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		page_id = state["page"]["id"]

		player.submit_page(survey.access_token, token, page_id, {self.q1.name: {"value": "Ada"}})
		back = player.go_back(survey.access_token, token, page_id)

		self.assertEqual(back["page"]["id"], page_id)
		self.assertEqual(back["answers"][self.q1.name]["value"], "Ada")

	def test_going_back_is_refused_when_roaming_is_off(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		result = player.go_back(survey.access_token, token, state["page"]["id"])

		self.assertEqual(result["state"], "error")
		self.assertEqual(result["code"], "not_allowed")

	def test_submitting_a_finished_response_is_a_no_op(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.q1.name: {"value": "Ada"}}
		)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.q2.name: {"value": 36}}
		)

		again = player.submit_page(survey.access_token, token, self.q2.name, {self.q2.name: {"value": 1}})

		self.assertEqual(again["state"], "done")
		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertEqual(response.docstatus, 1)


class TestPagination(IntegrationTestCase):
	def test_one_page_holds_every_question(self):
		survey = open_survey(pagination=PAGINATION_ONE_PAGE)
		make_question(survey, question_type="Single Line Text")
		make_question(survey, question_type="Numeric")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertEqual(len(state["page"]["questions"]), 2)
		self.assertTrue(state["navigation"]["is_last"])

	def test_one_page_per_section(self):
		survey = open_survey(pagination=PAGINATION_PER_SECTION)
		first = make_section(survey, title="About you")
		make_question(survey, question_type="Single Line Text")
		make_question(survey, question_type="Numeric")
		make_section(survey, title="About us")
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertEqual(state["page"]["id"], first.name)
		self.assertEqual(len(state["page"]["questions"]), 2)
		self.assertEqual(state["progress"]["total"], 2)

	def test_an_empty_section_is_not_a_page(self):
		survey = open_survey(pagination=PAGINATION_PER_SECTION)
		make_section(survey, title="Empty")
		populated = make_section(survey, title="Real")
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertEqual(state["page"]["id"], populated.name)
		self.assertEqual(state["progress"]["total"], 1)

	def test_a_described_section_gets_its_own_page_per_question(self):
		survey = open_survey(pagination=PAGINATION_PER_QUESTION)
		intro = make_section(survey, title="Part one", description="<p>Read this first.</p>")
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertEqual(state["page"]["id"], intro.name)
		self.assertEqual(state["page"]["kind"], "section")
		self.assertEqual(state["page"]["questions"], [])

	def test_a_section_without_a_description_gets_no_page(self):
		survey = open_survey(pagination=PAGINATION_PER_QUESTION)
		make_section(survey, title="Silent")
		question = make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertEqual(state["page"]["questions"][0]["id"], question.name)


class TestSkipLogicNavigation(IntegrationTestCase):
	def build(self):
		survey = open_survey(pagination=PAGINATION_PER_QUESTION)

		self.gate = make_question(survey, question_type="Single Choice", title="Do you drive?")
		self.yes = make_option(self.gate, "Yes")
		self.no = make_option(self.gate, "No")

		self.follow_up = make_question(
			survey, question_type="Single Line Text", title="Which car?"
		)
		self.follow_up.append("triggering_options", {"option": self.yes.name})
		self.follow_up.save(ignore_permissions=True)

		self.last = make_question(survey, question_type="Single Line Text", title="Anything else?")
		return publish(survey)

	def test_the_follow_up_is_skipped_when_not_triggered(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.gate.name: {"value": self.no.name}}
		)

		self.assertEqual(state["page"]["questions"][0]["id"], self.last.name)

	def test_the_follow_up_appears_when_triggered(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.gate.name: {"value": self.yes.name}}
		)

		self.assertEqual(state["page"]["questions"][0]["id"], self.follow_up.name)

	def test_progress_total_excludes_hidden_questions(self):
		survey = self.build()
		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {self.gate.name: {"value": self.no.name}}
		)

		# Gate + last question. The untriggered follow-up must not inflate it,
		# or the bar would appear to jump backwards.
		self.assertEqual(state["progress"]["total"], 2)

	def test_the_last_question_is_not_last_while_it_can_unlock_another(self):
		"""The gate is followed by a question that only it can reveal."""
		survey = open_survey(pagination=PAGINATION_PER_QUESTION)
		gate = make_question(survey, question_type="Single Choice", title="Continue?")
		yes = make_option(gate, "Yes")
		follow_up = make_question(survey, question_type="Single Line Text", title="Details")
		follow_up.append("triggering_options", {"option": yes.name})
		follow_up.save(ignore_permissions=True)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		# Nothing is unlocked yet, so the gate is currently the only page —
		# but it must not offer "Submit", because answering Yes adds one.
		self.assertFalse(state["navigation"]["is_last"])


class TestAnswerPersistence(IntegrationTestCase):
	def test_multiple_choice_stores_one_row_per_tick(self):
		survey = open_survey()
		question = make_question(survey, question_type="Multiple Choice")
		first = make_option(question, "A")
		second = make_option(question, "B")
		make_option(question, "C")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token,
			token,
			state["page"]["id"],
			{question.name: {"value": [first.name, second.name]}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertEqual(len(response.answers), 2)

	def test_a_comment_is_stored_alongside_the_options(self):
		survey = open_survey()
		question = make_question(survey, question_type="Single Choice", allow_comments=1)
		option = make_option(question, "Other")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token,
			token,
			state["page"]["id"],
			{question.name: {"value": option.name, "comment": "Something else"}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		kinds = sorted(row.answer_type for row in response.answers)
		self.assertEqual(kinds, ["Comment", "Option"])

	def test_an_unanswered_optional_question_is_recorded_as_skipped(self):
		"""Distinguishes "nobody answered" from "never shown" in the stats."""
		survey = open_survey()
		question = make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": ""}}
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertEqual(len(response.answers), 1)
		self.assertTrue(response.answers[0].skipped)

	def test_resubmitting_a_page_replaces_the_earlier_answer(self):
		survey = open_survey(allow_roaming=1)
		question = make_question(survey, question_type="Single Line Text")
		make_question(survey, question_type="Numeric")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		page_id = state["page"]["id"]

		player.submit_page(survey.access_token, token, page_id, {question.name: {"value": "first"}})
		player.submit_page(survey.access_token, token, page_id, {question.name: {"value": "second"}})

		response = frappe.get_doc("Survey Response", {"access_token": token})
		rows = [row for row in response.answers if row.question == question.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].value_text, "second")

	def test_matrix_answers_become_one_row_per_cell(self):
		survey = open_survey()
		question = make_question(survey, question_type="Matrix")
		column_a = make_option(question, "Good")
		make_option(question, "Bad")
		row_one = make_option(question, "Speed", is_matrix_row=1)
		row_two = make_option(question, "Price", is_matrix_row=1)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token,
			token,
			state["page"]["id"],
			{question.name: {"value": {row_one.name: [column_a.name], row_two.name: [column_a.name]}}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertEqual(len(response.answers), 2)
		self.assertEqual({row.matrix_row for row in response.answers}, {row_one.name, row_two.name})

	def test_an_identity_question_writes_onto_the_response(self):
		survey = open_survey()
		question = make_question(
			survey,
			question_type="Single Line Text",
			validate_email=1,
			save_as_email=1,
		)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token,
			token,
			state["page"]["id"],
			{question.name: {"value": "ada@example.com"}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertEqual(response.email, "ada@example.com")

	def test_a_question_unlocked_on_the_same_page_is_saved(self):
		"""Answer the gate and the question it reveals in one submission.

		Skip logic is evaluated against the answers already *stored*, so when
		the submission arrives the follow-up still looks hidden. Resolving the
		page for saving has to use the wider set, or the respondent's answer
		is silently discarded.
		"""
		survey = open_survey(pagination=PAGINATION_PER_SECTION)

		make_section(survey, title="Gate")
		gate = make_question(survey, question_type="Single Choice")
		yes = make_option(gate, "Yes")
		make_option(gate, "No")
		follow_up = make_question(survey, question_type="Single Line Text")
		follow_up.append("triggering_options", {"option": yes.name})
		follow_up.save(ignore_permissions=True)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		player.submit_page(
			survey.access_token,
			token,
			state["page"]["id"],
			{gate.name: {"value": yes.name}, follow_up.name: {"value": "a detail"}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		saved = [row for row in response.answers if row.question == follow_up.name]

		self.assertEqual(len(saved), 1)
		self.assertEqual(saved[0].value_text, "a detail")

	def test_answers_to_a_question_that_became_hidden_are_cleared(self):
		"""Tick Yes, answer the follow-up, then change the answer to No.

		A second section keeps the survey unfinished, so the page can be
		resubmitted — which is the situation this guards against.
		"""
		survey = open_survey(pagination=PAGINATION_PER_SECTION, allow_roaming=1)

		make_section(survey, title="Gate")
		gate = make_question(survey, question_type="Single Choice")
		yes = make_option(gate, "Yes")
		no = make_option(gate, "No")
		follow_up = make_question(survey, question_type="Single Line Text")
		follow_up.append("triggering_options", {"option": yes.name})
		follow_up.save(ignore_permissions=True)

		make_section(survey, title="After")
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		page_id = state["page"]["id"]

		player.submit_page(
			survey.access_token,
			token,
			page_id,
			{gate.name: {"value": yes.name}, follow_up.name: {"value": "a detail"}},
		)

		response = frappe.get_doc("Survey Response", {"access_token": token})
		self.assertTrue(any(row.question == follow_up.name for row in response.answers))

		# Flip the gate. The follow-up is hidden again, so its answer must go:
		# otherwise it keeps counting toward the score and keeps unlocking
		# whatever it triggers.
		player.submit_page(survey.access_token, token, page_id, {gate.name: {"value": no.name}})

		response.reload()
		self.assertFalse(any(row.question == follow_up.name for row in response.answers))


class TestScoringThroughThePlayer(IntegrationTestCase):
	def test_a_scored_run_reports_its_result(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS, passing_score=50)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=10)
		make_option(question, "Wrong", score=0)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": right.name}}
		)

		self.assertEqual(state["state"], "done")
		self.assertEqual(state["result"]["percentage"], 100)
		self.assertTrue(state["result"]["passed"])

	def test_the_answer_key_is_never_sent_before_the_page_is_submitted(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")
		make_option(question, "Right", is_correct=1, score=10)
		make_option(question, "Wrong", score=0)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		serialised = state["page"]["questions"][0]
		self.assertNotIn("correct_answers", state)
		for option in serialised["options"]:
			self.assertNotIn("is_correct", option)
			self.assertNotIn("score", option)


class TestTimeLimit(IntegrationTestCase):
	"""The survey-wide countdown.

	Every test here moves `started_on` backwards rather than waiting: the
	clock the server consults is `now() - started_on`, so shifting the start
	is the same thing as time passing, and runs in milliseconds.
	"""

	def setUp(self):
		self.survey = open_survey(
			pagination=PAGINATION_PER_QUESTION, is_time_limited=1, time_limit=10
		)
		self.first = make_question(self.survey, question_type="Single Line Text")
		make_question(self.survey, question_type="Single Line Text")
		publish(self.survey)

		self.token = player.start(self.survey.access_token)["response_token"]
		self.state = player.begin(self.survey.access_token, self.token)

	def _response(self):
		return frappe.get_doc("Survey Response", {"access_token": self.token})

	def _age_by(self, minutes):
		"""Pretend the run started `minutes` ago."""
		response = self._response()
		frappe.db.set_value(
			"Survey Response",
			response.name,
			"started_on",
			add_to_date(now_datetime(), minutes=-minutes),
			update_modified=False,
		)

	def test_the_payload_carries_the_time_left(self):
		timer = self.state["timer"]

		self.assertEqual(timer["limit_seconds"], 600)
		self.assertGreater(timer["time_left"], 590)
		self.assertLessEqual(timer["time_left"], 600)

	def test_an_untimed_survey_has_no_timer(self):
		survey = open_survey(pagination=PAGINATION_PER_QUESTION)
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertIsNone(state["timer"])

	def test_time_left_shrinks_as_the_clock_runs(self):
		self._age_by(4)

		state = player.get_state(self.survey.access_token, self.token)

		self.assertLess(state["timer"]["time_left"], 6 * 60 + 1)
		self.assertGreater(state["timer"]["time_left"], 5 * 60)

	def test_a_page_submitted_inside_the_grace_window_is_accepted(self):
		# Five seconds past ten minutes: over, but inside the ten-second grace.
		self._age_by(10 + 5 / 60)

		state = player.submit_page(
			self.survey.access_token,
			self.token,
			self.state["page"]["id"],
			{self.first.name: {"value": "in time"}},
		)

		self.assertEqual(state["state"], "in_progress")
		response = self._response()
		self.assertTrue(any(row.value_text == "in time" for row in response.answers))

	def test_a_page_submitted_past_the_grace_window_finishes_the_run(self):
		self._age_by(11)

		state = player.submit_page(
			self.survey.access_token,
			self.token,
			self.state["page"]["id"],
			{self.first.name: {"value": "too late"}},
		)

		self.assertEqual(state["state"], "done")
		self.assertTrue(state["timed_out"])

		response = self._response()
		self.assertEqual(response.docstatus, 1)
		# The answer arrived after the deadline, so it is not recorded.
		self.assertFalse(any(row.value_text == "too late" for row in response.answers))

	def test_a_timeout_submission_saves_the_page_and_finishes(self):
		state = player.submit_page(
			self.survey.access_token,
			self.token,
			self.state["page"]["id"],
			{self.first.name: {"value": "beat the buzzer"}},
			direction="timeout",
		)

		self.assertEqual(state["state"], "done")
		self.assertTrue(state["timed_out"])

		response = self._response()
		self.assertEqual(response.docstatus, 1)
		self.assertTrue(any(row.value_text == "beat the buzzer" for row in response.answers))

	def test_beginning_an_already_expired_response_finishes_it(self):
		self._age_by(20)

		state = player.begin(self.survey.access_token, self.token)

		self.assertEqual(state["state"], "done")
		self.assertTrue(state["timed_out"])

	def test_the_clock_starts_at_begin_not_at_start(self):
		"""A link opened and left alone does not burn the respondent's time."""
		survey = open_survey(
			pagination=PAGINATION_PER_QUESTION, is_time_limited=1, time_limit=10
		)
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		response = frappe.get_doc("Survey Response", {"access_token": token})

		self.assertIsNone(response.started_on)
		self.assertEqual(response.time_remaining(), 600)


class TestSkippedMandatoryQueue(IntegrationTestCase):
	"""Roaming lets a mandatory question be left blank — but not forever."""

	def setUp(self):
		self.survey = open_survey(
			pagination=PAGINATION_PER_QUESTION, allow_roaming=1, progress_display="Number"
		)
		self.one = make_question(self.survey, question_type="Single Line Text", mandatory=1)
		self.two = make_question(self.survey, question_type="Single Line Text", mandatory=1)
		self.three = make_question(self.survey, question_type="Single Line Text")
		publish(self.survey)

		self.token = player.start(self.survey.access_token)["response_token"]
		self.state = player.begin(self.survey.access_token, self.token)

	def _submit(self, page_id, answers, direction="next"):
		return player.submit_page(
			self.survey.access_token, self.token, page_id, answers, direction=direction
		)

	def test_a_mandatory_question_can_be_skipped_while_roaming(self):
		state = self._submit(self.state["page"]["id"], {self.one.name: {"value": None}})

		self.assertEqual(state["state"], "in_progress")
		self.assertEqual(state["page"]["questions"][0]["id"], self.two.name)

	def test_the_run_does_not_finish_with_a_mandatory_question_blank(self):
		state = self._submit(self.state["page"]["id"], {self.one.name: {"value": None}})
		state = self._submit(state["page"]["id"], {self.two.name: {"value": "two"}})
		state = self._submit(state["page"]["id"], {self.three.name: {"value": "three"}})

		# Reaching the end sends them back to the one they left blank.
		self.assertEqual(state["state"], "in_progress")
		self.assertEqual(state["page"]["questions"][0]["id"], self.one.name)
		self.assertTrue(state["navigation"]["is_revisiting"])

		response = frappe.get_doc("Survey Response", {"access_token": self.token})
		self.assertTrue(response.first_submitted)

	def test_answering_the_last_skipped_question_finishes_the_run(self):
		state = self._submit(self.state["page"]["id"], {self.one.name: {"value": None}})
		state = self._submit(state["page"]["id"], {self.two.name: {"value": "two"}})
		state = self._submit(state["page"]["id"], {self.three.name: {"value": "three"}})
		state = self._submit(state["page"]["id"], {self.one.name: {"value": "one, finally"}})

		self.assertEqual(state["state"], "done")

	def test_nothing_is_flagged_before_the_respondent_has_answered_anything(self):
		"""The count is about questions passed over, not questions unasked."""
		self.assertEqual(self.state["navigation"]["skipped_remaining"], 0)
		self.assertEqual(self.state["navigation"]["submit_label"], "continue")

	def test_the_button_says_so_when_something_is_still_unanswered(self):
		state = self._submit(self.state["page"]["id"], {self.one.name: {"value": None}})
		state = self._submit(state["page"]["id"], {self.two.name: {"value": "two"}})

		# Last page, but question one is still blank.
		self.assertEqual(state["navigation"]["submit_label"], "next_skipped")
		self.assertEqual(state["navigation"]["skipped_remaining"], 1)

	def test_the_button_says_submit_when_nothing_is_outstanding(self):
		state = self._submit(self.state["page"]["id"], {self.one.name: {"value": "one"}})
		state = self._submit(state["page"]["id"], {self.two.name: {"value": "two"}})

		self.assertEqual(state["navigation"]["submit_label"], "submit")
		self.assertEqual(state["navigation"]["skipped_remaining"], 0)

	def test_an_optional_question_never_joins_the_queue(self):
		state = self._submit(self.state["page"]["id"], {self.one.name: {"value": "one"}})
		state = self._submit(state["page"]["id"], {self.two.name: {"value": "two"}})
		state = self._submit(state["page"]["id"], {self.three.name: {"value": None}})

		self.assertEqual(state["state"], "done")

	def test_a_hidden_mandatory_question_does_not_block_finishing(self):
		"""A question nobody was shown cannot be one they failed to answer."""
		survey = open_survey(pagination=PAGINATION_PER_QUESTION, allow_roaming=1)
		gate = make_question(survey, question_type="Single Choice", mandatory=1)
		yes = make_option(gate, "Yes")
		make_option(gate, "No")
		follow_up = make_question(survey, question_type="Single Line Text", mandatory=1)
		follow_up.append("triggering_options", {"option": yes.name})
		follow_up.save(ignore_permissions=True)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		no = frappe.db.get_value(
			"Survey Question Option", {"question": gate.name, "label": "No"}, "name"
		)
		state = player.submit_page(
			survey.access_token, token, state["page"]["id"], {gate.name: {"value": no}}
		)

		self.assertEqual(state["state"], "done")


class TestBreadcrumb(IntegrationTestCase):
	def setUp(self):
		self.survey = open_survey(pagination=PAGINATION_PER_SECTION, allow_roaming=1)

		make_section(self.survey, title="About you")
		self.one = make_question(self.survey, question_type="Single Line Text", mandatory=1)
		make_section(self.survey, title="The product")
		self.two = make_question(self.survey, question_type="Single Line Text")
		make_section(self.survey, title="Anything else")
		make_question(self.survey, question_type="Single Line Text")
		publish(self.survey)

		self.token = player.start(self.survey.access_token)["response_token"]
		self.state = player.begin(self.survey.access_token, self.token)

	def test_the_trail_names_every_section(self):
		trail = self.state["breadcrumb"]

		self.assertEqual(
			[step["title"] for step in trail],
			["About you", "The product", "Anything else"],
		)
		self.assertEqual([step["state"] for step in trail], ["current", "todo", "todo"])

	def test_only_visited_sections_can_be_jumped_to(self):
		state = player.submit_page(
			self.survey.access_token,
			self.token,
			self.state["page"]["id"],
			{self.one.name: {"value": "me"}},
		)
		trail = state["breadcrumb"]

		self.assertEqual([step["state"] for step in trail], ["done", "current", "todo"])
		self.assertEqual([step["can_jump"] for step in trail], [True, False, False])

	def test_no_section_is_marked_pending_at_the_start(self):
		self.assertEqual([step["pending"] for step in self.state["breadcrumb"]], [False] * 3)

	def test_a_section_owing_an_answer_is_marked_pending(self):
		state = player.submit_page(
			self.survey.access_token,
			self.token,
			self.state["page"]["id"],
			{self.one.name: {"value": None}},
		)

		self.assertTrue(state["breadcrumb"][0]["pending"])
		self.assertFalse(state["breadcrumb"][1]["pending"])

	def test_jumping_back_saves_the_page_it_leaves(self):
		state = player.submit_page(
			self.survey.access_token,
			self.token,
			self.state["page"]["id"],
			{self.one.name: {"value": "me"}},
		)
		first_page = state["breadcrumb"][0]["id"]

		state = player.submit_page(
			self.survey.access_token,
			self.token,
			state["page"]["id"],
			{self.two.name: {"value": "typed on the way out"}},
			direction="jump",
			target_page_id=first_page,
		)

		self.assertEqual(state["page"]["id"], first_page)

		response = frappe.get_doc("Survey Response", {"access_token": self.token})
		self.assertTrue(any(row.value_text == "typed on the way out" for row in response.answers))

	def test_there_is_no_breadcrumb_on_the_other_layouts(self):
		survey = open_survey(pagination=PAGINATION_PER_QUESTION)
		make_question(survey, question_type="Single Line Text")
		make_question(survey, question_type="Single Line Text")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)

		self.assertEqual(state["breadcrumb"], [])
