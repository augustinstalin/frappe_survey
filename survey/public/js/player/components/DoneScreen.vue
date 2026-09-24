<script setup>
import { computed, ref } from "vue";

const props = defineProps({
	result: { type: Object, default: null },
	endMessage: { type: String, default: "" },
	timedOut: { type: Boolean, default: false },
	certificateUrl: { type: String, default: null },
	isTest: { type: Boolean, default: false },
	busy: { type: Boolean, default: false },
});

const emit = defineEmits(["retest"]);

// The ring is drawn as a dashed circle whose dash length is the score. The
// circumference is 2π·52 ≈ 326.7.
const CIRCUMFERENCE = 326.7;
const percentage = computed(() => Math.max(0, Math.min(100, props.result?.percentage || 0)));
const dash = computed(() => `${(percentage.value / 100) * CIRCUMFERENCE} ${CIRCUMFERENCE}`);

const celebrate = computed(() => !props.timedOut && (!props.result || props.result.passed));

// Fixed positions, not random ones: the same pieces every render, so the
// component stays pure and the animation does not reshuffle on re-render.
const confetti = Array.from({ length: 28 }, (_, i) => ({
	left: `${(i * 37) % 100}%`,
	delay: `${((i * 53) % 90) / 100}s`,
	duration: `${2.2 + ((i * 17) % 14) / 10}s`,
	hue: (i * 47) % 360,
	tilt: `${(i * 29) % 360}deg`,
}));

const retesting = ref(false);
function retest() {
	retesting.value = true;
	emit("retest");
}
</script>

<template>
	<section class="survey-done">
		<div v-if="celebrate" class="survey-confetti" aria-hidden="true">
			<span
				v-for="(piece, i) in confetti"
				:key="i"
				class="survey-confetti__piece"
				:style="{
					left: piece.left,
					animationDelay: piece.delay,
					animationDuration: piece.duration,
					backgroundColor: `hsl(${piece.hue} 80% 58%)`,
					'--tilt': piece.tilt,
				}"
			></span>
		</div>

		<p v-if="timedOut" class="survey-done__timeout">
			Your time ran out, so the survey was submitted with the answers you had given.
		</p>

		<div v-if="result" class="survey-ring" :class="result.passed ? 'is-passed' : 'is-failed'">
			<svg viewBox="0 0 120 120" aria-hidden="true">
				<circle class="survey-ring__track" cx="60" cy="60" r="52" />
				<circle class="survey-ring__value" cx="60" cy="60" r="52" :style="{ '--dash': dash }" />
			</svg>
			<span class="survey-ring__label">{{ Math.round(percentage) }}<small>%</small></span>
		</div>
		<div v-else class="survey-check" aria-hidden="true">
			<svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="24" /><path d="m15 27 8 8 15-17" /></svg>
		</div>

		<h1 class="survey-done__title">
			<template v-if="result">{{ result.passed ? "You passed!" : "Not quite there" }}</template>
			<template v-else>Thank you!</template>
		</h1>

		<p v-if="result" class="survey-done__verdict" :class="result.passed ? 'is-passed' : 'is-failed'">
			You scored {{ result.percentage }}%. {{ result.passed ? "" : `You needed ${result.passing_score}% to pass.` }}
		</p>

		<div v-if="endMessage" class="survey-done__message" v-html="endMessage"></div>

		<div class="survey-done__actions">
			<a v-if="certificateUrl" class="survey-btn survey-btn--primary survey-btn--large" :href="certificateUrl">
				Download certificate
			</a>
			<button
				v-if="isTest"
				type="button"
				class="survey-btn survey-btn--ghost survey-btn--large"
				:disabled="busy || retesting"
				@click="retest"
			>
				Run the test again
			</button>
		</div>
	</section>
</template>
