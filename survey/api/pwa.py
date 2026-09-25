"""A per-survey web app manifest for `/s/<token>`.

A single static `manifest.json` can't be right for every survey: its
`start_url` has to be the link the respondent actually opened, or "installing"
the survey and reopening it later would land back on the generic, token-less
`/s` page instead of their survey. Frappe already resolves the survey for the
first paint in `www/s.py`, so this borrows that same lookup rather than
re-implementing it, and fails soft (a manifest without a valid survey just
omits `name`/icons rather than 404ing — the browser simply won't offer to
install a broken link).
"""

import frappe

from survey.player.access import SurveyAccessError, resolve

ICON_BASE = "/assets/survey/images/pwa"


@frappe.whitelist(allow_guest=True)
def manifest(token: str | None = None):
	title = frappe._("Survey")

	if token:
		try:
			access = resolve(token, None, require_response=False)
			title = access.survey.title or title
		except SurveyAccessError:
			pass

	# Mutating `frappe.response` directly (rather than `return`ing a dict)
	# skips Frappe's usual `{"message": ...}` envelope for whitelisted
	# methods — a browser fetching this as a web app manifest needs the raw
	# object, not a value nested under `message`.
	frappe.response.update(
		{
			"name": title,
			"short_name": title[:32],
			"description": frappe._("Take a survey — no account required."),
			"start_url": f"/s/{token}" if token else "/s",
			"scope": "/s/",
			"display": "standalone",
			"background_color": "#2563eb",
			"theme_color": "#2563eb",
			"orientation": "portrait-primary",
			"icons": [
				{"src": f"{ICON_BASE}/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
				{"src": f"{ICON_BASE}/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
				{
					"src": f"{ICON_BASE}/icon-maskable-192.png",
					"sizes": "192x192",
					"type": "image/png",
					"purpose": "maskable",
				},
				{
					"src": f"{ICON_BASE}/icon-maskable-512.png",
					"sizes": "512x512",
					"type": "image/png",
					"purpose": "maskable",
				},
			],
		}
	)
