<!--
	Rendered twice: a table on wide screens, one card per row on narrow ones.
	Odoo keeps the table and lets it scroll sideways, which is the worst part
	of taking one of its surveys on a phone.

	Both layouts bind to the same answer object. The old player had to work
	out which layout was visible before reading the DOM, because reading the
	hidden one would overwrite what the visible one said; with a single source
	of truth that whole class of bug is gone.
-->
<script setup>
import { computed } from "vue";

const props = defineProps({
	question: { type: Object, required: true },
	modelValue: { type: Object, default: () => ({}) },
});

const emit = defineEmits(["update:modelValue"]);

const single = computed(() => props.question.matrix_subtype !== "Multiple Choices Per Row");
const inputType = computed(() => (single.value ? "radio" : "checkbox"));

function isPicked(rowId, columnId) {
	return (props.modelValue?.[rowId] || []).includes(columnId);
}

function pick(rowId, columnId) {
	const next = { ...(props.modelValue || {}) };

	if (single.value) {
		next[rowId] = [columnId];
	} else {
		const current = [...(next[rowId] || [])];
		const at = current.indexOf(columnId);
		if (at === -1) current.push(columnId);
		else current.splice(at, 1);
		next[rowId] = current;
	}

	emit("update:modelValue", next);
}
</script>

<template>
	<div class="survey-matrix__wrapper">
		<table class="survey-matrix survey-matrix--table">
			<thead>
				<tr>
					<th scope="col"></th>
					<th v-for="column in question.options || []" :key="column.id" scope="col">
						{{ column.label }}
					</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="row in question.rows || []" :key="row.id">
					<th scope="row">{{ row.label }}</th>
					<td v-for="column in question.options || []" :key="column.id">
						<input
							:type="inputType"
							:name="`q-${question.id}-${row.id}`"
							:value="column.id"
							:aria-label="`${row.label}: ${column.label}`"
							:checked="isPicked(row.id, column.id)"
							@change="pick(row.id, column.id)"
						/>
					</td>
				</tr>
			</tbody>
		</table>

		<div class="survey-matrix survey-matrix--cards">
			<fieldset v-for="row in question.rows || []" :key="row.id" class="survey-matrix__card">
				<legend class="survey-matrix__row-label">{{ row.label }}</legend>
				<div class="survey-matrix__chips">
					<label
						v-for="column in question.options || []"
						:key="column.id"
						class="survey-matrix__chip"
						:for="`m-${question.id}-${row.id}-${column.id}`"
					>
						<input
							:type="inputType"
							:id="`m-${question.id}-${row.id}-${column.id}`"
							:name="`qc-${question.id}-${row.id}`"
							:value="column.id"
							:checked="isPicked(row.id, column.id)"
							@change="pick(row.id, column.id)"
						/>
						<span>{{ column.label }}</span>
					</label>
				</div>
			</fieldset>
		</div>
	</div>
</template>
