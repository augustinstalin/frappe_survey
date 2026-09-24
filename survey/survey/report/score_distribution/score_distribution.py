# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

"""How respondents' scores bucket across a scored survey.

Buckets `Survey Response.score_percentage` into fixed-width ranges. Only
meaningful for a survey with scoring turned on — an unscored survey has
nothing in `score_percentage` and this report has nothing to show it.
"""

import frappe
from frappe import _

#: Width of each bucket, in percentage points. 10 gives ten rows (0–10%,
#: 10–20%, ... 90–100%), which reads well as a bar chart without configuring
#: anything per survey.
BUCKET_WIDTH = 10


def execute(filters=None):
	filters = filters or {}
	if not filters.get("survey"):
		frappe.throw(_("Pick a survey."))

	survey = frappe.db.get_value("Survey", filters["survey"], ["scoring_type", "passing_score"], as_dict=True)
	if not survey or survey.scoring_type == "No Scoring":
		frappe.throw(_("This survey has no scoring enabled."))

	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "bucket", "label": _("Score Range"), "fieldtype": "Data", "width": 140},
		{"fieldname": "count", "label": _("Responses"), "fieldtype": "Int", "width": 100},
		{"fieldname": "passed_count", "label": _("Passed"), "fieldtype": "Int", "width": 100},
		{"fieldname": "average_score", "label": _("Average Score %"), "fieldtype": "Percent", "width": 140},
	]


def get_data(filters: dict) -> list[dict]:
	response_filters = {"survey": filters["survey"], "docstatus": 1, "is_test": 0}
	if filters.get("passed") == "Yes":
		response_filters["passed"] = 1
	elif filters.get("passed") == "No":
		response_filters["passed"] = 0

	rows = frappe.get_all(
		"Survey Response",
		filters=response_filters,
		fields=["score_percentage", "passed"],
	)
	if not rows:
		return []

	buckets: dict[int, dict] = {}
	for row in rows:
		percentage = row.score_percentage or 0
		# 100% belongs in the top bucket rather than spilling into an
		# eleventh "100-110" one of its own.
		index = min(int(percentage // BUCKET_WIDTH), (100 // BUCKET_WIDTH) - 1)
		bucket = buckets.setdefault(index, {"count": 0, "passed_count": 0, "total_score": 0.0})
		bucket["count"] += 1
		bucket["passed_count"] += 1 if row.passed else 0
		bucket["total_score"] += percentage

	data = []
	for index in sorted(buckets):
		bucket = buckets[index]
		low, high = index * BUCKET_WIDTH, (index + 1) * BUCKET_WIDTH
		data.append(
			{
				"bucket": f"{low}–{high}%",
				"count": bucket["count"],
				"passed_count": bucket["passed_count"],
				"average_score": round(bucket["total_score"] / bucket["count"], 1),
			}
		)

	return data
