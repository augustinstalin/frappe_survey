# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""One row per invited respondent.

Created (or reused) exclusively through `survey.api.invites.send_invites` —
not something a Survey Manager fills in by hand, though they may look at the
list. `invite_token` is the secret in the personal link; `response` is set
the moment the invitee starts, by `survey.api.player.start_via_invite`, so a
re-sent reminder and a resumed attempt both resolve to the same response.
"""

import frappe
from frappe.model.document import Document

from survey.utils.tokens import generate_token


class SurveyInvite(Document):
	def before_insert(self):
		if not self.invite_token:
			self.invite_token = generate_token()

	def validate(self):
		if frappe.db.exists(
			"Survey Invite",
			{"survey": self.survey, "email": self.email, "name": ["!=", self.name or ""]},
		):
			frappe.throw(
				frappe._("{0} has already been invited to this survey.").format(self.email)
			)
