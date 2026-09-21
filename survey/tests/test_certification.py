# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

"""Certification: badges, the certificate PDF, and the section breakdown."""

import frappe
from frappe.tests import IntegrationTestCase

from survey import certification
from survey.api import player
from survey.constants import (
	PAGINATION_PER_QUESTION,
	SCORING_AFTER_PAGE,
	SCORING_NONE,
	SCORING_WITH_ANSWERS,
	SCORING_WITHOUT_ANSWERS,
	STATUS_OPEN,
)
from survey.tests.factories import (
	make_option,
	make_question,
	make_response,
	make_section,
	make_survey,
)


def open_survey(**values):
	values.setdefault("status", "Draft")
	return make_survey(**values)


def publish(survey):
	survey.reload()
	survey.status = STATUS_OPEN
	survey.save(ignore_permissions=True)
	return survey


def make_badge(**values):
	values.setdefault("badge_name", frappe.generate_hash(length=8))
	return frappe.get_doc({"doctype": "Survey Badge", **values}).insert(ignore_permissions=True)


class TestBadgeOwnership(IntegrationTestCase):
	"""`Survey.badge` <-> `Survey Badge.survey`, kept in sync from the survey side."""

	def test_turning_on_give_badge_without_a_badge_is_rejected(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS, is_certification=1, login_required=1)
		survey.give_badge = 1

		self.assertRaises(frappe.ValidationError, survey.save)

	def test_picking_a_badge_links_it_back_to_the_survey(self):
		badge = make_badge()
		survey = open_survey(
			scoring_type=SCORING_WITH_ANSWERS,
			is_certification=1,
			login_required=1,
			give_badge=1,
			badge=badge.name,
		)

		badge.reload()
		self.assertEqual(badge.survey, survey.name)

	def test_a_badge_already_claimed_by_another_survey_is_refused(self):
		badge = make_badge()
		open_survey(
			scoring_type=SCORING_WITH_ANSWERS,
			is_certification=1,
			login_required=1,
			give_badge=1,
			badge=badge.name,
		)

		other = open_survey(scoring_type=SCORING_WITH_ANSWERS, is_certification=1, login_required=1)
		other.give_badge = 1
		other.badge = badge.name

		self.assertRaises(frappe.ValidationError, other.save)

	def test_swapping_badges_releases_the_old_one(self):
		first = make_badge()
		second = make_badge()
		survey = open_survey(
			scoring_type=SCORING_WITH_ANSWERS,
			is_certification=1,
			login_required=1,
			give_badge=1,
			badge=first.name,
		)

		survey.badge = second.name
		survey.save()

		first.reload()
		second.reload()
		self.assertIsNone(first.survey)
		self.assertEqual(second.survey, survey.name)

	def test_turning_off_give_badge_clears_and_releases_the_badge(self):
		badge = make_badge()
		survey = open_survey(
			scoring_type=SCORING_WITH_ANSWERS,
			is_certification=1,
			login_required=1,
			give_badge=1,
			badge=badge.name,
		)

		survey.give_badge = 0
		survey.save()

		badge.reload()
		self.assertIsNone(survey.badge)
		self.assertIsNone(badge.survey)

	def test_a_badge_cannot_belong_to_an_anonymous_survey(self):
		"""`give_badge` needs `login_required`; without it the badge is dropped
		rather than silently kept switched on for a survey that can never
		award it."""
		badge = make_badge()
		survey = open_survey(
			scoring_type=SCORING_WITH_ANSWERS,
			is_certification=1,
			login_required=0,
			give_badge=1,
			badge=badge.name,
		)

		self.assertFalse(survey.give_badge)
		self.assertFalse(survey.badge)


