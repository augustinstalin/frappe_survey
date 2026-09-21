"""Which screen the respondent sees next.

A survey is a flat ordered list of sections and questions. How that list is
cut into pages depends on `Survey.pagination`:

* **All On One Page** — one page holding everything.
* **One Page Per Section** — one page per section; a section with neither
  questions nor a description is skipped entirely.
* **One Page Per Question** — one page per question, plus a standalone page
  for any section that carries a description (so section intros still get
  their moment).

Two things filter the list before it is paginated:

* the respondent's own question set (`predefined_questions`), which is what
  makes randomised surveys stable per person;
* skip logic — a question whose trigger has not been satisfied is not a page,
  and a section whose every question is hidden is not a page either.

Because both filters depend on answers *given so far*, pagination is computed
fresh on each request rather than cached on the response.
"""

from dataclasses import dataclass, field

import frappe

from survey.constants import (
	PAGINATION_ONE_PAGE,
	PAGINATION_PER_QUESTION,
	PAGINATION_PER_SECTION,
)
from survey.survey.doctype.survey_response.survey_response import get_triggering_options_map
from survey.utils.sequencing import sequence_key


@dataclass
class Page:
	"""One screen: a section intro, a single question, or a batch of them."""

	id: str
	kind: str  # "question" | "section" | "all"
	questions: list[str] = field(default_factory=list)
	section: str | None = None


def get_pages(survey, response, include_hidden: bool = False) -> list[Page]:
	"""Every page this respondent could see, in order.

	Hidden questions are excluded, so the length of this list is also the
	honest denominator for the progress bar. (Odoo indexes into the full
	question list instead, which is why its progress bar can jump backwards
	on a survey with skip logic.)

	`include_hidden` keeps questions whose trigger is not currently satisfied.
	It is for saving, not for rendering — see `get_page_for_save`.
	"""
	rows = get_visible_rows(survey, response, include_hidden=include_hidden)
	questions = [row for row in rows if not row.is_section]

	if survey.pagination == PAGINATION_ONE_PAGE:
		if not questions:
			return []
		return [Page(id="all", kind="all", questions=[row.name for row in questions])]

	if survey.pagination == PAGINATION_PER_SECTION:
		return _paginate_by_section(rows)

	return _paginate_by_question(rows)


def _paginate_by_section(rows) -> list[Page]:
	"""One page per section. Questions before the first section get their own.

	A question that sits above every section would otherwise be unreachable,
	so those are collected into a leading page.
	"""
	pages: list[Page] = []

	orphans = [row.name for row in rows if not row.is_section and not row.section]
	if orphans:
		pages.append(Page(id="__intro__", kind="all", questions=orphans))

	for row in rows:
		if not row.is_section:
			continue

		members = [q.name for q in rows if not q.is_section and q.section == row.name]
		if not members and not _has_description(row):
			# An empty section with nothing to say is not a page.
			continue

		pages.append(Page(id=row.name, kind="section", questions=members, section=row.name))

	return pages


def _paginate_by_question(rows) -> list[Page]:
	"""One page per question, with described sections as their own interstitial."""
	pages: list[Page] = []

	for row in rows:
		if row.is_section:
			if _has_description(row):
				pages.append(Page(id=row.name, kind="section", questions=[], section=row.name))
			continue

		pages.append(Page(id=row.name, kind="question", questions=[row.name], section=row.section))

	return pages


def get_visible_rows(survey, response, include_hidden: bool = False) -> list:
	"""The builder list, minus questions this respondent will not be asked.

	Sections survive this filter even when empty; `_paginate_*` decides
	whether an empty section is worth a page, because that answer differs
	between layouts.
	"""
	dealt = set(response.get_question_names()) if response else None
	hidden = set() if include_hidden else (response.get_inactive_questions() if response else set())

	rows = frappe.get_all(
		"Survey Question",
		filters={"survey": survey.name},
		fields=["name", "title", "description", "sequence", "is_section", "section"],
	)
	rows = sorted(rows, key=sequence_key)

	visible = []
	for row in rows:
		if row.is_section:
			visible.append(row)
			continue
		if dealt is not None and row.name not in dealt:
			continue
		if row.name in hidden:
			continue
		visible.append(row)

	return visible


