<!-- Dispatch by question type. One place knows the mapping. -->
<script setup>
import { computed } from "vue";

import ChoiceQuestion from "./ChoiceQuestion.vue";
import DateQuestion from "./DateQuestion.vue";
import MatrixQuestion from "./MatrixQuestion.vue";
import NumericQuestion from "./NumericQuestion.vue";
import QuestionShell from "./QuestionShell.vue";
import ScaleQuestion from "./ScaleQuestion.vue";
import TextQuestion from "./TextQuestion.vue";

const RENDERERS = {
	"Single Choice": ChoiceQuestion,
	"Multiple Choice": ChoiceQuestion,
	"Single Line Text": TextQuestion,
	"Multiple Line Text": TextQuestion,
	Numeric: NumericQuestion,
	Scale: ScaleQuestion,
	Date: DateQuestion,
	Datetime: DateQuestion,
	Matrix: MatrixQuestion,
};

const props = defineProps({
	question: { type: Object, required: true },
	answer: { type: Object, required: true },
	error: { type: String, default: "" },
	// 1-based position shown as a lead-in on one-question-per-page layouts.
	number: { type: Number, default: 0 },
});

const emit = defineEmits(["update:answer"]);

const control = computed(() => RENDERERS[props.question.question_type] || null);

function setValue(value) {
	emit("update:answer", { ...props.answer, value });
}

function setComment(comment) {
	emit("update:answer", { ...props.answer, comment });
}
</script>

<template>
	<QuestionShell
		:question="question"
		:comment="answer.comment"
		:error="error"
		:number="number"
		@update:comment="setComment"
	>
		<component
			v-if="control"
			:is="control"
			:question="question"
			:model-value="answer.value"
			@update:model-value="setValue"
		/>
		<div v-else class="survey-question__unsupported">Unsupported question type.</div>
	</QuestionShell>
</template>
