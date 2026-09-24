// Copyright (c) 2026, Bosco Soft Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Survey Answers"] = {
	filters: [
		{
			fieldname: "survey",
			label: __("Survey"),
			fieldtype: "Link",
			options: "Survey",
			reqd: 1,
		},
		{
			fieldname: "question",
			label: __("Question"),
			fieldtype: "Link",
			options: "Survey Question",
			get_query: () => {
				const survey = frappe.query_report.get_filter_value("survey");
				return { filters: { survey } };
			},
		},
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To"),
			fieldtype: "Date",
		},
	],
};
