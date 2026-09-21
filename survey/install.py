"""Post-install setup: roles, workspace defaults and sample content."""

import frappe

from survey.constants import ROLE_MANAGER, ROLE_RESPONDENT, ROLE_USER

ROLES = (
	(ROLE_MANAGER, "Full access to every survey, response and setting."),
	(ROLE_USER, "Builds and runs surveys they are allowed to work on."),
	(ROLE_RESPONDENT, "A signed-in respondent. Reads only their own responses."),
)


def after_install():
	create_roles()
	frappe.db.commit()


def create_roles():
	for name, description in ROLES:
		if frappe.db.exists("Role", name):
			continue

		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": name,
				"desk_access": 0 if name == ROLE_RESPONDENT else 1,
				"description": description,
			}
		).insert(ignore_permissions=True)
