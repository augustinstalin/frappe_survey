<!-- One screen of questions, whichever pagination the survey uses. -->
<script setup>
import { computed } from "vue";

import QuestionRenderer from "./QuestionRenderer.vue";

const props = defineProps({
	page: { type: Object, required: true },
	questions: { type: Array, required: true },
	answers: { type: Object, required: true },
	errors: { type: Object, required: true },
	submitLabel: { type: String, default: "continue" },
	skippedRemaining: { type: Number, default: 0 },
	busy: { type: Boolean, default: false },
});

const LABELS = {
	continue: "Continue",
	submit: "Submit",
	// The server decides this one: it knows a mandatory question is still
	// blank somewhere, so "Submit" would be a lie about what the button does.
	next_skipped: "Next unanswered",
};

const label = computed(() => LABELS[props.submitLabel] || LABELS.continue);
const isSubmit = computed(() => props.submitLabel === "submit");

const emit = defineEmits(["update:answer", "submit"]);
</script>

<template>
	<form class="survey-page" @submit.prevent="emit('submit')">
		<div v-if="page.section" class="survey-section">
			<h2 class="survey-section__title">{{ page.section.title }}</h2>
			<div
				v-if="page.section.description"
				class="survey-section__description"
				v-html="page.section.description"
			></div>
		</div>

		<QuestionRenderer
			v-for="question in questions"
			:key="question.id"
			:question="question"
			:answer="answers[question.id] || { value: null, comment: '' }"
			:error="errors[question.id] || ''"
			@update:answer="emit('update:answer', question.id, $event)"
		/>

		<div class="survey-actions">
			<button
				type="submit"
				class="survey-btn"
				:class="isSubmit ? 'survey-btn--submit' : 'survey-btn--primary'"
				:disabled="busy"
			>
				{{ label }}
			</button>
			<span v-if="skippedRemaining" class="survey-hint survey-hint--pending">
				{{ skippedRemaining }} question{{ skippedRemaining === 1 ? "" : "s" }} still need an answer
			</span>
			<span v-else class="survey-hint">or press Enter</span>
		</div>
	</form>
</template>
