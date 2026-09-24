// Copyright (c) 2026, Bosco Soft Technologies and contributors
// For license information, please see license.txt

/**
 * Cross-question answer filtering — the one thing a plain Query Report
 * cannot express (see `survey.api.reports.get_filtered_responses`'s
 * docstring for why). Per-question distributions and trend charts already
 * exist as the "Survey Answer Distribution" report and the "Survey
 * Analytics" dashboard; this page is deliberately just the piece those two
 * cannot do — "everyone who answered Q1=B *and* Q3=Yes" — not a second copy
 * of what they already cover.
 */
frappe.pages["survey-results"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Survey Results"),
		single_column: true,
	});

	new SurveyResults(page);
};

class SurveyResults {
	constructor(page) {
		this.page = page;
		this.filter_rows = []; // {question, option}
		this.question_cache = {};

		this.survey_field = this.page.add_field({
			fieldname: "survey",
			label: __("Survey"),
			fieldtype: "Link",
			options: "Survey",
			change: () => this.on_survey_change(),
		});

		this.$summary = $('<div class="survey-results__summary row"></div>')
			.appendTo(this.page.main)
			.hide();
		this.$filters = $('<div class="survey-results__filters"></div>').appendTo(this.page.main);
		this.$results = $('<div class="survey-results__table"></div>').appendTo(this.page.main);
	}

	async on_survey_change() {
		const survey = this.survey_field.get_value();
		this.filter_rows = [];
		this.$results.empty();

		if (!survey) {
			this.$summary.hide();
			this.$filters.empty();
			return;
		}

		await this.load_questions(survey);
		this.render_summary(survey);
		this.render_filters();
	}

	async load_questions(survey) {
		const { message } = await frappe.call({
			method: "survey.api.reports.get_choice_questions",
			args: { survey },
		});
		this.question_cache[survey] = message || [];
	}

	get questions() {
		return this.question_cache[this.survey_field.get_value()] || [];
	}

	async render_summary(survey) {
		const { message: summary } = await frappe.call({
			method: "survey.api.reports.get_dashboard_summary",
			args: { survey },
		});

		const tiles = [
			[__("Total Responses"), summary.total_responses],
			[__("Completed"), summary.completed_responses],
			[__("Completion Rate"), `${summary.completion_rate}%`],
			[__("Average Score"), summary.average_score != null ? `${summary.average_score}%` : "—"],
			[__("Pass Rate"), summary.pass_rate != null ? `${summary.pass_rate}%` : "—"],
		];

		this.$summary.empty().show();
		for (const [label, value] of tiles) {
			$(`
				<div class="col-sm-2">
					<div class="survey-results__tile" style="padding: 12px; border: 1px solid var(--border-color); border-radius: var(--border-radius); margin-bottom: 12px;">
						<div class="text-muted small">${frappe.utils.escape_html(label)}</div>
						<div style="font-size: 20px; font-weight: 600;">${frappe.utils.escape_html(String(value))}</div>
					</div>
				</div>
			`).appendTo(this.$summary);
		}
	}

	render_filters() {
		this.$filters.empty();

		$(`<h5>${__("Filter by Answer")}</h5>`).appendTo(this.$filters);
		this.$filter_rows = $('<div class="survey-results__filter-rows"></div>').appendTo(this.$filters);

		if (!this.filter_rows.length) this.filter_rows.push({ question: null, option: null });
		this.filter_rows.forEach((row, index) => this.render_filter_row(row, index));

		$(`<button class="btn btn-xs btn-default">${__("+ Add Filter")}</button>`)
			.appendTo(this.$filters)
			.on("click", () => {
				this.filter_rows.push({ question: null, option: null });
				this.render_filters();
			});

		$(`<button class="btn btn-xs btn-primary" style="margin-left: 8px;">${__("Run")}</button>`)
			.appendTo(this.$filters)
			.on("click", () => this.run());
	}

	render_filter_row(row, index) {
		const $row = $('<div class="survey-results__filter-row" style="display:flex; gap:8px; margin-bottom:8px;"></div>').appendTo(
			this.$filter_rows
		);

		const question_select = $(`<select class="form-control"><option value="">${__("Question")}</option></select>`).appendTo(
			$row
		);
		this.questions.forEach((q) => {
			$("<option>")
				.val(q.name)
				.text(q.title)
				.prop("selected", q.name === row.question)
				.appendTo(question_select);
		});

		const option_select = $(`<select class="form-control"><option value="">${__("Answer")}</option></select>`).appendTo(
			$row
		);
		const fill_options = () => {
			option_select.empty().append(`<option value="">${__("Answer")}</option>`);
			const question = this.questions.find((q) => q.name === row.question);
			(question ? question.options : []).forEach((opt) => {
				$("<option>").val(opt.name).text(opt.label).prop("selected", opt.name === row.option).appendTo(option_select);
			});
		};
		fill_options();

		question_select.on("change", () => {
			row.question = question_select.val() || null;
			row.option = null;
			fill_options();
		});
		option_select.on("change", () => {
			row.option = option_select.val() || null;
		});

		$(`<button class="btn btn-xs btn-default">${__("Remove")}</button>`)
			.appendTo($row)
			.on("click", () => {
				this.filter_rows.splice(index, 1);
				this.render_filters();
			});
	}

	async run() {
		const survey = this.survey_field.get_value();
		if (!survey) return;

		const rows = this.filter_rows.filter((r) => r.question && r.option);
		const { message } = await frappe.call({
			method: "survey.api.reports.get_filtered_responses",
			args: { survey, filters: rows },
			freeze: true,
		});

		this.render_results(message);
	}

	render_results({ total, rows }) {
		this.$results.empty();
		$(`<h5>${__("Matching Respondents")} (${total})</h5>`).appendTo(this.$results);

		if (!rows.length) {
			$(`<p class="text-muted">${__("No responses match these filters.")}</p>`).appendTo(this.$results);
			return;
		}

		const $table = $(
			`<table class="table table-bordered">
				<thead><tr>
					<th>${__("Respondent")}</th>
					<th>${__("Score")}</th>
					<th>${__("Passed")}</th>
					<th>${__("Submitted On")}</th>
				</tr></thead>
				<tbody></tbody>
			</table>`
		).appendTo(this.$results);

		const $body = $table.find("tbody");
		rows.forEach((row) => {
			$(`
				<tr>
					<td><a href="/app/survey-response/${row.name}">${frappe.utils.escape_html(row.respondent)}</a></td>
					<td>${row.score_percentage != null ? row.score_percentage + "%" : "—"}</td>
					<td>${row.passed ? __("Yes") : __("No")}</td>
					<td>${row.completed_on ? frappe.datetime.str_to_user(row.completed_on) : ""}</td>
				</tr>
			`).appendTo($body);
		});
	}
}