class TestBadgeAward(IntegrationTestCase):
	def setUp(self):
		self.badge = make_badge()
		self.survey = open_survey(
			pagination=PAGINATION_PER_QUESTION,
			scoring_type=SCORING_WITH_ANSWERS,
			passing_score=50,
			is_certification=1,
			login_required=1,
			give_badge=1,
			badge=self.badge.name,
		)
		self.question = make_question(self.survey, question_type="Single Choice")
		self.right = make_option(self.question, "Right", is_correct=1, score=10)
		make_option(self.question, "Wrong", score=0)
		publish(self.survey)

	def _pass(self):
		token = player.start(self.survey.access_token)["response_token"]
		state = player.begin(self.survey.access_token, token)
		return player.submit_page(
			self.survey.access_token,
			token,
			state["page"]["id"],
			{self.question.name: {"value": self.right.name}},
		)

	def test_passing_awards_the_badge(self):
		self._pass()

		award = frappe.get_all(
			"Survey Badge Award",
			filters={"badge": self.badge.name},
			fields=["survey", "user", "response"],
		)
		self.assertEqual(len(award), 1)
		self.assertEqual(award[0].survey, self.survey.name)
		self.assertEqual(award[0].user, "Administrator")

	def test_awarding_is_idempotent(self):
		self._pass()
		response = frappe.get_doc(
			"Survey Response", frappe.db.get_value("Survey Response", {"survey": self.survey.name})
		)

		certification.award_badge(response, self.survey)
		certification.award_badge(response, self.survey)

		self.assertEqual(
			frappe.db.count("Survey Badge Award", {"response": response.name}), 1
		)

	def test_cancelling_the_response_revokes_the_badge(self):
		self._pass()
		response = frappe.get_doc(
			"Survey Response", frappe.db.get_value("Survey Response", {"survey": self.survey.name})
		)

		response.cancel()

		self.assertEqual(frappe.db.count("Survey Badge Award", {"response": response.name}), 0)

	def test_a_test_entry_never_earns_a_badge(self):
		response = make_response(self.survey, is_test=1, user="Administrator")
		response.append(
			"answers",
			{"question": self.question.name, "answer_type": "Option", "selected_option": self.right.name},
		)
		response.submit()

		self.assertEqual(frappe.db.count("Survey Badge Award", {"response": response.name}), 0)

	def test_failing_does_not_award_a_badge(self):
		wrong = frappe.db.get_value(
			"Survey Question Option", {"question": self.question.name, "label": "Wrong"}, "name"
		)
		token = player.start(self.survey.access_token)["response_token"]
		state = player.begin(self.survey.access_token, token)
		player.submit_page(
			self.survey.access_token, token, state["page"]["id"], {self.question.name: {"value": wrong}}
		)

		# Scoped to this test's own badge: `IntegrationTestCase` only rolls
		# back once per class, so an unscoped count would also see whatever
		# an earlier test method in this class already committed.
		self.assertEqual(frappe.db.count("Survey Badge Award", {"badge": self.badge.name}), 0)


