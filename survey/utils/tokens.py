"""Token generation for public survey access.

Both `Survey.access_token` and `Survey Response.access_token` are the *only*
thing standing between an anonymous visitor and the data behind them, so they
are generated with `frappe.generate_hash`, which is backed by `secrets`.
"""

import frappe

from survey.constants import TOKEN_LENGTH


def generate_token(length: int = TOKEN_LENGTH) -> str:
	"""Return a cryptographically random, URL-safe token."""
	return frappe.generate_hash(length=length)


def mask_token(token: str | None) -> str:
	"""Render a token for logs and error messages without leaking it."""
	if not token:
		return ""
	return f"{token[:4]}…{token[-4:]}" if len(token) > 12 else "…"
