<script setup>
defineProps({
	progress: { type: Object, required: true },
});
</script>

<template>
	<div class="survey-progress">
		<div class="survey-progress__track">
			<div class="survey-progress__fill" :style="{ width: `${progress.percent}%` }"></div>
		</div>
		<span class="survey-progress__label">
			{{ progress.mode === "Number" ? `${progress.current} / ${progress.total}` : `${progress.percent}%` }}
		</span>
	</div>
</template>
