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
import { api } from "./api.js";
import { contrastOn, focusFirstInput, safeColor, scrollToTop, setBackground } from "./dom.js";
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
	direction,
	errors,
	isTest,
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

const LABELS = {
	continue: "Continue",
	submit: "Submit",
	// The server decides this one: it knows a mandatory question is still
	// blank somewhere, so "Submit" would be a lie about what the button does.
	next_skipped: "Next unanswered",
};

const submitLabel = computed(() => LABELS[navigation.value.submit_label] || LABELS.continue);
const isSubmit = computed(() => navigation.value.submit_label === "submit");
const skippedRemaining = computed(() => navigation.value.skipped_remaining || 0);

const progressLabel = computed(() => {
	const value = progress.value;
	if (!value || !value.total) return "";
	return value.mode === "Number" ? `${value.current} / ${value.total}` : `${value.percent}%`;
});

// The author's accent, validated before it reaches a style attribute.
const themeStyle = computed(() => {
	const accent = safeColor(survey.value.accent_color);
	return accent ? { "--survey-accent": accent, "--survey-accent-contrast": contrastOn(accent) } : {};
});

function setAnswer(questionId, answer) {
	answers[questionId] = answer;
	maybeAutoAdvance(questionId);
}

/**
 * Move on by itself once a lone single-choice question is answered.
 *
 * Only ever triggered from a respondent's own pick (never from answers being
 * repopulated on Back), and only where advancing is unambiguous: one question
 * on screen, one choice allowed, no comment box that still wants typing in.
 * The short pause lets them see what they picked.
 */
let advanceTimer = null;

function maybeAutoAdvance(questionId) {
	if (!survey.value.auto_advance || multiQuestion.value) return;

	const question = visibleQuestions.value.find((each) => each.id === questionId);
	if (!question || question.question_type !== "Single Choice" || question.allow_comments) return;
	if (visibleQuestions.value.length !== 1 || !answers[questionId]?.value) return;

	clearTimeout(advanceTimer);
	advanceTimer = setTimeout(() => {
		if (!busy.value && screen.value === "in_progress") submit("next");
	}, 380);
}

/** Test runs only: throw this one away and start a fresh one. */
async function retest() {
	try {
		const { message } = await api.startTest(survey.value.name);
		window.location.href = message.url;
	} catch (error) {
		console.error("survey: could not start a new test", error);
	}
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
		maybeAutoAdvance(question.id);
	}
}

onMounted(() => document.addEventListener("keydown", onKeyDown));
onUnmounted(() => {
	document.removeEventListener("keydown", onKeyDown);
	clearTimeout(advanceTimer);
});
</script>

<template>
	<div ref="root" class="survey-player" :style="themeStyle">
		<ProgressBar v-if="showChrome && progress && progress.total" :progress="progress" />

		<div v-if="isTest" class="survey-testbar" role="status">
			<strong>Test run</strong>
			<span>Nothing you answer here is counted or saved to results.</span>
		</div>

		<div class="survey-shell">
			<header v-if="showChrome" class="survey-header">
				<h1 class="survey-header__title">{{ survey.title }}</h1>
				<div class="survey-header__meta">
					<span v-if="progressLabel" class="survey-header__count">{{ progressLabel }}</span>
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
				<Transition :name="`survey-${direction}`" mode="out-in">
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
						:certificate-url="payload.certificate_url"
						:is-test="isTest"
						:busy="busy"
						@retest="retest"
					/>

					<SurveyPage
						v-else-if="page"
						:key="page.id"
						:page="page"
						:questions="visibleQuestions"
						:answers="answers"
						:errors="errors"
						:compact="!multiQuestion"
						:position="progress ? progress.current : 0"
						@update:answer="setAnswer"
						@submit="submit('next')"
					/>
				</Transition>
			</main>

			<footer v-if="showChrome" class="survey-footer">
				<button
					v-if="navigation.can_go_back"
					type="button"
					class="survey-btn survey-btn--ghost"
					:disabled="busy"
					@click="submit('back')"
				>
					<svg class="survey-btn__arrow survey-btn__arrow--back" viewBox="0 0 20 20" aria-hidden="true"><path d="M16 10H5m4-4-4 4 4 4" /></svg>
					Back
				</button>

				<span v-if="skippedRemaining" class="survey-hint survey-hint--pending">
					{{ skippedRemaining }} question{{ skippedRemaining === 1 ? "" : "s" }} still need an answer
				</span>
				<span v-else class="survey-hint">press <kbd>Enter ↵</kbd></span>

				<button
					type="button"
					class="survey-btn survey-btn--large"
					:class="isSubmit ? 'survey-btn--submit' : 'survey-btn--primary'"
					:disabled="busy"
					@click="submit('next')"
				>
					{{ submitLabel }}
					<svg v-if="!isSubmit" class="survey-btn__arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11m-4-4 4 4-4 4" /></svg>
					<svg v-else class="survey-btn__arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 10.5 3.5 3.5L15 7" /></svg>
				</button>
			</footer>
		</div>
	</div>
</template>
