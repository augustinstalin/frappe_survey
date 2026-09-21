<!--
	The section trail, on "One Page Per Section" only.

	A dot per section: filled for done, outlined for still to come, ringed for
	the current one, and marked when a section still owes a mandatory answer.
	Only completed sections are clickable — jumping forward would let somebody
	skip past questions they have not seen, which on a scored survey is
	cheating and on any other is just confusing.
-->
<script setup>
defineProps({
	trail: { type: Array, required: true },
	busy: { type: Boolean, default: false },
});

const emit = defineEmits(["jump"]);
</script>

<template>
	<nav class="survey-breadcrumb" :aria-label="'Sections'">
		<ol class="survey-breadcrumb__list">
			<li
				v-for="step in trail"
				:key="step.id"
				class="survey-breadcrumb__step"
				:class="[`is-${step.state}`, { 'is-pending': step.pending }]"
			>
				<button
					v-if="step.can_jump"
					type="button"
					class="survey-breadcrumb__button"
					:disabled="busy"
					:title="step.pending ? `${step.title} — still needs an answer` : step.title"
					@click="emit('jump', step.id)"
				>
					<span class="survey-breadcrumb__dot" aria-hidden="true"></span>
					<span class="survey-breadcrumb__label">{{ step.title }}</span>
				</button>

				<span
					v-else
					class="survey-breadcrumb__button is-static"
					:aria-current="step.state === 'current' ? 'step' : null"
					:title="step.pending ? `${step.title} — still needs an answer` : step.title"
				>
					<span class="survey-breadcrumb__dot" aria-hidden="true"></span>
					<span class="survey-breadcrumb__label">{{ step.title }}</span>
				</span>
			</li>
		</ol>
	</nav>
</template>
