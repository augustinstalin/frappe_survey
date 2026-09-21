<!--
	Single and multiple choice, with optional image answers and letter keys.

	Both share this component because the only real difference is whether
	picking one option unpicks the last.
-->
<script setup>
import { computed } from "vue";

const props = defineProps({
	question: { type: Object, required: true },
	modelValue: { type: [String, Array, null], default: null },
});

const emit = defineEmits(["update:modelValue"]);

// `option.key` is shown next to each option; the letter doubles as the
// keyboard shortcut hint that App.vue acts on.
const multiple = computed(() => props.question.question_type === "Multiple Choice");
const hasImages = computed(() => (props.question.options || []).some((option) => option.image));

function isPicked(option) {
	return multiple.value
		? (props.modelValue || []).includes(option.id)
		: props.modelValue === option.id;
}

function pick(option) {
	if (!multiple.value) {
		emit("update:modelValue", option.id);
		return;
	}

	const current = [].concat(props.modelValue || []);
	const at = current.indexOf(option.id);
	if (at === -1) current.push(option.id);
	else current.splice(at, 1);
	emit("update:modelValue", current);
}

// Exposed so the keyboard shortcut handler can drive this without touching
// the DOM the way the old player did.
defineExpose({ pick, isPicked });
</script>

<template>
	<div
		class="survey-choices"
		:class="{ 'survey-choices--grid': hasImages }"
		:role="multiple ? 'group' : 'radiogroup'"
		:aria-labelledby="`question-${question.id}`"
	>
		<label
			v-for="option in question.options || []"
			:key="option.id"
			class="survey-choice"
			:for="`opt-${option.id}`"
		>
			<input
				class="survey-choice__input"
				:type="multiple ? 'checkbox' : 'radio'"
				:id="`opt-${option.id}`"
				:name="`q-${question.id}`"
				:value="option.id"
				:checked="isPicked(option)"
				:data-option="option.id"
				@change="pick(option)"
			/>
			<span v-if="option.key" class="survey-choice__key">{{ option.key }}</span>
			<img
				v-if="option.image"
				class="survey-choice__image"
				:src="option.image"
				:alt="option.label || ''"
			/>
			<span v-if="option.label" class="survey-choice__label">{{ option.label }}</span>
		</label>
	</div>
</template>
