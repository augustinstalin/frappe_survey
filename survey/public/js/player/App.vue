<!--
	The survey player.

	Owns the screen: renders whatever payload the API returned, collects
	answers, and moves between pages. All of the deciding lives on the server;
	this is presentation and input.
-->
<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";

import DoneScreen from "./components/DoneScreen.vue";
import ErrorNotice from "./components/ErrorNotice.vue";
import IntroScreen from "./components/IntroScreen.vue";
import ProgressBar from "./components/ProgressBar.vue";
import SurveyBreadcrumb from "./components/SurveyBreadcrumb.vue";
import SurveyPage from "./components/SurveyPage.vue";
import SurveyTimer from "./components/SurveyTimer.vue";
import { focusFirstInput, scrollToTop, setBackground } from "./dom.js";
import { useSurvey } from "./useSurvey.js";

const props = defineProps({
	surveyToken: { type: String, required: true },
	bootstrap: { type: Object, required: true },
});

const {
	answers,
	breadcrumb,
	begin,
	busy,
	errors,
	navigation,
	page,
	payload,
	progress,
	screen,
	submit,
	survey,
	timedOut,
	timer,
	visibleQuestions,
} = useSurvey(props.surveyToken, props.bootstrap);

const root = ref(null);
const body = ref(null);

const showChrome = computed(() => screen.value === "in_progress");
const multiQuestion = computed(() => survey.value.pagination !== "One Page Per Question");

function setAnswer(questionId, answer) {
	answers[questionId] = answer;
}

/**
 * The countdown hit zero in this browser.
 *
 * The server re-checks its own clock and is the authority — this only asks
 * it to close the run, and hands over whatever is on screen so a page filled
 * in just before the buzzer is not lost. Guarded so a repeat fire (two tabs,
 * a re-render) cannot submit twice.
 */
let expiring = false;

function onExpired() {
	if (expiring || screen.value !== "in_progress") return;
	expiring = true;
	submit("timeout");
}

function onJump(targetPageId) {
	if (targetPageId === page.value?.id) return;
	submit("jump", targetPageId);
}

// -------------------------------------------------------------------
// Chrome that lives outside Vue's reactive rendering
// -------------------------------------------------------------------

watch(
	() => payload.value.background_image,
	(url) => setBackground(root.value, url),
	{ immediate: true }
);

watch(
	() => page.value?.id,
	() => {
		scrollToTop();
		nextTick(() => focusFirstInput(body.value));
	}
);

// Bring the first thing that failed into view. The message itself is rendered
// by the question; this only handles getting there.
watch(
	() => Object.keys(errors)[0],
	(questionId) => {
		if (!questionId) return;
		nextTick(() => {
			const node = body.value?.querySelector(`[data-question="${questionId}"]`);
			if (!node) return;
			node.scrollIntoView({ behavior: "smooth", block: "center" });
			node.querySelector("input, textarea, select")?.focus();
		});
	}
);

// -------------------------------------------------------------------
// Keyboard
// -------------------------------------------------------------------

/**
 * Enter advances; a letter picks the option with that key.
 *
 * Inside a textarea Enter means a newline, so it only submits with a modifier
 * there. On layouts with several questions per screen, Enter alone is also
 * ambiguous, so it needs the modifier too.
 */
function onKeyDown(event) {
	if (busy.value) return;

	const target = event.target;
	const inTextarea = target?.tagName === "TEXTAREA";
	const inInput = target?.tagName === "INPUT" || inTextarea;
	const modifier = event.ctrlKey || event.metaKey;

	if (event.key === "Enter") {
		if (inTextarea && !modifier) return;
		if (multiQuestion.value && !modifier && inInput) return;

		event.preventDefault();
		if (screen.value === "new") begin();
		else if (screen.value === "in_progress") submit("next");
		return;
	}

	// Letter shortcuts only make sense when one question owns the screen.
	if (multiQuestion.value || inInput || modifier) return;

	const letter = event.key.toUpperCase();
	if (!/^[A-Z]$/.test(letter)) return;

	for (const question of visibleQuestions.value) {
		const option = (question.options || []).find((each) => each.key === letter);
		if (!option) continue;

		event.preventDefault();
		toggleOption(question, option);
		return;
	}
}

function toggleOption(question, option) {
	const answer = answers[question.id];
	if (!answer) return;

	if (question.question_type === "Multiple Choice") {
		const current = [].concat(answer.value || []);
		const at = current.indexOf(option.id);
		if (at === -1) current.push(option.id);
		else current.splice(at, 1);
		answers[question.id] = { ...answer, value: current };
	} else if (question.question_type === "Single Choice") {
		answers[question.id] = { ...answer, value: option.id };
	}
}

onMounted(() => document.addEventListener("keydown", onKeyDown));
onUnmounted(() => document.removeEventListener("keydown", onKeyDown));
</script>

<template>
	<div ref="root" class="survey-player">
		<div class="survey-shell">
			<header v-if="showChrome" class="survey-header">
				<h1 class="survey-header__title">{{ survey.title }}</h1>
				<div class="survey-header__meta">
					<SurveyTimer v-if="timer" :timer="timer" @expired="onExpired" />
				</div>
			</header>

			<SurveyBreadcrumb
				v-if="showChrome && breadcrumb.length"
				:trail="breadcrumb"
				:busy="busy"
				@jump="onJump"
			/>

			<main ref="body" class="survey-body" aria-live="polite">
				<Transition name="survey-screen" mode="out-in">
					<ErrorNotice v-if="screen === 'error'" :message="payload.message" />

					<IntroScreen
						v-else-if="screen === 'new'"
						:survey="survey"
						:busy="busy"
						@begin="begin"
					/>

					<DoneScreen
						v-else-if="screen === 'done'"
						:result="payload.result"
						:end-message="payload.end_message"
						:timed-out="timedOut"
					/>

					<SurveyPage
						v-else-if="page"
						:key="page.id"
						:page="page"
						:questions="visibleQuestions"
						:answers="answers"
						:errors="errors"
						:submit-label="navigation.submit_label || 'continue'"
						:skipped-remaining="navigation.skipped_remaining || 0"
						:busy="busy"
						@update:answer="setAnswer"
						@submit="submit('next')"
					/>
				</Transition>
			</main>

			<footer v-if="showChrome" class="survey-footer">
				<div class="survey-footer__left">
					<button
						v-if="navigation.can_go_back"
						type="button"
						class="survey-btn survey-btn--ghost"
						:disabled="busy"
						@click="submit('back')"
					>
						Back
					</button>
				</div>
				<div class="survey-footer__progress">
					<ProgressBar v-if="progress && progress.total" :progress="progress" />
				</div>
			</footer>
		</div>
	</div>
</template>
