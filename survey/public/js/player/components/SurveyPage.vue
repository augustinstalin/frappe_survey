<!-- One screen of questions, whichever pagination the survey uses. -->
<script setup>
import QuestionRenderer from "./QuestionRenderer.vue";

defineProps({
	page: { type: Object, required: true },
	questions: { type: Array, required: true },
	answers: { type: Object, required: true },
	errors: { type: Object, required: true },
	// One Page Per Question: the section is context, not the headline.
	compact: { type: Boolean, default: false },
	position: { type: Number, default: 0 },
});

const emit = defineEmits(["update:answer", "submit"]);
</script>

<template>
	<form class="survey-page" novalidate @submit.prevent="emit('submit')">
		<div v-if="page.section" class="survey-section" :class="{ 'survey-section--compact': compact }">
			<h2 class="survey-section__title">{{ page.section.title }}</h2>
			<div
				v-if="page.section.description"
				class="survey-section__description"
				v-html="page.section.description"
			></div>
		</div>

		<QuestionRenderer
			v-for="(question, index) in questions"
			:key="question.id"
			:question="question"
			:number="compact && position ? position : 0"
			:answer="answers[question.id] || { value: null, comment: '' }"
			:error="errors[question.id] || ''"
			:style="{ '--stagger': `${index * 60}ms` }"
			@update:answer="emit('update:answer', question.id, $event)"
		/>
	</form>
</template>
