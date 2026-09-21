"""The public survey page.

Serves `/s/<token>`. The first paint is rendered server-side so the
respondent sees the survey's title and intro immediately (and so the page
says something useful without JavaScript); everything after that is driven by
the player against `survey.api.player`.

The bootstrap payload is the same shape `get_state` returns, so the client has
no special case for its first render.
"""

import json

import frappe

from survey.api import player
from survey.player import serializers
from survey.player.access import SurveyAccessError, resolve

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.no_header = True
	context.no_breadcrumbs = True
	context.no_sidebar = True

	token = frappe.form_dict.get("token")
	response_token = frappe.form_dict.get("r") or player.get_response_token_from_cookie(token or "")

	context.survey_token = token
	context.bootstrap = get_bootstrap(token, response_token)
	context.bootstrap_json = encode_bootstrap(context.bootstrap)

	survey = context.bootstrap.get("survey") or {}
	context.title = survey.get("title") or frappe._("Survey")
	context.background_image = context.bootstrap.get("background_image")

	return context


def encode_bootstrap(payload: dict) -> str:
	"""Serialise the payload for embedding in a `<script>` tag.

	Frappe's Jinja environment does not autoescape, so a survey description
	containing the literal text `</script>` would otherwise close the tag and
	let whatever follows run as markup. Escaping `<` (and the line separators
	that are legal in JSON but not in JavaScript string literals) makes the
	payload inert without changing what `JSON.parse` sees.
	"""
	encoded = json.dumps(payload, default=str)
	return (
		encoded.replace("<", "\\u003c")
		.replace("\u2028", "\\u2028")
		.replace("\u2029", "\\u2029")
	)


def get_bootstrap(survey_token: str | None, response_token: str | None) -> dict:
	"""The first screen, resolved server-side.

	A failure here is not an exception: an expired link or a closed survey is
	an ordinary outcome that deserves a proper page, not a 500.
	"""
	if not survey_token:
		return serializers.serialize_error(
			"survey_missing", frappe._("This survey link is not valid.")
		)

	try:
		access = resolve(survey_token, response_token, require_response=False)
	except SurveyAccessError as error:
		return serializers.serialize_error(error.code, str(error))

	return player.get_state_payload(access)
