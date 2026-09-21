"""One-click sample surveys.

Mirrors Odoo's four starter templates: a feedback form, a certification, a
live quiz and an empty survey. They exist so a new install has something to
open, and so the builder's features are discoverable without reading docs.

Called from the Survey list view ("Load a sample"). Everything is created
with `ignore_permissions=False` on purpose — a user who cannot create a
survey should not be able to create one this way either.
"""

import frappe
from frappe import _

from survey.constants import (
	ACCESS_INVITED,
	MATRIX_SINGLE,
	PAGINATION_PER_QUESTION,
	PROGRESS_NUMBER,
	SCORING_WITH_ANSWERS,
	STATUS_DRAFT,
	SURVEY_TYPE_ASSESSMENT,
	SURVEY_TYPE_CUSTOM,
	SURVEY_TYPE_LIVE_SESSION,
	SURVEY_TYPE_SURVEY,
	TYPE_MATRIX,
	TYPE_MULTIPLE_CHOICE,
	TYPE_NUMERIC,
	TYPE_SCALE,
	TYPE_SINGLE_CHOICE,
	TYPE_SHORT_TEXT,
)
from survey.constants import SEQUENCE_STEP


@frappe.whitelist()
def load_sample(kind: str = "survey") -> str:
	"""Create one sample survey and return its name."""
	frappe.has_permission("Survey", "create", throw=True)

	builders = {
		"survey": build_feedback_form,
		"assessment": build_certification,
		"live_session": build_live_quiz,
		"custom": build_empty_survey,
	}
	builder = builders.get(kind)
	if not builder:
		frappe.throw(_("Unknown sample: {0}").format(kind))

	return builder()


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------


def build_feedback_form() -> str:
	survey = _create_survey(
		title=_("Feedback Form"),
		survey_type=SURVEY_TYPE_SURVEY,
		description=_(
			"<p>Please complete this very short survey to let us know how satisfied "
			"you are with our products.</p><p>Your responses will help us improve "
			"our range to serve you even better.</p>"
		),
		end_message=_("<p>Thank you very much for your feedback. We highly value your opinion!</p>"),
		progress_display=PROGRESS_NUMBER,
	)

	_add_question(
		survey,
		title=_("How frequently do you use our products?"),
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=[
			_("Often (1-3 times per week)"),
			_("Rarely (1-3 times per month)"),
			_("Never (less than once a month)"),
		],
	)
	_add_question(
		survey,
		title=_("How many orders did you place in the last 6 months?"),
		question_type=TYPE_NUMERIC,
	)
	_add_question(
		survey,
		title=_("How likely are you to recommend us to a friend?"),
		question_type=TYPE_SCALE,
		scale_min=0,
		scale_max=10,
		scale_min_label=_("Not likely at all"),
		scale_mid_label=_("Neutral"),
		scale_max_label=_("Extremely likely"),
	)
	_add_question(
		survey,
		title=_("How would you rate the following?"),
		question_type=TYPE_MATRIX,
		matrix_subtype=MATRIX_SINGLE,
		options=[_("Poor"), _("Acceptable"), _("Good"), _("Excellent")],
		matrix_rows=[_("Product quality"), _("Delivery speed"), _("Customer support")],
	)
	_add_question(
		survey,
		title=_("Anything else you would like to tell us?"),
		question_type="Multiple Line Text",
		placeholder=_("Your thoughts..."),
	)

	return survey.name


def build_certification() -> str:
	"""A scored, invite-only certification that also demonstrates skip logic."""
	survey = _create_survey(
		title=_("Product Certification"),
		survey_type=SURVEY_TYPE_ASSESSMENT,
		access_mode=ACCESS_INVITED,
		scoring_type=SCORING_WITH_ANSWERS,
		passing_score=80,
		is_certification=1,
		is_time_limited=1,
		time_limit=20,
		description=_(
			"<p>This certification has a 20-minute time limit and requires 80% to pass.</p>"
		),
		end_message=_("<p>Thank you for taking this certification.</p>"),
	)

	_add_question(
		survey,
		title=_("What is your name?"),
		question_type=TYPE_SHORT_TEXT,
		save_as_nickname=1,
		mandatory=1,
	)

	experience = _add_question(
		survey,
		title=_("Have you used the product before?"),
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=[_("Yes"), _("No")],
	)

	# Skip logic: the follow-up is only shown to people who answered "Yes".
	yes_option = frappe.db.get_value(
		"Survey Question Option", {"question": experience.name, "label": _("Yes")}, "name"
	)

	_add_question(
		survey,
		title=_("How long have you been using it?"),
		question_type=TYPE_SINGLE_CHOICE,
		options=[_("Less than a year"), _("One to three years"), _("More than three years")],
		triggering_options=[yes_option],
	)

	_add_question(
		survey,
		title=_("Which of these are supported file formats?"),
		question_type=TYPE_MULTIPLE_CHOICE,
		mandatory=1,
		options=[
			{"label": _("CSV"), "is_correct": 1, "score": 2},
			{"label": _("XLSX"), "is_correct": 1, "score": 2},
			{"label": _("DOCX"), "is_correct": 0, "score": -1},
		],
	)
	_add_question(
		survey,
		title=_("In which year was the company founded?"),
		question_type=TYPE_NUMERIC,
		correct_number=2010,
		score=4,
	)

	return survey.name


