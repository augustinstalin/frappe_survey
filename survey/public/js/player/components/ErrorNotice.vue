<script setup>
defineProps({
	message: { type: String, default: "" },
});
</script>

<template>
	<div class="survey-notice survey-notice--error">
		<h2 class="survey-notice__title">{{ message || "Something went wrong." }}</h2>
	</div>
</template>
