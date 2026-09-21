# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""A badge design. `Survey Badge Award` is the audit trail of who got one.

`survey` is set programmatically by `Survey.validate_certification`, not by
the badge's own form — a badge belongs to at most one survey at a time
(replacing Odoo's goal/challenge/badge machinery with a single link), and the
survey is the side that decides that, the same way `Survey Question.survey`
is never edited from the question form either.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SurveyBadge(Document):
	def on_trash(self):
		if frappe.db.exists("Survey Badge Award", {"badge": self.name}):
			frappe.throw(
				_(
					"{0} has already been awarded to at least one respondent and cannot be "
					"deleted. Unlink it from its survey first if it should stop being awarded."
				).format(self.name)
			)
