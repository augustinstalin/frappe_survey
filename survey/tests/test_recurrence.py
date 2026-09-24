# Copyright (c) 2026, Bosco Soft Technologies and contributors
# See license.txt

"""The `Recurring` survey type: series/wave fields, `comparison_key`,
`duplicate_to_next_wave`, and the comparison API."""

import frappe
from frappe.tests import IntegrationTestCase

from survey.api import comparison, player
from survey.constants import STATUS_OPEN, SURVEY_TYPE_RECURRING, SURVEY_TYPE_SURVEY
from survey.tests.factories import make_option, make_question, make_survey


def open_survey(**values):
	values.setdefault("status", "Draft")
	return make_survey(**values)


def publish(survey):
	survey.reload()
	survey.status = STATUS_OPEN
	survey.save(ignore_permissions=True)
	return survey


def unique_series() -> str:
	"""A series name unique to this call, so tests exercising the (series,
	wave_date) uniqueness rule never collide with fixtures another test in
	the same run happens to have left behind."""
	return f"series-{frappe.generate_hash(length=8)}"


def recurring_survey(series: str, wave_label: str, wave_date: str, **values):
	return open_survey(
		survey_type=SURVEY_TYPE_RECURRING,
		series=series,
		wave_label=wave_label,
		wave_date=wave_date,
		**values,
	)


