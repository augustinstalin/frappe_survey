# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

"""Phase 6: invitations, attempt limiting, and `retry`."""

import frappe
from frappe.tests import IntegrationTestCase

from survey.api import invites, player
from survey.constants import STATUS_OPEN
from survey.player.access import SurveyAccessError
from survey.tests.factories import make_question, make_survey


def open_survey(**values):
	values.setdefault("status", "Draft")
	return make_survey(**values)


def publish(survey):
	survey.reload()
	survey.status = STATUS_OPEN
	survey.save(ignore_permissions=True)
	return survey


def finish(survey, response_token):
	"""Walk a one-question survey to completion and return the closing payload."""
	player.begin(survey.access_token, response_token)
	page = player.get_state(survey.access_token, response_token)["page"]
	return player.submit_page(
		survey.access_token,
		response_token,
		page["id"],
		{page["questions"][0]["id"]: {"value": "Ada"}},
	)


class TestAttemptLimiting(IntegrationTestCase):
	"""`Survey.validate_timing_and_attempts` only leaves `limit_attempts` on
	for a survey that requires login or is invite-only — so every test here
	needs a stable identity, not an anonymous public link."""

	def setUp(self):
		self.user = "Administrator"
		frappe.set_user(self.user)
		self.survey = open_survey(login_required=1, limit_attempts=1, attempts_limit=1)
		make_question(self.survey, question_type="Single Line Text", title="Name?")
		publish(self.survey)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_first_attempt_is_allowed(self):
		result = player.start(self.survey.access_token)
		self.assertIn("response_token", result)
		self.assertNotEqual(result.get("state"), "error")

	def test_a_second_attempt_is_refused_once_the_first_is_used_up(self):
		token = player.start(self.survey.access_token)["response_token"]
		finish(self.survey, token)

		# A brand new `start` call (no token) must count the completed attempt
		# above and refuse another.
		result = player.start(self.survey.access_token)
		self.assertEqual(result["state"], "error")
		self.assertEqual(result["code"], "no_attempts_left")

	def test_an_in_progress_attempt_does_not_itself_count_as_used_up(self):
		# Starting (but not finishing) must not immediately lock the survey
		# out for the very visitor who is still on it — resuming goes through
		# `start` with the same response token and must keep working.
		token = player.start(self.survey.access_token)["response_token"]
		result = player.start(self.survey.access_token, response_token=token)
		self.assertNotEqual(result.get("state"), "error")


class TestRetry(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.survey = open_survey(login_required=1, limit_attempts=1, attempts_limit=2)
		make_question(self.survey, question_type="Single Line Text", title="Name?")
		publish(self.survey)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_retry_starts_a_fresh_response_after_completion(self):
		first_token = player.start(self.survey.access_token)["response_token"]
		finish(self.survey, first_token)

		result = player.retry(self.survey.access_token, first_token)
		self.assertNotEqual(result.get("state"), "error")
		self.assertNotEqual(result["response_token"], first_token)

	def test_retry_is_refused_while_the_attempt_is_still_in_progress(self):
		token = player.start(self.survey.access_token)["response_token"]

		result = player.retry(self.survey.access_token, token)
		self.assertEqual(result["state"], "error")
		self.assertEqual(result["code"], "not_allowed")

	def test_retry_is_refused_once_attempts_are_used_up(self):
		frappe.db.set_value("Survey", self.survey.name, "attempts_limit", 1)

		token = player.start(self.survey.access_token)["response_token"]
		finish(self.survey, token)

		result = player.retry(self.survey.access_token, token)
		self.assertEqual(result["state"], "error")
		self.assertEqual(result["code"], "no_attempts_left")


class TestInvites(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.survey = open_survey()
		make_question(self.survey, question_type="Single Line Text", title="Name?")
		publish(self.survey)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_sending_an_invite_creates_a_pending_row(self):
		invites.send_invites(self.survey.name, [{"email": "invitee@example.com"}])

		invite = frappe.get_doc(
			"Survey Invite", {"survey": self.survey.name, "email": "invitee@example.com"}
		)
		self.assertTrue(invite.invite_token)
		# No `invite_email_template` is configured on this survey, so nothing
		# actually sends — the row still exists and stays Pending.
		self.assertEqual(invite.status, "Pending")

	def test_sending_to_the_same_address_twice_reuses_one_invite(self):
		invites.send_invites(self.survey.name, [{"email": "invitee@example.com"}])
		invites.send_invites(self.survey.name, [{"email": "invitee@example.com"}])

		self.assertEqual(
			frappe.db.count(
				"Survey Invite", {"survey": self.survey.name, "email": "invitee@example.com"}
			),
			1,
		)

	def test_a_guest_cannot_send_invites(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			invites.send_invites(self.survey.name, [{"email": "invitee@example.com"}])

	def test_starting_from_an_invite_creates_and_links_a_response(self):
		invites.send_invites(self.survey.name, [{"email": "invitee@example.com"}])
		invite = frappe.get_doc(
			"Survey Invite", {"survey": self.survey.name, "email": "invitee@example.com"}
		)

		frappe.set_user("Guest")
		result = player.start_via_invite(invite.invite_token)
		self.assertNotEqual(result.get("state"), "error")

		invite.reload()
		self.assertEqual(invite.status, "Started")
		self.assertTrue(invite.response)
		self.assertEqual(
			frappe.db.get_value("Survey Response", invite.response, "email"), "invitee@example.com"
		)

	def test_reopening_the_same_invite_link_reuses_the_response(self):
		invites.send_invites(self.survey.name, [{"email": "invitee@example.com"}])
		invite = frappe.get_doc(
			"Survey Invite", {"survey": self.survey.name, "email": "invitee@example.com"}
		)

		frappe.set_user("Guest")
		first = player.start_via_invite(invite.invite_token)
		second = player.start_via_invite(invite.invite_token)

		self.assertEqual(first["response_token"], second["response_token"])

	def test_an_unknown_invite_token_is_rejected(self):
		frappe.set_user("Guest")
		result = player.start_via_invite("not-a-real-token")
		self.assertEqual(result["state"], "error")
		self.assertEqual(result["code"], "response_missing")
