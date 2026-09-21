/**
 * Client-side mirror of `survey/player/validation.py`.
 *
 * This exists only to spare the respondent a round trip; the server re-checks
 * everything and is the authority. Keep the two in step — a rule that exists
 * here but not there is a hole, and a rule there but not here is a confusing
 * round trip.
 */

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function validatePage(questions, answers, { allowRoaming = false } = {}) {
	const errors = {};

	for (const question of questions) {
		const given = answers[question.id] || {};
		const error = validateAnswer(question, given.value, given.comment, allowRoaming);
		if (error) errors[question.id] = error;
	}

	return errors;
}

export function validateAnswer(question, value, comment, allowRoaming = false) {
	if (isEmpty(value)) {
		if (!question.mandatory) return null;
		if (question.comment_counts_as_answer && comment && comment.trim()) return null;
		if (allowRoaming) return null;
		return question.mandatory_error_message || "This question requires an answer.";
	}

	switch (question.question_type) {
		case "Single Line Text":
			return validateShortText(question, String(value));
		case "Numeric":
			return validateNumeric(question, value);
		case "Date":
		case "Datetime":
			return validateTemporal(question, value);
		case "Matrix":
			return validateMatrix(question, value);
		default:
			return null;
	}
}

/** `0` is a real answer, so this cannot be a truthiness check. */
export function isEmpty(value) {
	if (value === null || value === undefined) return true;
	if (typeof value === "number") return false;
	if (typeof value === "string") return value.trim() === "";
	if (Array.isArray(value)) return value.length === 0;
	if (typeof value === "object") {
		return Object.values(value).every((entry) => !entry || entry.length === 0);
	}
	return false;
}

function validateShortText(question, text) {
	if (question.validate_email && !EMAIL.test(text)) {
		return "This answer must be an email address.";
	}
	if (!question.validate_entry) return null;

	if (question.min_length && text.length < question.min_length) return invalid(question);
	if (question.max_length && text.length > question.max_length) return invalid(question);
	return null;
}

function validateNumeric(question, value) {
	const number = Number(value);
	if (Number.isNaN(number)) return "Please enter a number.";
	if (!question.validate_entry) return null;

	if (question.min_value && number < question.min_value) return invalid(question);
	if (question.max_value && number > question.max_value) return invalid(question);
	return null;
}

function validateTemporal(question, value) {
	const given = new Date(value);
	if (Number.isNaN(given.getTime())) return "Please enter a valid date.";
	if (!question.validate_entry) return null;

	const isDate = question.question_type === "Date";
	const min = isDate ? question.min_date : question.min_datetime;
	const max = isDate ? question.max_date : question.max_datetime;

	if (min && given < new Date(min)) return invalid(question);
	if (max && given > new Date(max)) return invalid(question);
	return null;
}

function validateMatrix(question, value) {
	if (!question.mandatory) return null;

	const answered = Object.values(value || {}).filter((picked) => picked && picked.length).length;
	if (answered < (question.rows || []).length) {
		return question.mandatory_error_message || "Please answer every row.";
	}
	return null;
}

function invalid(question) {
	return question.validation_error_message || "The answer you entered is not valid.";
}
