"""Scheduled jobs.

Registered in `hooks.py` now so the contract is visible, but the bodies land
with the phases that own them. Each is a no-op until then rather than a
missing attribute, so the scheduler does not error on an incomplete install.
"""

import frappe
from frappe.utils import now_datetime, today

from survey.constants import RESPONSE_COMPLETED, STATUS_CLOSED, STATUS_OPEN


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

	TODO(phase-6): decide per survey whether an expired response is submitted
	with the answers given so far (assessments: yes, the time ran out) or
	cancelled (invitations that were never started). For now it only handles
	the unambiguous case: a deadline that has passed on an untouched response.
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

	if stale:
		frappe.db.commit()


def send_invite_reminders():
	"""TODO(phase-6): nudge invitees who have not started before the deadline."""


def cleanup_abandoned_responses():
	"""TODO(phase-6): delete untouched public responses older than N days.

	A public survey creates a response record every time somebody lands on the
	link, so this table grows without bound. Odoo has the same problem and no
	answer to it.
	"""
