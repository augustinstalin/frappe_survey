<script setup>
import { computed } from "vue";

const props = defineProps({
	survey: { type: Object, required: true },
	busy: { type: Boolean, default: false },
});

const emit = defineEmits(["begin"]);

// Half a minute a question is an honest average for mixed surveys, and an
// estimate that runs long is kinder than one that runs short.
const minutes = computed(() => {
	if (props.survey.is_time_limited) return null;
	const count = props.survey.question_count || 0;
	return count ? Math.max(1, Math.round(count / 2)) : null;
});
</script>

<template>
	<section class="survey-intro">
		<span v-if="survey.is_certification" class="survey-badge">Certification</span>
		<h1 class="survey-intro__title">{{ survey.title }}</h1>
		<div v-if="survey.description" class="survey-intro__description" v-html="survey.description"></div>

		<ul class="survey-facts">
			<li v-if="survey.question_count" class="survey-facts__item">
				<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 5h12M4 10h12M4 15h8" /></svg>
				{{ survey.question_count }} question{{ survey.question_count === 1 ? "" : "s" }}
			</li>
			<li v-if="minutes" class="survey-facts__item">
				<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" /><path d="M10 6v4l3 2" /></svg>
				About {{ minutes }} min
			</li>
			<li v-if="survey.is_time_limited" class="survey-facts__item survey-facts__item--strong">
				<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" /><path d="M10 6v4l3 2" /></svg>
				{{ survey.time_limit }} minute time limit
			</li>
			<li v-if="survey.is_scored" class="survey-facts__item">
				<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-8" /></svg>
				Scored
			</li>
		</ul>

		<div class="survey-intro__actions">
			<button type="button" class="survey-btn survey-btn--primary survey-btn--large" :disabled="busy" @click="emit('begin')">
				{{ survey.is_certification ? "Start certification" : "Start" }}
				<svg class="survey-btn__arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11m-4-4 4 4-4 4" /></svg>
			</button>
			<span class="survey-hint">press <kbd>Enter ↵</kbd></span>
		</div>
	</section>
</template>
