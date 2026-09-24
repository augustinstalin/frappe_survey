<!-- A hairline pinned to the top of the viewport; the numbers live in the header. -->
<script setup>
defineProps({
	progress: { type: Object, required: true },
});
</script>

<template>
	<div
		class="survey-progress"
		role="progressbar"
		aria-valuemin="0"
		aria-valuemax="100"
		:aria-valuenow="progress.percent"
	>
		<div class="survey-progress__fill" :style="{ width: `${progress.percent}%` }"></div>
	</div>
</template>