def _has_description(row) -> bool:
	description = (row.get("description") or "").strip()
	# A Text Editor field that has been opened and emptied leaves markup
	# behind rather than an empty string.
	return bool(description) and description not in ("<p></p>", "<p><br></p>", "<div></div>")


# ----------------------------------------------------------------------
# Movement
# ----------------------------------------------------------------------


def get_first_page(survey, response) -> Page | None:
	pages = get_pages(survey, response)
	return pages[0] if pages else None


def get_page(survey, response, page_id: str | None) -> Page | None:
	"""Resolve a page id, falling back to the first page."""
	pages = get_pages(survey, response)
	if not pages:
		return None

	if not page_id:
		return pages[0]

	return next((page for page in pages if page.id == page_id), None)


def get_page_for_save(survey, response, page_id: str | None) -> Page | None:
	"""The same page, but holding every question that structurally belongs to it.

	Skip logic is evaluated against the answers already *stored*, so a
	question unlocked by an answer given on this very page still looks hidden
	when the submission arrives. Resolving the page normally would therefore
	drop that answer on the floor: the respondent sees the question (the
	browser reveals it live), answers it, and the server quietly discards it.

	Saving works from this wider set instead. Anything that is still hidden
	once the page's answers are stored is then removed by
	`persistence.clear_hidden_answers`, so nothing unanswerable survives.
	"""
	pages = get_pages(survey, response, include_hidden=True)

	if not page_id:
		return pages[0] if pages else None

	return next((page for page in pages if page.id == page_id), None)


def get_next_page(survey, response, page_id: str) -> Page | None:
	"""The page after `page_id`, or None when there is nothing left.

	Recomputed against the answers just saved, so an answer that unlocked a
	conditional question makes that question the very next page.
	"""
	pages = get_pages(survey, response)
	index = _index_of(pages, page_id)

	if index is None or index >= len(pages) - 1:
		return None

	return pages[index + 1]


def get_previous_page(survey, response, page_id: str) -> Page | None:
	pages = get_pages(survey, response)
	index = _index_of(pages, page_id)

	if not index:  # None, or 0 — either way there is nothing before it
		return None

	return pages[index - 1]


def is_last_page(survey, response, page_id: str) -> bool:
	"""Whether `page_id` is the final screen.

	Answer-dependent: a page whose options could still unlock a later question
	is not the last page, even when nothing currently follows it. Getting this
	wrong shows "Submit" on a page that turns out to have a successor, which
	is worse than the reverse.
	"""
	if survey.pagination == PAGINATION_ONE_PAGE:
		return True

	pages = get_pages(survey, response)
	index = _index_of(pages, page_id)

	if index is None:
		return False

	if index < len(pages) - 1:
		return False

	return not _page_can_unlock_more(survey, response, page_id)


def _page_can_unlock_more(survey, response, page_id: str) -> bool:
	"""Could an answer on this page reveal a question further down?"""
	triggers = get_triggering_options_map(survey.name)
	if not triggers:
		return False

	page = get_page(survey, response, page_id)
	if not page or not page.questions:
		return False

	options_on_page = set(
		frappe.get_all(
			"Survey Question Option",
			filters={"question": ["in", page.questions], "is_matrix_row": 0},
			pluck="name",
		)
	)
	if not options_on_page:
		return False

	dealt = set(response.get_question_names())
	hidden = response.get_inactive_questions()

	for question, required in triggers.items():
		if question not in dealt or question not in hidden:
			continue
		if required & options_on_page:
			return True

	return False


def _index_of(pages: list[Page], page_id: str) -> int | None:
	for index, page in enumerate(pages):
		if page.id == page_id:
			return index
	return None


def get_progress(survey, response, page_id: str | None) -> dict:
	"""Where the respondent is, for the progress bar.

	Counts pages rather than questions: on a one-question-per-page survey they
	are the same thing, and on the other layouts pages are what the respondent
	actually experiences as progress.
	"""
	pages = get_pages(survey, response)
	total = len(pages)
	index = _index_of(pages, page_id) if page_id else None

	current = (index + 1) if index is not None else 0

	return {
		"current": current,
		"total": total,
		"percent": round((current / total) * 100) if total else 0,
		"mode": survey.progress_display or "Percentage",
	}


