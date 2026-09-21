<script setup>
defineProps({
	question: { type: Object, required: true },
	modelValue: { type: [Number, String, null], default: null },
});

// inputmode="decimal" gets the numeric keypad on a phone.
const emit = defineEmits(["update:modelValue"]);
</script>

<template>
	<input
		type="number"
		step="any"
		inputmode="decimal"
		class="survey-input"
		:placeholder="question.placeholder || ''"
		:value="modelValue === null || modelValue === undefined ? '' : modelValue"
		@input="emit('update:modelValue', $event.target.value)"
	/>
</template>
