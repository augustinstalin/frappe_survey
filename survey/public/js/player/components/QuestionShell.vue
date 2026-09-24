<!--
	The chrome every question shares: title, required marker, description,
	the optional comment field and the error slot. The control itself is a
	slot, so a renderer only has to know about its own inputs.
-->
<script setup>
const props = defineProps({
	question: { type: Object, required: true },
	comment: { type: String, default: "" },
	error: { type: String, default: "" },
	number: { type: Number, default: 0 },
});

const emit = defineEmits(["update:comment"]);

// `description` is rendered with v-html: it is author-written content that
// Frappe sanitised on the way in, and the one place the player renders HTML.
</script>

<template>
	<div
		class="survey-question"
		:class="{ 'has-error': error }"
		:data-question="question.id"
		:data-type="question.question_type"
		:id="`question-${question.id}`"
	>
		<div class="survey-question__header">
			<h2 class="survey-question__title">
				<span v-if="number" class="survey-question__number" aria-hidden="true">{{ number }}<svg viewBox="0 0 20 20"><path d="M4 10h11m-4-4 4 4-4 4" /></svg></span>
				{{ question.title }}
				<span v-if="question.mandatory" class="survey-question__required" aria-label="required">*</span>
			</h2>
			<div
				v-if="question.description"
				class="survey-question__description"
				v-html="question.description"
			></div>
		</div>

		<slot></slot>

		<div v-if="question.allow_comments" class="survey-question__comment">
			<label class="survey-question__comment-label" :for="`comment-${question.id}`">
				{{ question.comments_message || "If other, please specify:" }}
			</label>
			<input
				type="text"
				class="survey-input"
				:id="`comment-${question.id}`"
				:value="comment"
				@input="emit('update:comment', $event.target.value)"
			/>
		</div>

		<div class="survey-question__error" :class="{ 'is-visible': error }" role="alert" aria-live="polite">
			{{ error }}
		</div>
	</div>
</template>
