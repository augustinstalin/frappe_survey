<!-- Single-line and multi-line text. -->
<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { autoGrow } from "../dom.js";

const props = defineProps({
	question: { type: Object, required: true },
	modelValue: { type: [String, null], default: null },
});

const emit = defineEmits(["update:modelValue"]);

const textarea = ref(null);
const long = computed(() => props.question.question_type === "Multiple Line Text");

const maxLength = computed(() =>
	props.question.validate_entry && props.question.max_length ? props.question.max_length : null
);

function onInput(event) {
	emit("update:modelValue", event.target.value);
	if (long.value) autoGrow(event.target);
}

onMounted(() => nextTick(() => autoGrow(textarea.value)));
watch(() => props.modelValue, () => nextTick(() => autoGrow(textarea.value)));
</script>

<template>
	<textarea
		v-if="long"
		ref="textarea"
		class="survey-input survey-input--textarea"
		rows="3"
		:placeholder="question.placeholder || ''"
		:value="modelValue || ''"
		@input="onInput"
	></textarea>

	<input
		v-else
		class="survey-input"
		:type="question.validate_email ? 'email' : 'text'"
		:inputmode="question.validate_email ? 'email' : null"
		:placeholder="question.placeholder || ''"
		:maxlength="maxLength"
		:value="modelValue || ''"
		@input="onInput"
	/>
</template>
