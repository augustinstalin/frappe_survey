"""Sending survey invitations.

Desk-only (a Survey Manager sending links out), unlike everything in
`survey.api.player`, which is guest-callable. The invitee's own entry point
is `survey.api.player.start_via_invite` / the `?invite=` link handled by
`survey/www/s.py` — nothing here is reachable by them.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime, validate_email_address


@frappe.whitelist()
@rate_limit(limit=20, seconds=60 * 60)
def send_invites(survey: str, recipients: list | str) -> dict:
	"""Get-or-create a `Survey Invite` per recipient and email each one its link.

	`recipients` is a list of `{"email": ..., "contact": None, "user": None}`
	dicts (or a JSON-encoded string of the same, since this is normally called
	from a desk dialog). Re-sending to an address already invited reuses the
	existing invite (and its `invite_token`) rather than creating a second one
	— `Survey Invite.validate` already refuses a duplicate `survey`+`email`
	pair, so this is where that idempotency is actually exercised.
	"""
	frappe.has_permission("Survey", "write", survey, throw=True)
	survey_doc = frappe.get_doc("Survey", survey)

	recipients = _parse_recipients(recipients)
	if not recipients:
		frappe.throw(_("No recipients given."))

	sent, skipped = [], []

	for recipient in recipients:
		email = (recipient.get("email") or "").strip()
		if not email:
			continue
		try:
			validate_email_address(email, throw=True)
		except frappe.InvalidEmailAddressError:
			skipped.append({"email": email, "reason": _("Not a valid email address.")})
			continue

		invite = _get_or_create_invite(survey_doc, email, recipient.get("contact"), recipient.get("user"))
		if send_invite_email(survey_doc, invite):
			sent.append(email)
		else:
			skipped.append({"email": email, "reason": _("No invite email template is set on the survey.")})

	return {"sent": sent, "skipped": skipped}


def _parse_recipients(recipients) -> list[dict]:
	import json

	if isinstance(recipients, str):
		try:
			recipients = json.loads(recipients)
		except (ValueError, TypeError):
			# Tolerate a plain textarea: one address per line/comma.
			recipients = [
				{"email": part.strip()}
				for part in recipients.replace(",", "\n").splitlines()
				if part.strip()
			]

	if isinstance(recipients, dict):
		recipients = [recipients]

	return [r for r in (recipients or []) if isinstance(r, dict)]


def _get_or_create_invite(survey_doc, email: str, contact: str | None, user: str | None):
	name = frappe.db.get_value("Survey Invite", {"survey": survey_doc.name, "email": email}, "name")
	if name:
		return frappe.get_doc("Survey Invite", name)

	invite = frappe.get_doc(
		{
			"doctype": "Survey Invite",
			"survey": survey_doc.name,
			"email": email,
			"contact": contact,
			"user": user,
		}
	)
	invite.insert(ignore_permissions=True)
	return invite


def send_invite_email(survey_doc, invite) -> bool:
	"""Email one invite. Returns whether it actually sent one.

	No template configured is not an error — same contract as
	`certification.send_certificate_email`: an optional setting whose absence
	just means no automatic email for this survey.
	"""
	if not survey_doc.invite_email_template:
		return False

	invite_url = frappe.utils.get_url(f"/s/{survey_doc.access_token}?invite={invite.invite_token}")

	try:
		frappe.sendmail(
			recipients=[invite.email],
			template=survey_doc.invite_email_template,
			args={"survey": survey_doc, "invite": invite, "invite_url": invite_url},
			reference_doctype="Survey Invite",
			reference_name=invite.name,
		)
	except Exception:
		frappe.log_error(
			title="Survey invite email failed", message=frappe.get_traceback()
		)
		return False

	updates = {"sent_on": now_datetime()}
	if invite.status == "Pending":
		# Once they've started or finished, re-sending (a reminder) must not
		# regress the status back to "Sent".
		updates["status"] = "Sent"
	invite.db_set(updates)
	return True
