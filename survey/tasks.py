"""Scheduled jobs.

Registered in `hooks.py`. Each commits its own batch on the way out — the
one place in this app `frappe.db.commit()` belongs (see `TODO.md`'s note on
why it must never appear in a document method): a long-running job that gets
interrupted should keep whatever partial progress it already made rather
than losing it to a rollback.
"""

import frappe
from frappe.utils import add_days, now_datetime, today

from survey.constants import RESPONSE_COMPLETED, STATUS_CLOSED, STATUS_OPEN

#: How many days ahead of `Survey.close_on` an unopened invite gets a nudge.
INVITE_REMINDER_LOOKAHEAD_DAYS = 3

#: A respondent gets at most this many reminder emails per invite.
MAX_INVITE_REMINDERS = 2

#: An untouched (status "New") public response older than this is dead
#: weight — nobody is coming back to a link they never opened.
ABANDONED_RESPONSE_AGE_DAYS = 30


def close_expired_surveys():
	"""Close surveys whose `close_on` date has passed.

	Odoo has no scheduled expiry at all — surveys stay open until somebody
	archives them by hand. This is a deliberate addition.
	"""
	expired = frappe.get_all(
		"Survey",
		filters={"status": STATUS_OPEN, "close_on": ["<", today()]},
		pluck="name",
	)
	for name in expired:
		doc = frappe.get_doc("Survey", name)
		doc.status = STATUS_CLOSED
		doc.flags.ignore_open_checks = True
		doc.save(ignore_permissions=True)

	if expired:
		frappe.db.commit()


def close_expired_responses():
	"""Submit or void responses that ran past their deadline.

	An untouched response (never past "New") is cancelled — nobody answered
	anything, so there is nothing to score. An in-progress response is
	submitted with whatever answers it has *if it has any*; the time ran out,
	but partial answers on an assessment are still a real attempt and should
	go through the normal scoring/certification path like any other
	submission. One that reached "In Progress" (`started_on` set, by opening
	the survey) but never actually answered anything is cancelled the same as
	an untouched one — there is still nothing to score.
	"""
	stale = frappe.get_all(
		"Survey Response",
		filters={
			"docstatus": 0,
			"deadline": ["<", now_datetime()],
			"status": ["!=", RESPONSE_COMPLETED],
		},
		fields=["name", "status"],
		limit=500,
	)

	for row in stale:
		if row.status == "New":
			frappe.db.set_value("Survey Response", row.name, "docstatus", 2, update_modified=False)
			continue

		doc = frappe.get_doc("Survey Response", row.name)
		if not doc.answers:
			frappe.db.set_value("Survey Response", row.name, "docstatus", 2, update_modified=False)
			continue

		doc.flags.ignore_permissions = True
		try:
			doc.submit()
		except Exception:
			# One bad response must not stop the rest of the batch; it stays
			# `docstatus=0` and is picked up again next run.
			frappe.log_error(
				title="Failed to auto-submit an expired survey response",
				message=frappe.get_traceback(),
			)

	if stale:
		frappe.db.commit()


def send_invite_reminders():
	"""Nudge invitees who have not started, as their survey's deadline nears."""
	from survey.api.invites import send_invite_email

	cutoff = add_days(today(), INVITE_REMINDER_LOOKAHEAD_DAYS)

	candidates = frappe.get_all(
		"Survey Invite",
		filters={"status": ["in", ("Pending", "Sent")], "reminder_count": ["<", MAX_INVITE_REMINDERS]},
		fields=["name", "survey"],
		limit=1000,
	)
	if not candidates:
		return

	# `close_on` is optional; a survey without one never has an imminent
	# deadline to remind anyone about, so only surveys that both have a close
	# date and it falls within the lookahead window are "due".
	due_surveys = set(
		frappe.get_all(
			"Survey",
			filters={
				"name": ["in", list({row.survey for row in candidates})],
				"status": STATUS_OPEN,
				# NULL never satisfies "<=", so a survey without a close date
				# is naturally excluded rather than needing a separate check.
				"close_on": ["<=", cutoff],
			},
			pluck="name",
		)
	)
	if not due_surveys:
		return

	reminded = 0
	for row in candidates:
		if row.survey not in due_surveys:
			continue

		invite = frappe.get_doc("Survey Invite", row.name)
		survey_doc = frappe.get_cached_doc("Survey", invite.survey)
		if send_invite_email(survey_doc, invite):
			invite.db_set(
				{
					"reminder_count": (invite.reminder_count or 0) + 1,
					"last_reminded_on": now_datetime(),
				}
			)
			reminded += 1

	if reminded:
		frappe.db.commit()


def cleanup_abandoned_responses():
	"""Delete untouched public responses older than `ABANDONED_RESPONSE_AGE_DAYS`.

	A public survey creates a response record every time somebody lands on
	the link, so this table grows without bound. Only ever removes rows that
	never got past "New" (no answers, `started_on` unset) — anything with a
	real attempt on it is left alone regardless of age. Deletes with plain
	`frappe.db.delete`, the same pattern `purge_test_responses` uses: these
	are draft rows nobody links to, so routing them through `delete_doc` for
	a cancel-first workflow buys nothing.
	"""
	cutoff = add_days(now_datetime(), -ABANDONED_RESPONSE_AGE_DAYS)

	names = frappe.get_all(
		"Survey Response",
		filters={"status": "New", "docstatus": 0, "creation": ["<", cutoff]},
		pluck="name",
		limit=5000,
	)
	if not names:
		return

	for child in ("Survey Response Answer", "Survey Response Question"):
		frappe.db.delete(child, {"parenttype": "Survey Response", "parent": ["in", names]})
	frappe.db.delete("Survey Response", {"name": ["in", names]})

	frappe.db.commit()
