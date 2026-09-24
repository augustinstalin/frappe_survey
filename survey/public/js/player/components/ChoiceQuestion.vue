<!--
	Single and multiple choice, with optional image answers and letter keys.

	Both share this component because the only real difference is whether
	picking one option unpicks the last.
-->
<script setup>
import { computed, ref } from "vue";

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

// Image zoom: a full-screen view of one answer image, closed by click or Esc.
const zoomed = ref(null);

function zoom(option, event) {
	// The image sits inside the option's <label>; without this, opening the
	// zoom would also pick the answer.
	event.preventDefault();
	event.stopPropagation();
	zoomed.value = option;
}

function onZoomKey(event) {
	if (event.key === "Escape") zoomed.value = null;
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
			<span v-if="option.image" class="survey-choice__media">
				<img class="survey-choice__image" :src="option.image" :alt="option.label || ''" loading="lazy" />
				<button type="button" class="survey-choice__zoom" aria-label="Enlarge image" @click="zoom(option, $event)">
					<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5" /><path d="m13 13 4 4M9 7v4M7 9h4" /></svg>
				</button>
			</span>
			<span v-if="option.label" class="survey-choice__label">{{ option.label }}</span>
			<svg class="survey-choice__tick" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 10.5 3.5 3.5L15 7" /></svg>
		</label>

		<Teleport to="body">
			<div
				v-if="zoomed"
				class="survey-lightbox"
				role="dialog"
				aria-modal="true"
				tabindex="-1"
				@click="zoomed = null"
				@keydown="onZoomKey"
				:ref="(node) => node && node.focus()"
			>
				<img :src="zoomed.image" :alt="zoomed.label || ''" />
			</div>
		</Teleport>
	</div>
</template>
