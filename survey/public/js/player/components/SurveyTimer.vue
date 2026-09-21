<script setup>
import { computed, onUnmounted, ref, watch } from "vue";

const props = defineProps({
	timer: { type: Object, required: true },
});

const emit = defineEmits(["expired"]);

const left = ref(props.timer.time_left);
let handle = null;
let anchor = 0;
let startedWith = 0;

/**
 * Count down from the *duration* the server sent, anchored to this browser's
 * own clock at the moment it arrived.
 *
 * Only deltas of `Date.now()` are ever used, never its absolute value against
 * a server timestamp, so a machine whose clock is wrong — or simply in
 * another timezone — still counts down correctly. Every page turn brings a
 * fresh `time_left`, which re-anchors this and corrects any drift.
 *
 * `Date.now()` rather than a tick counter because a backgrounded tab throttles
 * its timers: the interval may fire once a minute, but the arithmetic still
 * comes out right when it does.
 */
function restart(seconds) {
	stop();
	startedWith = seconds;
	anchor = Date.now();
	left.value = seconds;

	if (seconds <= 0) {
		emit("expired");
		return;
	}

	handle = setInterval(tick, 250);
}

function tick() {
	const elapsed = (Date.now() - anchor) / 1000;
	left.value = Math.max(startedWith - elapsed, 0);

	if (left.value <= 0) {
		stop();
		emit("expired");
	}
}

function stop() {
	if (handle) clearInterval(handle);
	handle = null;
}

watch(() => props.timer.time_left, restart, { immediate: true });
onUnmounted(stop);

const warning = computed(() => left.value <= (props.timer.warn_at || 60));

const display = computed(() => {
	const total = Math.ceil(left.value);
	const minutes = Math.floor(total / 60);
	const seconds = total % 60;
	return `${minutes}:${String(seconds).padStart(2, "0")}`;
});

const label = computed(() =>
	warning.value ? `${display.value} remaining — nearly out of time` : `${display.value} remaining`
);
</script>

<template>
	<span
		class="survey-timer"
		:class="{ 'is-warning': warning }"
		role="timer"
		aria-live="off"
		:aria-label="label"
	>
		<svg class="survey-timer__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
			<circle cx="8" cy="9" r="6" fill="none" stroke="currentColor" stroke-width="1.5" />
			<path d="M8 6v3.2l2 1.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
			<path d="M6 1.5h4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
		</svg>
		<span class="survey-timer__value">{{ display }}</span>
	</span>
</template>