class TestSectionBreakdown(IntegrationTestCase):
	def test_unscored_questions_are_left_out(self):
		survey = open_survey(scoring_type=SCORING_NONE)
		question = make_question(survey, question_type="Single Line Text")
		response = make_response(survey)
		response.append(
			"answers", {"question": question.name, "answer_type": "Text", "value_text": "hi"}
		)
		response.save(ignore_permissions=True)

		self.assertEqual(response.get_section_breakdown(), [])

	def test_single_choice_is_correct_or_incorrect(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=5)
		make_option(question, "Wrong", score=0)

		response = make_response(survey)
		response.append(
			"answers", {"question": question.name, "answer_type": "Option", "selected_option": right.name}
		)
		response.save(ignore_permissions=True)

		[bucket] = response.get_section_breakdown()
		self.assertEqual((bucket["correct"], bucket["partial"], bucket["incorrect"]), (1, 0, 0))

	def test_multiple_choice_can_be_partial(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Multiple Choice")
		right = make_option(question, "Right", is_correct=1, score=4)
		also_right = make_option(question, "Also Right", is_correct=1, score=4)
		make_option(question, "Wrong", score=-2)

		response = make_response(survey)
		# Only one of the two correct options picked -> partial, not correct.
		response.append(
			"answers", {"question": question.name, "answer_type": "Option", "selected_option": right.name}
		)
		response.save(ignore_permissions=True)

		[bucket] = response.get_section_breakdown()
		self.assertEqual((bucket["correct"], bucket["partial"], bucket["incorrect"]), (0, 1, 0))

		response.append(
			"answers",
			{"question": question.name, "answer_type": "Option", "selected_option": also_right.name},
		)
		response.save(ignore_permissions=True)

		[bucket] = response.get_section_breakdown()
		self.assertEqual((bucket["correct"], bucket["partial"], bucket["incorrect"]), (1, 0, 0))

	def test_a_wrong_only_pick_is_incorrect_not_partial(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Multiple Choice")
		make_option(question, "Right", is_correct=1, score=4)
		wrong = make_option(question, "Wrong", score=-2)

		response = make_response(survey)
		response.append(
			"answers", {"question": question.name, "answer_type": "Option", "selected_option": wrong.name}
		)
		response.save(ignore_permissions=True)

		[bucket] = response.get_section_breakdown()
		self.assertEqual((bucket["correct"], bucket["partial"], bucket["incorrect"]), (0, 0, 1))

	def test_a_skipped_question_is_counted_as_skipped(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Numeric", correct_number=5, score=3)

		response = make_response(survey)
		response.append("answers", {"question": question.name, "skipped": 1})
		response.save(ignore_permissions=True)

		[bucket] = response.get_section_breakdown()
		self.assertEqual(bucket["skipped"], 1)
		self.assertEqual(bucket["total"], 1)

	def test_directly_scorable_types_are_binary(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		question = make_question(survey, question_type="Numeric", correct_number=5, score=3)

		response = make_response(survey)
		response.append(
			"answers", {"question": question.name, "answer_type": "Number", "value_number": 5}
		)
		response.save(ignore_permissions=True)

		[bucket] = response.get_section_breakdown()
		self.assertEqual((bucket["correct"], bucket["incorrect"]), (1, 0))

	def test_grouped_by_section_with_a_general_bucket_for_the_rest(self):
		survey = open_survey(scoring_type=SCORING_WITH_ANSWERS)
		orphan = make_question(survey, question_type="Numeric", correct_number=1, score=1)
		section = make_section(survey, title="Part One")
		grouped = make_question(survey, question_type="Numeric", correct_number=2, score=1)

		response = make_response(survey)
		response.append(
			"answers", {"question": orphan.name, "answer_type": "Number", "value_number": 1}
		)
		response.append(
			"answers", {"question": grouped.name, "answer_type": "Number", "value_number": 2}
		)
		response.save(ignore_permissions=True)

		breakdown = {row["section"]: row for row in response.get_section_breakdown()}
		self.assertIn(None, breakdown)
		self.assertIn(section.name, breakdown)
		self.assertEqual(breakdown[section.name]["title"], "Part One")
		self.assertEqual(breakdown[section.name]["correct"], 1)


class TestCertificateAvailability(IntegrationTestCase):
	def _passed_certification(self, **survey_values):
		values = {
			"pagination": PAGINATION_PER_QUESTION,
			"scoring_type": SCORING_WITH_ANSWERS,
			"passing_score": 50,
			"is_certification": 1,
		}
		values.update(survey_values)
		survey = open_survey(**values)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=10)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": right.name}}
		)

		response = frappe.get_doc(
			"Survey Response", frappe.db.get_value("Survey Response", {"survey": survey.name})
		)
		return survey, response, token

	def test_a_passed_certification_response_is_available(self):
		survey, response, _ = self._passed_certification()
		self.assertTrue(certification.is_certificate_available(survey, response))

	def test_a_non_certification_survey_has_none(self):
		survey, response, _ = self._passed_certification(is_certification=0)
		self.assertFalse(certification.is_certificate_available(survey, response))

	def test_a_test_entry_has_none(self):
		survey = open_survey(
			pagination=PAGINATION_PER_QUESTION,
			scoring_type=SCORING_WITH_ANSWERS,
			passing_score=50,
			is_certification=1,
		)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=10)
		publish(survey)

		response = make_response(survey, is_test=1)
		response.append(
			"answers", {"question": question.name, "answer_type": "Option", "selected_option": right.name}
		)
		response.submit()

		self.assertFalse(certification.is_certificate_available(survey, response))

	def test_download_streams_a_pdf_for_the_owner(self):
		"""Converting to PDF needs wkhtmltopdf to fetch the site's own static
		assets over HTTP, which needs the site's hostname to actually
		resolve — true wherever the site is really served from (that is how
		anyone reaches it at all), but not necessarily true from a bare test
		runner in a sandbox with no DNS entry for it. Skip narrowly rather
		than fail on an environment limitation this app cannot fix.
		"""
		survey, response, token = self._passed_certification()

		frappe.local.response = frappe._dict()
		try:
			certification.download_certificate(survey.access_token, token)
		except OSError as error:
			if "HostNotFoundError" not in str(error):
				raise
			self.skipTest("wkhtmltopdf could not resolve the site's own hostname in this environment")

		self.assertEqual(frappe.local.response.type, "pdf")
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))

	def test_download_renders_the_certificate_content(self):
		"""The HTML the certificate is built from, independent of whether
		wkhtmltopdf can also convert it — see the skip note above."""
		survey, response, token = self._passed_certification()

		frappe.flags.ignore_print_permissions = True
		try:
			html = frappe.get_print(
				"Survey Response", response.name, certification.CERTIFICATE_PRINT_FORMAT,
				doc=response, as_pdf=False,
			)
		finally:
			frappe.flags.ignore_print_permissions = False

		self.assertIn("Certificate of Achievement", html)
		self.assertIn(survey.title, html)
		self.assertIn(response.name, html)
		self.assertIn("family-modern", html)
		self.assertIn("colour-purple", html)

	def test_download_refuses_a_response_that_has_not_passed(self):
		survey = open_survey(
			pagination=PAGINATION_PER_QUESTION,
			scoring_type=SCORING_WITH_ANSWERS,
			passing_score=100,
			is_certification=1,
		)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=1)
		wrong = make_option(question, "Wrong", score=0)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": wrong.name}}
		)

		self.assertRaises(
			frappe.PermissionError, certification.download_certificate, survey.access_token, token
		)

	def test_download_refuses_an_unknown_token(self):
		self.assertRaises(
			frappe.PermissionError, certification.download_certificate, "not-a-real-token", "also-fake"
		)


