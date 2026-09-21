/**
 * Show and hide conditional questions as the respondent answers.
 *
 * Only used on the layouts where several questions share a screen. On
 * "One Page Per Question" the server decides what comes next, so the payload
 * carries no maps and this module answers "nothing is hidden".
 *
 * Semantics match the server (`get_inactive_questions`): a question with
 * triggers is visible when *at least one* of them is selected. Chaining needs
 * no special handling — a hidden question's answer is cleared, so anything
 * depending on it goes away on the same pass.
 *
 * Unlike the DOM-walking version this replaces, everything here is a pure
 * function of the answer state. The rendered page is downstream of that
 * state rather than the other way round, which is what removes the class of
 * bug where the screen and the collected answers disagreed.
 */

/** Every option id currently ticked, across all answers on the page. */
export function selectedOptionIds(questions, answers) {
	const chosen = new Set();

	for (const question of questions) {
		// Triggers can only ever be choice options, which is why scale and
		// matrix selections are deliberately not counted here.
		if (question.question_type !== "Single Choice" && question.question_type !== "Multiple Choice") {
			continue;
		}

		const value = answers[question.id]?.value;
		if (!value) continue;

		for (const id of [].concat(value)) if (id) chosen.add(id);
	}

	return chosen;
}

/** Ids of the questions that should currently be hidden. */
export function hiddenQuestionIds(questions, answers, conditional = {}) {
	const required = conditional.required_options_by_question || {};
	if (!Object.keys(required).length) return new Set();

	const chosen = selectedOptionIds(questions, answers);
	const hidden = new Set();

	for (const [questionId, options] of Object.entries(required)) {
		if (!options.length) continue;
		if (!options.some((option) => chosen.has(option))) hidden.add(questionId);
	}

	return hidden;
}
