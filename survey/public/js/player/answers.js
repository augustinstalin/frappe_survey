/**
 * The shape of an answer, per question type.
 *
 * One place decides this so the renderers, the validator and the payload
 * builder cannot drift apart.
 */

/** The value a question starts with when nothing has been answered yet. */
export function emptyValue(question) {
	switch (question.question_type) {
		case "Multiple Choice":
			return [];
		case "Matrix":
			return {};
		default:
			return null;
	}
}

/**
 * Build the answer state for a page.
 *
 * `given` is what the server already has for this response, so going back to
 * a page shows what was answered rather than a blank form.
 */
export function initAnswers(questions, given = {}) {
	const answers = {};

	for (const question of questions) {
		const previous = given[question.id] || {};
		let value = previous.value;

		if (value === undefined || value === null) {
			value = emptyValue(question);
		} else if (question.question_type === "Multiple Choice") {
			value = [].concat(value);
		} else if (question.question_type === "Datetime" && value) {
			// `<input type=datetime-local>` will not accept a space separator
			// or seconds.
			value = String(value).replace(" ", "T").slice(0, 16);
		}

		answers[question.id] = { value, comment: previous.comment || "" };
	}

	return answers;
}

/** Strip the questions that are hidden — an unasked question is unanswered. */
export function collectAnswers(questions, answers, hidden) {
	const payload = {};

	for (const question of questions) {
		if (hidden.has(question.id)) continue;

		const answer = answers[question.id] || {};
		payload[question.id] = {
			value: answer.value,
			comment: (answer.comment || "").trim() || null,
		};
	}

	return payload;
}