class TestCertificateContext(IntegrationTestCase):
	def test_layout_splits_family_and_colour(self):
		survey, response, _ = self._build("Classic Gold")
		context = certification.build_certificate_context(response)

		self.assertEqual(context["layout_family"], "classic")
		self.assertEqual(context["layout_colour"], "gold")

	def test_section_breakdown_is_hidden_when_answers_are_not_revealed(self):
		survey, response, _ = self._build("Modern Purple", scoring_type=SCORING_WITHOUT_ANSWERS)
		context = certification.build_certificate_context(response)

		self.assertEqual(context["section_breakdown"], [])

	def test_section_breakdown_is_shown_when_answers_are_revealed(self):
		survey, response, _ = self._build("Modern Purple", scoring_type=SCORING_AFTER_PAGE)
		context = certification.build_certificate_context(response)

		self.assertTrue(context["section_breakdown"])

	def _build(self, layout, scoring_type=SCORING_WITH_ANSWERS):
		survey = open_survey(
			pagination=PAGINATION_PER_QUESTION,
			scoring_type=scoring_type,
			passing_score=50,
			is_certification=1,
			certificate_layout=layout,
		)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=10)
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": right.name}}
		)

		response = frappe.get_doc(
			"Survey Response", frappe.db.get_value("Survey Response", {"survey": survey.name})
		)
		return survey, response, token
