"""Comparing answers across the waves of a `Recurring` survey's series.

A `series` (`Survey.series`) groups every wave of the same recurring survey;
`Survey Question.comparison_key` links "the same" question across those
waves even when its wording changed slightly (see `Survey.duplicate_to_next_
wave`, which is what carries the key forward). This module joins the two:
given a series and a key, it returns one row per wave, in `wave_date` order —
which is the whole feature, whether the series has 2 annual waves or a dozen
quarterly ones (see the module docstring in `survey/survey/page/survey_
comparison/survey_comparison.js` for why the report shape doesn't change
with the cadence).

Desk-only, same as `survey.api.reports` — a Survey Manager/User looking at
their own data, never guest-callable.
"""

import frappe

from survey.constants import CHOICE_TYPES, DIRECTLY_SCORABLE_TYPES, SURVEY_TYPE_RECURRING


@frappe.whitelist()
def list_series() -> list[str]:
	"""Every distinct series that has at least one Recurring wave — what the
	comparison page's series picker offers, since `series` is a plain string
	field rather than its own doctype (see the plan: nothing else is worth
	attaching to "the concept of this recurring survey" beyond its name)."""
	frappe.has_permission("Survey", "read", throw=True)

	rows = frappe.get_all(
		"Survey",
		filters={"survey_type": SURVEY_TYPE_RECURRING, "series": ["is", "set"]},
		fields=["series"],
		group_by="series",
		order_by="series asc",
	)
	return [row.series for row in rows]


@frappe.whitelist()
def get_series_waves(series: str) -> list[dict]:
	"""Every wave of `series`, oldest first."""
	frappe.has_permission("Survey", "read", throw=True)

	return frappe.get_all(
		"Survey",
		filters={"series": series, "survey_type": SURVEY_TYPE_RECURRING},
		fields=["name", "title", "wave_label", "wave_date"],
		order_by="wave_date asc",
	)


@frappe.whitelist()
def list_comparison_keys(series: str) -> list[dict]:
	"""Every comparison key in use anywhere in the series, one representative
	title each (whichever wave happens to be read first — the title is only
	there to make the picker readable, not to be authoritative)."""
	frappe.has_permission("Survey", "read", throw=True)

	waves = {row.name for row in get_series_waves(series)}
	if not waves:
		return []

	questions = frappe.get_all(
		"Survey Question",
		filters={"survey": ["in", list(waves)], "comparison_key": ["is", "set"]},
		fields=["comparison_key", "title"],
		order_by="creation asc",
	)

	seen: dict[str, str] = {}
	for row in questions:
		seen.setdefault(row.comparison_key, row.title)

	return [{"comparison_key": key, "title": title} for key, title in seen.items()]


@frappe.whitelist()
def get_comparison_data(series: str, comparison_key: str) -> dict:
	"""One row per wave: that wave's matching question and its answers.

	A wave with no question carrying this key (it hadn't been introduced
	yet, or was dropped later) is included with `question: None` rather than
	skipped — an honest gap in the trend line is more useful than a silently
	shortened one.
	"""
	frappe.has_permission("Survey", "read", throw=True)

	waves = get_series_waves(series)
	rows = []

	for wave in waves:
		question = frappe.db.get_value(
			"Survey Question",
			{"survey": wave.name, "comparison_key": comparison_key},
			["name", "title", "question_type", "is_scored"],
			as_dict=True,
		)

		row = {
			"survey": wave.name,
			"survey_title": wave.title,
			"wave_label": wave.wave_label,
			"wave_date": wave.wave_date,
			"question": None,
			"question_title": None,
			"distribution": [],
			"average_score": None,
			"response_count": 0,
		}

		if question:
			row["question"] = question.name
			row["question_title"] = question.title
			row.update(_answers_for(wave.name, question))

		rows.append(row)

	return {"comparison_key": comparison_key, "waves": rows}


def _answers_for(survey: str, question: dict) -> dict:
	"""The relevant summary for one wave's matching question: an answer
	distribution for a choice question, an average for a directly-scorable
	one, nothing extra for free text (there is no ratio to show)."""
	base_filters = {"survey": survey, "docstatus": 1, "is_test": 0}
	response_count = frappe.db.count("Survey Response", base_filters)

	if question.question_type in CHOICE_TYPES:
		counted = frappe.get_all(
			"Survey Response Answer",
			filters={
				"question": question.name,
				"answer_type": "Option",
				"parent": ["in", frappe.get_all("Survey Response", filters=base_filters, pluck="name")],
			},
			fields=["selected_option"],
		)
		totals: dict[str, int] = {}
		for row in counted:
			totals[row.selected_option] = totals.get(row.selected_option, 0) + 1

		total = sum(totals.values()) or 1
		labels = {
			r.name: r.label
			for r in frappe.get_all(
				"Survey Question Option", filters={"name": ["in", list(totals)]}, fields=["name", "label"]
			)
		}
		distribution = [
			{
				"option": name,
				"label": labels.get(name, name),
				"count": count,
				"percentage": round(count / total * 100, 1),
			}
			for name, count in totals.items()
		]
		return {"distribution": distribution, "response_count": response_count}

	if question.is_scored and question.question_type in DIRECTLY_SCORABLE_TYPES:
		scored = frappe.get_all("Survey Response", filters=base_filters, fields=["score_percentage"])
		average = round(sum(r.score_percentage or 0 for r in scored) / len(scored), 1) if scored else None
		return {"average_score": average, "response_count": response_count}

	return {"response_count": response_count}
