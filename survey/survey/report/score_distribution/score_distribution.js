// Copyright (c) 2026, Bosco Soft Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Score Distribution"] = {
	filters: [
		{
			fieldname: "survey",
			label: __("Survey"),
			fieldtype: "Link",
			options: "Survey",
			reqd: 1,
			get_query: () => ({ filters: { scoring_type: ["!=", "No Scoring"] } }),
		},
		{
			fieldname: "passed",
			label: __("Passed"),
			fieldtype: "Select",
			options: ["", "Yes", "No"],
		},
	],
};
