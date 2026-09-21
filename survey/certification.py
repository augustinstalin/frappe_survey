# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""Everything that happens because a response passed a certification survey:
the badge award, the certificate email, and the certificate download itself.

Kept out of `Survey Response`'s own controller on purpose (see the comment on
`on_submit` there) — this is wired in from `hooks.py`'s `doc_events`, the one
place later phases are meant to append to.

Security model matches the rest of the public player: a certificate is
reached through the *response's* access token, resolved by
`player.access.resolve`, and then everything runs with
`ignore_permissions`/`ignore_print_permissions`. Frappe's own print
permission check would not do the right thing here — an anonymous response's
`owner` is always "Guest", so any guest visitor would coincidentally pass it
for *any* other guest's response. The token is the only thing that actually
distinguishes one respondent from another, exactly as it is everywhere else
in this app.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import flt, formatdate, now_datetime

from survey.constants import SCORING_TYPES_REVEALING_ANSWERS
from survey.player.access import SurveyAccessError, resolve

CERTIFICATE_PRINT_FORMAT = "Survey Certificate"

#: `Survey.certificate_layout` is "<Family> <Colour>" (e.g. "Modern Purple").
#: The print format reads both halves as CSS classes on the body.
_DEFAULT_LAYOUT = ("modern", "purple")


# ----------------------------------------------------------------------
# doc_events
# ----------------------------------------------------------------------


def on_response_submit(doc, method=None):
	"""`Survey Response.on_submit`. A no-op for anything that is not a passed,
	non-test attempt at a certification survey."""
	survey = frappe.get_cached_doc("Survey", doc.survey)
	if not survey.is_certification or doc.is_test or not doc.passed:
		return

	award_badge(doc, survey)
	send_certificate_email(doc, survey)


def on_response_cancel(doc, method=None):
	revoke_badge(doc)


# ----------------------------------------------------------------------
# Badge
# ----------------------------------------------------------------------


def award_badge(response, survey=None):
	"""Create the one `Survey Badge Award` row for this response, if due.

	Idempotent: rescoring or any other path that could call this twice must
	not hand out two badges. There is no unique index doing that job for
	us here — `Survey Badge Award.response` is unique, so a second insert
	would simply fail loudly rather than duplicate silently, but checking
	first keeps this a quiet no-op instead of an error a caller has to
	swallow.
	"""
	survey = survey or frappe.get_cached_doc("Survey", response.survey)
	if not (survey.give_badge and survey.badge):
		return

	if frappe.db.exists("Survey Badge Award", {"response": response.name}):
		return

	frappe.get_doc(
		{
			"doctype": "Survey Badge Award",
			"badge": survey.badge,
			"survey": survey.name,
			"response": response.name,
			"user": response.user,
			"contact": response.contact,
			"awarded_on": now_datetime(),
		}
	).insert(ignore_permissions=True)


def revoke_badge(response):
	"""`Survey Response.on_cancel`. A cancelled result never earned anything."""
	frappe.db.delete("Survey Badge Award", {"response": response.name})


# ----------------------------------------------------------------------
# Certificate email
# ----------------------------------------------------------------------


def send_certificate_email(response, survey=None):
	"""Email the certificate, if the survey has a template configured and the
	respondent has an address to send it to.

	Both are optional settings, and their absence is not an error: not every
	certification survey wants an automatic email, and an anonymous
	respondent who never gave an email address has nowhere for one to go.

	A PDF render or a mail-queue problem must not fail the submission that
	triggered it — the response is already `docstatus = 1` by the time this
	runs, and undoing that over an email failure would be worse than losing
	the email.
	"""
	survey = survey or frappe.get_cached_doc("Survey", response.survey)
	if not survey.certificate_email_template or not response.email:
		return

	try:
		attachment = frappe.attach_print(
			"Survey Response",
			response.name,
			print_format=CERTIFICATE_PRINT_FORMAT,
			doc=response,
		)
		frappe.sendmail(
			recipients=[response.email],
			template=survey.certificate_email_template,
			args={
				"survey": survey,
				"response": response,
				"recipient_name": response.nickname or response.email,
			},
			attachments=[attachment],
			reference_doctype="Survey Response",
			reference_name=response.name,
		)
	except Exception:
		frappe.log_error(
			title="Survey certificate email failed",
			message=frappe.get_traceback(),
		)


# ----------------------------------------------------------------------
# Certificate content
# ----------------------------------------------------------------------


def build_certificate_context(response) -> dict:
	"""Everything the `Survey Certificate` print format reads off `doc`.

	Called from `Survey Response.before_print`, which both the direct
	download below and `send_certificate_email`'s `attach_print` route
	through — so this is computed in exactly one place for both.
	"""
	survey = frappe.get_cached_doc("Survey", response.survey)
	family, _sep, colour = (survey.certificate_layout or "").lower().partition(" ")
	if not colour:
		family, colour = _DEFAULT_LAYOUT

	reveals_answers = survey.scoring_type in SCORING_TYPES_REVEALING_ANSWERS

	return {
		"survey_title": survey.title,
		"layout_family": family,
		"layout_colour": colour,
		"recipient_name": response.nickname or _("Guest"),
		"issue_date": formatdate(response.completed_on) if response.completed_on else "",
		"certificate_number": response.name,
		"total_score": flt(response.total_score, 2),
		"score_percentage": flt(response.score_percentage, 2),
		"passing_score": flt(survey.passing_score, 2),
		"passed": bool(response.passed),
		"section_breakdown": response.get_section_breakdown() if reveals_answers else [],
		"is_test": bool(response.is_test),
	}


# ----------------------------------------------------------------------
# Availability + download
# ----------------------------------------------------------------------


def is_certificate_available(survey, response) -> bool:
	"""Whether *this* response has earned a certificate to download.

	A response that has not passed produces no PDF at all — Odoo renders a
	"did not pass" variant of the certificate; this build does not, on the
	view that a document titled "Certificate" handed to someone who failed is
	the wrong artifact regardless of its wording. The done screen shows the
	score either way; only a pass adds a download link.
	"""
	return bool(
		survey.is_certification
		and response
		and response.docstatus == 1
		and response.passed
		and not response.is_test
	)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=20, seconds=60 * 60)
def download_certificate(survey_token: str, response_token: str) -> None:
	"""Stream the certificate PDF for one response.

	`allow_closed=True`: a survey that has since closed must not take away a
	certificate someone already earned while it was open.
	"""
	try:
		access = resolve(
			survey_token, response_token, require_response=True, allow_closed=True
		)
	except SurveyAccessError as error:
		frappe.throw(str(error), frappe.PermissionError)

	survey, response = access.survey, access.response

	if not is_certificate_available(survey, response):
		frappe.throw(_("No certificate is available for this response."), frappe.PermissionError)

	# See the module docstring: this app's own token gate just did the
	# authorising, and Frappe's standard print permission check would
	# actively get this wrong for an anonymous response.
	frappe.flags.ignore_print_permissions = True
	try:
		pdf = frappe.get_print(
			"Survey Response",
			response.name,
			CERTIFICATE_PRINT_FORMAT,
			doc=response,
			as_pdf=True,
		)
	finally:
		frappe.flags.ignore_print_permissions = False

	frappe.local.response.filename = f"{response.name}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"
