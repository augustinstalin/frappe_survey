<script setup>
defineProps({
	result: { type: Object, default: null },
	endMessage: { type: String, default: "" },
	timedOut: { type: Boolean, default: false },
});
</script>

<template>
	<div class="survey-done">
		<p v-if="timedOut" class="survey-done__timeout">
			Your time ran out, so the survey was submitted with the answers you had given.
		</p>

		<h1 class="survey-done__title">
			{{ result ? `You scored ${result.percentage}%` : "Thank you!" }}
		</h1>

		<p
			v-if="result"
			class="survey-done__verdict"
			:class="result.passed ? 'is-passed' : 'is-failed'"
		>
			{{ result.passed ? "Congratulations, you passed." : "Unfortunately, you did not pass this time." }}
		</p>

		<div v-if="endMessage" class="survey-done__message" v-html="endMessage"></div>
	</div>
</template>
