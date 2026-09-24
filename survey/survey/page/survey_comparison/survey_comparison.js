// Copyright (c) 2026, Bosco Soft Technologies and contributors
// For license information, please see license.txt

/**
 * One row per wave of a Recurring survey's series, for whichever question
 * carries the chosen `comparison_key` in that wave (see
 * `survey.api.comparison.get_comparison_data`'s docstring). The same table
 * shape serves an annual survey's "last year vs. this year" (2 rows) and a
 * quarterly pulse survey's multi-year trend (a dozen rows) — the cadence
 * only changes how many rows there are, never the report itself.
 */
frappe.pages["survey-comparison"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Survey Comparison"),
		single_column: true,
	});

	new SurveyComparison(page);
};

class SurveyComparison {
	constructor(page) {
		this.page = page;
		this.series_field = this.page.add_field({
			fieldname: "series",
			label: __("Series"),
			fieldtype: "Select",
			options: [],
			change: () => this.on_series_change(),
		});

		this.key_field = this.page.add_field({
			fieldname: "comparison_key",
			label: __("Question"),
			fieldtype: "Select",
			options: [],
			change: () => this.run(),
		});

		this.$results = $('<div class="survey-comparison__table"></div>').appendTo(this.page.main);

		this.load_series();
	}

	async load_series() {
		const { message: series } = await frappe.call({ method: "survey.api.comparison.list_series" });
		this.series_field.df.options = series || [];
		this.series_field.refresh();
	}

	async on_series_change() {
		const series = this.series_field.get_value();
		this.$results.empty();

		if (!series) {
			this.key_field.df.options = [];
			this.key_field.refresh();
			return;
		}

		const { message: keys } = await frappe.call({
			method: "survey.api.comparison.list_comparison_keys",
			args: { series },
		});

		this.key_by_label = {};
		const options = [""].concat(
			(keys || []).map((k) => {
				const label = `${k.title} (${k.comparison_key})`;
				this.key_by_label[label] = k.comparison_key;
				return label;
			})
		);

		this.key_field.df.options = options;
		this.key_field.refresh();
	}

	async run() {
		const series = this.series_field.get_value();
		const label = this.key_field.get_value();
		const comparison_key = this.key_by_label ? this.key_by_label[label] : null;

		this.$results.empty();
		if (!series || !comparison_key) return;

		const { message } = await frappe.call({
			method: "survey.api.comparison.get_comparison_data",
			args: { series, comparison_key },
			freeze: true,
		});

		this.render(message);
	}

	render({ waves }) {
		this.$results.empty();

		if (!waves.length) {
			$(`<p class="text-muted">${__("No waves found in this series.")}</p>`).appendTo(this.$results);
			return;
		}

		// Every distinct option label across every wave becomes its own
		// column, so a wave missing a question (or an option retired since)
		// simply shows a blank cell rather than shifting the other columns.
		const all_labels = [];
		waves.forEach((wave) => {
			wave.distribution.forEach((d) => {
				if (!all_labels.includes(d.label)) all_labels.push(d.label);
			});
		});

		const $table = $(
			`<table class="table table-bordered">
				<thead><tr>
					<th>${__("Wave")}</th>
					<th>${__("Question")}</th>
					<th>${__("Responses")}</th>
					${all_labels.map((l) => `<th>${frappe.utils.escape_html(l)}</th>`).join("")}
					<th>${__("Average Score")}</th>
				</tr></thead>
				<tbody></tbody>
			</table>`
		).appendTo(this.$results);

		const $body = $table.find("tbody");
		waves.forEach((wave) => {
			const by_label = {};
			wave.distribution.forEach((d) => (by_label[d.label] = d));

			const cells = all_labels
				.map((label) => {
					const d = by_label[label];
					return `<td>${d ? `${d.percentage}% (${d.count})` : "—"}</td>`;
				})
				.join("");

			$(`
				<tr>
					<td>${frappe.utils.escape_html(wave.wave_label || "")}</td>
					<td>${wave.question_title ? frappe.utils.escape_html(wave.question_title) : `<span class="text-muted">${__("Not in this wave")}</span>`}</td>
					<td>${wave.response_count}</td>
					${cells}
					<td>${wave.average_score != null ? wave.average_score + "%" : "—"}</td>
				</tr>
			`).appendTo($body);
		});
	}
}
