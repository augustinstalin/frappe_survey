/**
 * Calls to the public player endpoints.
 *
 * Uses `fetch` against `/api/method/...` rather than `frappe.call`, because
 * this page must work for a guest without the Desk bundle loaded.
 */

const BASE = "/api/method/survey.api.player";

/**
 * Frappe writes the token into the page as `frappe.csrf_token` (see
 * `BaseTemplatePage`), not `window.csrf_token`. A guest has none and is not
 * checked; a signed-in visitor — an author running "Test Survey", or a
 * login-required survey — is rejected without it.
 */
function csrfToken() {
	return window.frappe?.csrf_token || window.csrf_token || "";
}

async function call(method, args = {}) {
	const response = await fetch(`${BASE}.${method}`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": csrfToken(),
		},
		credentials: "same-origin",
		body: JSON.stringify(args),
	});

	if (!response.ok) {
		// A 429 is the rate limiter, and is worth saying plainly rather than
		// as a generic failure.
		if (response.status === 429) {
			return {
				state: "error",
				code: "rate_limited",
				message: "Too many requests. Please wait a moment and try again.",
			};
		}
		throw new Error(`Request failed: ${response.status}`);
	}

	const payload = await response.json();
	return payload.message;
}

export const api = {
	start: (surveyToken, extra = {}) => call("start", { survey_token: surveyToken, ...extra }),

	getState: (surveyToken, responseToken) =>
		call("get_state", { survey_token: surveyToken, response_token: responseToken }),

	begin: (surveyToken, responseToken) =>
		call("begin", { survey_token: surveyToken, response_token: responseToken }),

	submitPage: (surveyToken, responseToken, pageId, answers, direction = "next", targetPageId = null) =>
		call("submit_page", {
			survey_token: surveyToken,
			response_token: responseToken,
			page_id: pageId,
			answers: JSON.stringify(answers),
			direction,
			target_page_id: targetPageId,
		}),

	// Authors only; a guest gets a permission error, which is correct.
	startTest: (survey) => call("start_test", { survey }),

	goBack: (surveyToken, responseToken, pageId) =>
		call("go_back", {
			survey_token: surveyToken,
			response_token: responseToken,
			page_id: pageId,
		}),
};
