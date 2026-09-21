<!--
	Date and datetime. The native picker beats any JS calendar on a phone and
	costs nothing, so there is no widget here.
-->
<script setup>
import { computed } from "vue";

const props = defineProps({
	question: { type: Object, required: true },
	modelValue: { type: [String, null], default: null },
});

const emit = defineEmits(["update:modelValue"]);

const isDate = computed(() => props.question.question_type === "Date");
const bounds = computed(() => {
	if (!props.question.validate_entry) return { min: null, max: null };
	return isDate.value
		? { min: props.question.min_date, max: props.question.max_date }
		: { min: props.question.min_datetime, max: props.question.max_datetime };
});
</script>

<template>
	<input
		class="survey-input"
		:type="isDate ? 'date' : 'datetime-local'"
		:min="bounds.min"
		:max="bounds.max"
		:value="modelValue || ''"
		@input="emit('update:modelValue', $event.target.value)"
	/>
</template>