def build_live_quiz() -> str:
	survey = _create_survey(
		title=_("Live Quiz"),
		survey_type=SURVEY_TYPE_LIVE_SESSION,
		scoring_type=SCORING_WITH_ANSWERS,
		pagination=PAGINATION_PER_QUESTION,
		description=_("<p>Answer as fast as you can. The quickest correct answers score highest.</p>"),
	)

	_add_question(
		survey,
		title=_("Pick a nickname"),
		question_type=TYPE_SHORT_TEXT,
		save_as_nickname=1,
		mandatory=1,
	)
	_add_question(
		survey,
		title=_("Which planet is closest to the sun?"),
		question_type=TYPE_SINGLE_CHOICE,
		options=[
			{"label": _("Mercury"), "is_correct": 1, "score": 10},
			{"label": _("Venus"), "score": 0},
			{"label": _("Mars"), "score": 0},
		],
	)
	_add_question(
		survey,
		title=_("How many continents are there?"),
		question_type=TYPE_SINGLE_CHOICE,
		options=[
			{"label": "5", "score": 0},
			{"label": "6", "score": 0},
			{"label": "7", "is_correct": 1, "score": 10},
		],
	)

	return survey.name


def build_empty_survey() -> str:
	return _create_survey(title=_("New Survey"), survey_type=SURVEY_TYPE_CUSTOM).name


# ----------------------------------------------------------------------
# Construction helpers
# ----------------------------------------------------------------------


def _create_survey(**values):
	values.setdefault("status", STATUS_DRAFT)
	doc = frappe.get_doc({"doctype": "Survey", **values})
	doc.insert()
	return doc


def _add_question(
	survey,
	options: list | None = None,
	matrix_rows: list[str] | None = None,
	triggering_options: list[str] | None = None,
	**values,
):
	"""Create one question with its options, rows and triggers."""
	sequence = values.pop("sequence", None)
	if sequence is None:
		sequence = (
			frappe.db.get_value(
				"Survey Question", {"survey": survey.name}, "sequence", order_by="sequence desc"
			)
			or 0
		) + SEQUENCE_STEP

	question = frappe.get_doc(
		{
			"doctype": "Survey Question",
			"survey": survey.name,
			"sequence": sequence,
			**values,
		}
	)

	if triggering_options:
		for option_name in triggering_options:
			question.append("triggering_options", {"option": option_name})

	question.insert()

	for index, option in enumerate(options or [], start=1):
		payload = {"label": option} if isinstance(option, str) else dict(option)
		frappe.get_doc(
			{
				"doctype": "Survey Question Option",
				"question": question.name,
				"sequence": index * SEQUENCE_STEP,
				**payload,
			}
		).insert()

	for index, row in enumerate(matrix_rows or [], start=1):
		frappe.get_doc(
			{
				"doctype": "Survey Question Option",
				"question": question.name,
				"is_matrix_row": 1,
				"sequence": index * SEQUENCE_STEP,
				"label": row,
			}
		).insert()

	# `is_scored` is pushed onto the question by each option's own
	# `sync_parent_survey`, so the in-memory copy here is stale.
	question.reload()

	return question


def _add_section(survey, title: str, **values):
	sequence = (
		frappe.db.get_value(
			"Survey Question", {"survey": survey.name}, "sequence", order_by="sequence desc"
		)
		or 0
	) + SEQUENCE_STEP

	return frappe.get_doc(
		{
			"doctype": "Survey Question",
			"survey": survey.name,
			"is_section": 1,
			"title": title,
			"sequence": sequence,
			**values,
		}
	).insert()
