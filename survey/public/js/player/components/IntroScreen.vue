<script setup>
defineProps({
	survey: { type: Object, required: true },
	busy: { type: Boolean, default: false },
});

const emit = defineEmits(["begin"]);
</script>

<template>
	<div class="survey-intro">
		<h1 class="survey-intro__title">{{ survey.title }}</h1>
		<div v-if="survey.description" class="survey-intro__description" v-html="survey.description"></div>

		<p v-if="survey.is_time_limited" class="survey-intro__meta">
			You have <strong>{{ survey.time_limit }} minutes</strong> to complete this.
		</p>

		<div class="survey-intro__actions">
			<button
				type="button"
				class="survey-btn survey-btn--primary"
				:disabled="busy"
				@click="emit('begin')"
			>
				{{ survey.is_certification ? "Start certification" : "Start survey" }}
			</button>
			<span class="survey-hint">or press Enter</span>
		</div>
	</div>
</template>