# ----------------------------------------------------------------------
# Skipped mandatory questions
#
# With roaming on, validation lets a mandatory question through empty: being
# able to move on and come back is the whole point of roaming, and refusing
# to advance would defeat it. The bargain is that the survey will not *finish*
# with a mandatory question still blank, so somebody has to keep the list —
# that is what these two functions are.
# ----------------------------------------------------------------------


def get_unanswered_mandatory(survey, response) -> set[str]:
	"""Visible mandatory questions with nothing recorded against them.

	A row marked `skipped` counts as nothing recorded: that is exactly what
	the respondent did.
	"""
	rows = get_visible_rows(survey, response)
	mandatory = {
		row.name
		for row in frappe.get_all(
			"Survey Question",
			filters={
				"name": ["in", [r.name for r in rows if not r.is_section]] or [""],
				"mandatory": 1,
				"is_section": 0,
			},
			fields=["name"],
		)
	}
	if not mandatory:
		return set()

	answered = {
		row.question
		for row in response.answers
		if not row.skipped and row.answer_type and row.answer_type != "Comment"
	}

	return mandatory - answered


def get_skipped_pages(survey, response) -> list[Page]:
	"""Every page still holding an unanswered mandatory question, in order.

	Unbounded on purpose: this is the finish-time question — "is the survey
	actually complete?" — and a page the respondent has not reached yet is
	still a reason not to finish.
	"""
	pending = get_unanswered_mandatory(survey, response)
	if not pending:
		return []

	return [page for page in get_pages(survey, response) if pending.intersection(page.questions)]


def get_outstanding_pages(survey, response, page_id: str | None) -> list[Page]:
	"""The same, but only as far as the respondent has actually got.

	The difference matters for anything the respondent *sees*. At the very
	first page nothing has been answered, so `get_skipped_pages` quite
	correctly reports every mandatory question in the survey — which as a
	badge reads "17 questions still need an answer" before they have been
	asked a single one. Telling somebody off for not yet having done something
	is worse than saying nothing.

	So counting stops at the current page, and only opens up to the whole
	survey once they have been all the way through it once
	(`first_submitted`), at which point every outstanding question really is
	one they passed over.
	"""
	pending = get_unanswered_mandatory(survey, response)
	if not pending:
		return []

	pages = get_pages(survey, response)

	if response.first_submitted:
		reached = len(pages)
	else:
		# Exclusive of the current page: they are standing on it, and the
		# question in front of them is not one they have passed over.
		index = _index_of(pages, page_id)
		reached = index if index is not None else len(pages)

	return [page for page in pages[:reached] if pending.intersection(page.questions)]


# ----------------------------------------------------------------------
# Breadcrumb
# ----------------------------------------------------------------------


def get_breadcrumb(survey, response, page_id: str | None) -> list[dict]:
	"""Section-by-section trail, for "One Page Per Section" only.

	The other two layouts have nothing to show: one page has no trail, and one
	page per question would produce a strip of twenty anonymous dots.

	`pending` marks a section that still owes a mandatory answer, so the
	respondent can see where the survey is going to send them back to rather
	than being surprised at the end.
	"""
	if survey.pagination != PAGINATION_PER_SECTION:
		return []

	pages = get_pages(survey, response)
	if len(pages) < 2:
		return []

	# Only sections the respondent has actually been through are marked as
	# owing an answer; see `get_outstanding_pages`.
	pending = {
		question
		for page in get_outstanding_pages(survey, response, page_id)
		for question in page.questions
	} & get_unanswered_mandatory(survey, response)
	current = _index_of(pages, page_id)

	trail = []
	for index, page in enumerate(pages):
		if current is None:
			state = "todo"
		elif index < current:
			state = "done"
		elif index == current:
			state = "current"
		else:
			state = "todo"

		title = _page_title(page, index)

		trail.append(
			{
				"id": page.id,
				"title": title,
				"state": state,
				"pending": bool(pending.intersection(page.questions)),
				# Jumping forward would skip past questions the respondent has
				# not seen, which is not roaming — it is cheating on a scored
				# survey and confusing on any other.
				"can_jump": bool(survey.allow_roaming) and state == "done",
			}
		)

	return trail


def _page_title(page: Page, index: int) -> str:
	if page.section:
		title = frappe.db.get_value("Survey Question", page.section, "title")
		if title:
			return title

	return frappe._("Part {0}").format(index + 1)
