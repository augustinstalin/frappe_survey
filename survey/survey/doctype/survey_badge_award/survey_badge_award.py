# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""Created and deleted only from `survey.certification` — see
`award_badge` / `revoke_badge`. There is deliberately no `validate()` of its
own beyond the field-level `reqd`/`unique` the DocType declares: this is a
log entry, not something anybody edits by hand.
"""

from frappe.model.document import Document


class SurveyBadgeAward(Document):
	pass
