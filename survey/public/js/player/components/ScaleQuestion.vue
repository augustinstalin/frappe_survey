<script setup>
import { computed } from "vue";

const props = defineProps({
	question: { type: Object, required: true },
	modelValue: { type: [Number, String, null], default: null },
});

const emit = defineEmits(["update:modelValue"]);

const hasLabels = computed(() =>
	Boolean(
		props.question.scale_min_label ||
			props.question.scale_mid_label ||
			props.question.scale_max_label
	)
);
</script>

<template>
	<div class="survey-scale" role="radiogroup">
		<div class="survey-scale__buttons">
			<label
				v-for="step in question.scale_values || []"
				:key="step"
				class="survey-scale__item"
				:for="`scale-${question.id}-${step}`"
			>
				<input
					type="radio"
					class="survey-scale__input"
					:id="`scale-${question.id}-${step}`"
					:name="`q-${question.id}`"
					:value="step"
					:checked="String(modelValue) === String(step)"
					@change="emit('update:modelValue', Number(step))"
				/>
				<span class="survey-scale__value">{{ step }}</span>
			</label>
		</div>

		<div v-if="hasLabels" class="survey-scale__labels">
			<span>{{ question.scale_min_label || "" }}</span>
			<span>{{ question.scale_mid_label || "" }}</span>
			<span>{{ question.scale_max_label || "" }}</span>
		</div>
	</div>
</template>