class TestRecurrenceFields(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_recurring_survey_needs_series_and_wave(self):
		with self.assertRaises(frappe.ValidationError):
			make_survey(survey_type=SURVEY_TYPE_RECURRING)

	def test_switching_away_from_recurring_clears_the_fields(self):
		survey = recurring_survey(unique_series(), "2025", "2025-01-01")

		survey.survey_type = SURVEY_TYPE_SURVEY
		survey.save()

		self.assertIsNone(survey.series)
		self.assertIsNone(survey.wave_label)
		self.assertIsNone(survey.wave_date)

	def test_two_waves_of_the_same_series_cannot_share_a_date(self):
		series = unique_series()
		recurring_survey(series, "2025", "2025-01-01")
		with self.assertRaises(frappe.ValidationError):
			recurring_survey(series, "2025 (again)", "2025-01-01")

	def test_different_series_may_reuse_the_same_date(self):
		recurring_survey(unique_series(), "2025", "2025-01-01")
		# No error: the uniqueness is per series, not global.
		recurring_survey(unique_series(), "2025", "2025-01-01")

	def test_recurrence_fields_lock_once_a_response_exists(self):
		survey = recurring_survey(unique_series(), "2025", "2025-01-01")
		make_question(survey, question_type="Single Line Text", title="Name?")
		publish(survey)

		token = player.start(survey.access_token)["response_token"]
		player.begin(survey.access_token, token)
		page = player.get_state(survey.access_token, token)["page"]
		player.submit_page(survey.access_token, token, page["id"], {page["questions"][0]["id"]: {"value": "Ada"}})

		survey.reload()
		survey.wave_label = "2025 (edited)"
		with self.assertRaises(frappe.ValidationError):
			survey.save()


class TestComparisonKey(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_comparison_key_is_refused_on_a_non_recurring_survey(self):
		survey = open_survey(survey_type=SURVEY_TYPE_SURVEY)
		with self.assertRaises(frappe.ValidationError):
			make_question(survey, question_type="Single Line Text", comparison_key="satisfaction")

	def test_comparison_key_is_allowed_on_a_recurring_survey(self):
		survey = recurring_survey(unique_series(), "2025", "2025-01-01")
		question = make_question(survey, question_type="Single Line Text", comparison_key="satisfaction")
		self.assertEqual(question.comparison_key, "satisfaction")

	def test_the_same_key_cannot_be_used_twice_on_one_survey(self):
		survey = recurring_survey(unique_series(), "2025", "2025-01-01")
		make_question(survey, question_type="Single Line Text", comparison_key="satisfaction")
		with self.assertRaises(frappe.ValidationError):
			make_question(survey, question_type="Single Line Text", comparison_key="satisfaction")


class TestDuplicateToNextWave(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.series = unique_series()
		self.survey = recurring_survey(self.series, "2025", "2025-01-01")
		self.gate = make_question(
			self.survey, question_type="Single Choice", title="Do you use our product daily?",
			comparison_key="daily_use",
		)
		self.yes = make_option(self.gate, "Yes")
		self.no = make_option(self.gate, "No")

		self.followup = make_question(
			self.survey,
			question_type="Single Line Text",
			title="What do you use it for?",
			comparison_key="use_case",
		)
		self.followup.append("triggering_options", {"option": self.yes.name})
		self.followup.save()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_refuses_on_a_non_recurring_survey(self):
		plain = open_survey(survey_type=SURVEY_TYPE_SURVEY)
		with self.assertRaises(frappe.ValidationError):
			plain.duplicate_to_next_wave("2026", "2026-01-01")

	def test_clones_questions_and_carries_the_comparison_key_forward(self):
		new_name = self.survey.duplicate_to_next_wave("2026", "2026-01-01")
		new_survey = frappe.get_doc("Survey", new_name)

		self.assertEqual(new_survey.series, self.series)
		self.assertEqual(new_survey.wave_label, "2026")
		self.assertNotEqual(new_survey.access_token, self.survey.access_token)
		self.assertEqual(new_survey.status, "Draft")

		questions = {q.comparison_key: q for q in frappe.get_all(
			"Survey Question",
			filters={"survey": new_name},
			fields=["name", "comparison_key", "title"],
		)}
		self.assertEqual(set(questions), {"daily_use", "use_case"})
		self.assertNotEqual(questions["daily_use"].name, self.gate.name)

	def test_remaps_a_cross_question_trigger_to_the_new_wave_own_options(self):
		new_name = self.survey.duplicate_to_next_wave("2026", "2026-01-01")

		new_gate = frappe.get_doc(
			"Survey Question", {"survey": new_name, "comparison_key": "daily_use"}
		)
		new_followup = frappe.get_doc(
			"Survey Question", {"survey": new_name, "comparison_key": "use_case"}
		)

		self.assertEqual(len(new_followup.triggering_options), 1)
		trigger_option = new_followup.triggering_options[0].option

		# The trigger must point at one of *this wave's own* options, never
		# at the source survey's — that's exactly what `validate_triggers`
		# would refuse to save if the remap were wrong.
		option_doc = frappe.get_doc("Survey Question Option", trigger_option)
		self.assertEqual(option_doc.question, new_gate.name)
		self.assertEqual(option_doc.label, "Yes")
		self.assertNotEqual(trigger_option, self.yes.name)

	def test_the_clone_does_not_claim_the_source_survey_badge(self):
		self.survey.give_badge = 0
		new_name = self.survey.duplicate_to_next_wave("2026", "2026-01-01")
		new_survey = frappe.get_doc("Survey", new_name)
		self.assertFalse(new_survey.give_badge)
		self.assertIsNone(new_survey.badge)


class TestComparisonApi(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.series = unique_series()

		self.wave_2025 = recurring_survey(self.series, "2025", "2025-01-01")
		q_2025 = make_question(
			self.wave_2025, question_type="Single Choice", title="Satisfied?", comparison_key="satisfaction"
		)
		self.happy_2025 = make_option(q_2025, "Yes")
		self.sad_2025 = make_option(q_2025, "No")
		publish(self.wave_2025)

		self.wave_2026 = recurring_survey(self.series, "2026", "2026-01-01")
		q_2026 = make_question(
			self.wave_2026,
			question_type="Single Choice",
			title="Are you satisfied with the product?",  # reworded, same key
			comparison_key="satisfaction",
		)
		self.happy_2026 = make_option(q_2026, "Yes")
		self.sad_2026 = make_option(q_2026, "No")
		publish(self.wave_2026)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _answer(self, survey, option):
		token = player.start(survey.access_token)["response_token"]
		player.begin(survey.access_token, token)
		page = player.get_state(survey.access_token, token)["page"]
		question_id = page["questions"][0]["id"]
		player.submit_page(survey.access_token, token, page["id"], {question_id: {"value": option}})

	def test_series_waves_are_ordered_by_wave_date(self):
		waves = comparison.get_series_waves(self.series)
		self.assertEqual([w.wave_label for w in waves], ["2025", "2026"])

	def test_list_comparison_keys_finds_the_shared_key(self):
		keys = comparison.list_comparison_keys(self.series)
		self.assertEqual([k["comparison_key"] for k in keys], ["satisfaction"])

	def test_comparison_data_tracks_the_reworded_question_across_waves(self):
		self._answer(self.wave_2025, self.happy_2025.name)
		self._answer(self.wave_2025, self.happy_2025.name)
		self._answer(self.wave_2025, self.sad_2025.name)

		self._answer(self.wave_2026, self.happy_2026.name)
		self._answer(self.wave_2026, self.happy_2026.name)
		self._answer(self.wave_2026, self.happy_2026.name)

		result = comparison.get_comparison_data(self.series, "satisfaction")
		by_wave = {row["wave_label"]: row for row in result["waves"]}

		self.assertEqual(by_wave["2025"]["response_count"], 3)
		yes_2025 = next(d for d in by_wave["2025"]["distribution"] if d["label"] == "Yes")
		self.assertAlmostEqual(yes_2025["percentage"], 66.7, places=1)

		self.assertEqual(by_wave["2026"]["response_count"], 3)
		yes_2026 = next(d for d in by_wave["2026"]["distribution"] if d["label"] == "Yes")
		self.assertEqual(yes_2026["percentage"], 100.0)

	def test_a_wave_missing_the_key_still_appears_with_no_question(self):
		other = recurring_survey(self.series, "2027", "2027-01-01")
		make_question(other, question_type="Single Line Text", title="Anything else?")

		result = comparison.get_comparison_data(self.series, "satisfaction")
		row_2027 = next(r for r in result["waves"] if r["wave_label"] == "2027")
		self.assertIsNone(row_2027["question"])
