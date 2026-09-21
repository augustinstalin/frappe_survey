# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from survey.constants import PAGINATION_PER_QUESTION, SCORING_WITH_ANSWERS, STATUS_OPEN
from survey.tests.factories import make_option, make_question, make_survey


class TestSurveyBadge(IntegrationTestCase):
	def test_a_badge_already_awarded_cannot_be_deleted(self):
		"""Deleting a `Survey Badge` that has already gone out would leave
		`Survey Badge Award` rows pointing at nothing."""
		badge = frappe.get_doc(
			{"doctype": "Survey Badge", "badge_name": frappe.generate_hash(length=8)}
		).insert(ignore_permissions=True)

		survey = make_survey(
			pagination=PAGINATION_PER_QUESTION,
			scoring_type=SCORING_WITH_ANSWERS,
			passing_score=50,
			is_certification=1,
			login_required=1,
			give_badge=1,
			badge=badge.name,
		)
		question = make_question(survey, question_type="Single Choice")
		right = make_option(question, "Right", is_correct=1, score=10)

		# Publish only once the question exists — `question_count` is derived
		# from the questions present at save time.
		survey.reload()
		survey.status = STATUS_OPEN
		survey.save(ignore_permissions=True)

		from survey.api import player

		token = player.start(survey.access_token)["response_token"]
		state = player.begin(survey.access_token, token)
		player.submit_page(
			survey.access_token, token, state["page"]["id"], {question.name: {"value": right.name}}
		)

		self.assertRaises(frappe.ValidationError, badge.delete)
