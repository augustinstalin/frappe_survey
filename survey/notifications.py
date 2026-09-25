"""Overrides ERPNext's blanket "open" filter for `Survey Response`.

ERPNext's own `notification_config` hook
(`erpnext.startup.notifications.get_notification_config`) runs for every
installed app's submittable doctypes, not just its own: any doctype with
`is_submittable = 1` that it doesn't explicitly recognise falls into a
generic `{"docstatus": 0}` "open" filter. `Survey Response` is submittable
(so a completed response can be locked from further edits) but has nothing
to do with ERPNext's notion of an "open transaction" — its blue badge on the
Survey form was really just counting draft/test responses, not anything a
survey owner would call "needs attention". Registering our own, empty
config here removes that badge; the plain linked-document count next to it
is untouched.
"""


def get_notification_config():
	return {"for_doctype": {"Survey Response": {}}}
