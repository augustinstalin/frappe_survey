/**
 * The player's state machine.
 *
 * Holds no survey knowledge of its own: what to show and what comes next are
 * both server decisions, which is what keeps skip logic, randomisation and
 * scoring honest against a client that cannot be trusted. Everything here is
 * about *when* to ask the server and what to do with the reply.
 */

import { computed, reactive, readonly, ref, watch } from "vue";

import { api } from "./api.js";
import { collectAnswers, initAnswers } from "./answers.js";
import { hiddenQuestionIds } from "./skip_logic.js";
import { isEmpty, validatePage } from "./validate.js";

export function useSurvey(surveyToken, bootstrap) {
	const payload = ref(bootstrap);
	const responseToken = ref(null);
	const answers = reactive({});
	const errors = reactive({});
	const busy = ref(false);

	const screen = computed(() => payload.value.state || "error");
	const survey = computed(() => payload.value.survey || {});
	const page = computed(() => payload.value.page || null);
	const questions = computed(() => page.value?.questions || []);
	const navigation = computed(() => payload.value.navigation || {});
	const progress = computed(() => payload.value.progress || null);
	const timer = computed(() => payload.value.timer || null);
	const breadcrumb = computed(() => payload.value.breadcrumb || []);
	const timedOut = computed(() => Boolean(payload.value.timed_out));

	const hidden = computed(() =>
		hiddenQuestionIds(questions.value, answers, payload.value.conditional || {})
	);

	const visibleQuestions = computed(() =>
		questions.value.filter((question) => !hidden.value.has(question.id))
	);

	/**
	 * A hidden question's answer is cleared as it goes, so an answer given
	 * before the trigger was flipped cannot silently survive and keep
	 * unlocking whatever *it* triggers. The server does the same on submit;
	 * doing it here too keeps the screen honest in between.
	 *
	 * Known limitation, shared with Odoo: flip a trigger off and back on and
	 * the text behind it is gone.
	 */
	// Watched through a stable string rather than the Set itself: a computed
	// returning a fresh Set every time would re-fire this watcher on its own
	// writes, and clearing an already-empty answer would loop forever.
	const hiddenKey = computed(() => Array.from(hidden.value).sort().join("|"));

	watch(hiddenKey, () => {
		for (const question of questions.value) {
			if (!hidden.value.has(question.id)) continue;

			const answer = answers[question.id];
			if (!answer) continue;
			if (isEmpty(answer.value) && !answer.comment) continue;

			answers[question.id] = initAnswers([question])[question.id];
			delete errors[question.id];
		}
	});

	function loadPage(next) {
		payload.value = next;
		if (next.response_token) responseToken.value = next.response_token;

		for (const key of Object.keys(answers)) delete answers[key];
		for (const key of Object.keys(errors)) delete errors[key];

		if (next.state === "in_progress" && next.page) {
			Object.assign(answers, initAnswers(next.page.questions || [], next.answers || {}));
		}
	}

	async function guarded(work) {
		if (busy.value) return;
		busy.value = true;
		try {
			return await work();
		} finally {
			busy.value = false;
		}
	}

	async function begin() {
		return guarded(async () => {
			if (!responseToken.value) {
				const started = await api.start(surveyToken);
				if (started.response_token) responseToken.value = started.response_token;
				if (started.state === "error") return loadPage(started);
			}

			loadPage(await api.begin(surveyToken, responseToken.value));
		});
	}

	async function submit(direction = "next", targetPageId = null) {
		if (screen.value !== "in_progress" || !page.value) return;

		const given = collectAnswers(questions.value, answers, hidden.value);

		// Only moving *forward* is gated on the page being valid. Going back,
		// jumping to an earlier section, or running out of time all save
		// whatever is there and move on; refusing to save a half-filled page
		// on the way out would lose work rather than protect it.
		if (direction === "next") {
			const found = validatePage(visibleQuestions.value, given, {
				allowRoaming: Boolean(survey.value.allow_roaming),
			});

			for (const key of Object.keys(errors)) delete errors[key];
			if (Object.keys(found).length) {
				Object.assign(errors, found);
				return;
			}
		}

		return guarded(async () => {
			const next = await api.submitPage(
				surveyToken,
				responseToken.value,
				page.value.id,
				given,
				direction,
				targetPageId
			);

			if (next.state === "invalid") {
				// The server disagreed with the client-side check. It wins.
				for (const key of Object.keys(errors)) delete errors[key];
				Object.assign(errors, next.errors || {});
				return;
			}

			loadPage(next);
		});
	}

	// The bootstrap payload goes through the same door as every API reply.
	// It matters because a resumed response boots straight into
	// `in_progress`: without this the first page would render with no answer
	// state at all.
	loadPage(bootstrap);

	return {
		answers,
		breadcrumb,
		begin,
		busy: readonly(busy),
		errors,
		hidden,
		navigation,
		page,
		payload: readonly(payload),
		progress,
		questions,
		screen,
		submit,
		survey,
		timedOut,
		timer,
		visibleQuestions,
	};
}
