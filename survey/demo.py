"""Three realistic surveys, for trying the app out and for manual QA.

Distinct from `samples.py`: those are the four one-click starters a user picks
from inside the builder, one per survey type, kept deliberately small. These
are full-size, and each one is built to exercise a different part of the
player:

* **Employee Engagement Pulse** (10 questions) — sections and a breadcrumb,
  with conditional follow-ups.
* **Product Knowledge Assessment** (15 questions) — a scored, *timed*
  certification, one question per page.
* **Customer Experience Survey** (20 questions) — roaming plus mandatory
  questions, which is what puts the skipped-question queue to work.

Run with:

    bench --site <site> execute survey.demo.create_demo_surveys
"""

import frappe

from survey.constants import (
	MATRIX_SINGLE,
	PAGINATION_PER_QUESTION,
	PAGINATION_PER_SECTION,
	SCORING_WITH_ANSWERS,
	STATUS_OPEN,
	TYPE_DATE,
	TYPE_LONG_TEXT,
	TYPE_MATRIX,
	TYPE_MULTIPLE_CHOICE,
	TYPE_NUMERIC,
	TYPE_SCALE,
	TYPE_SHORT_TEXT,
	TYPE_SINGLE_CHOICE,
)
from survey.samples import _add_question, _add_section, _create_survey


def create_demo_surveys() -> list[str]:
	"""Build all three and open them. Returns their names."""
	built = [
		build_engagement_pulse(),
		build_product_assessment(),
		build_customer_experience(),
	]

	names = []
	for survey in built:
		survey.reload()
		survey.status = STATUS_OPEN
		survey.save()
		names.append(survey.name)
		print(
			f"{survey.name}  {survey.title:34s} "
			f"{survey.question_count:>3} questions  /s/{survey.access_token}"
		)

	frappe.db.commit()
	return names


# ----------------------------------------------------------------------
# 1. Employee Engagement Pulse — 10 questions, sections, skip logic
# ----------------------------------------------------------------------


def build_engagement_pulse():
	survey = _create_survey(
		title="Employee Engagement Pulse",
		description=(
			"<p>A short quarterly check-in. Nothing here is attributed to you "
			"individually — results are reported by team, never by person.</p>"
		),
		end_message="<p>Thank you. This closes in a week; results go out the week after.</p>",
		pagination=PAGINATION_PER_SECTION,
		progress_display="Number",
		allow_roaming=1,
	)

	# -- Your work ----------------------------------------------------
	_add_section(
		survey,
		"Your work",
		description="<p>How the day to day feels at the moment.</p>",
	)
	_add_question(
		survey,
		title="How satisfied are you with your current role?",
		question_type=TYPE_SCALE,
		scale_min=1,
		scale_max=10,
		scale_min_label="Not at all",
		scale_mid_label="It varies",
		scale_max_label="Very",
		mandatory=1,
	)
	_add_question(
		survey,
		title="In a typical week, how many hours do you spend in meetings?",
		question_type=TYPE_NUMERIC,
		placeholder="e.g. 6",
		validate_entry=1,
		min_value=0,
		max_value=60,
		validation_error_message="Please enter somewhere between 0 and 60 hours.",
	)
	workload = _add_question(
		survey,
		title="How would you describe your workload?",
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=["Too light", "About right", "Slightly heavy", "Unsustainable"],
	)

	# The follow-up only appears for the two answers that warrant one.
	heavy = frappe.db.get_value(
		"Survey Question Option", {"question": workload.name, "label": "Slightly heavy"}, "name"
	)
	unsustainable = frappe.db.get_value(
		"Survey Question Option", {"question": workload.name, "label": "Unsustainable"}, "name"
	)
	_add_question(
		survey,
		title="What is taking up the most time?",
		question_type=TYPE_LONG_TEXT,
		description="<p>Only you and your manager's manager see free-text answers.</p>",
		triggering_options=[heavy, unsustainable],
	)

	# -- Your team ----------------------------------------------------
	_add_section(survey, "Your team", description="<p>The people you work with most.</p>")
	_add_question(
		survey,
		title="How much do you agree with each statement?",
		question_type=TYPE_MATRIX,
		matrix_subtype=MATRIX_SINGLE,
		mandatory=1,
		options=["Disagree", "Neutral", "Agree"],
		matrix_rows=[
			"I know what is expected of me",
			"I get useful feedback",
			"I can raise a concern safely",
			"Decisions are explained to me",
		],
	)
	_add_question(
		survey,
		title="How often do you get uninterrupted time to do deep work?",
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=["Most days", "A couple of times a week", "Rarely", "Never"],
	)
	_add_question(
		survey,
		title="Which of these would most improve your week?",
		question_type=TYPE_MULTIPLE_CHOICE,
		description="<p>Pick up to two.</p>",
		options=[
			"Fewer meetings",
			"Clearer priorities",
			"More focus time",
			"Better tooling",
			"More autonomy",
		],
	)

	# -- Looking ahead ------------------------------------------------
	_add_section(survey, "Looking ahead", description="<p>Two last ones.</p>")
	_add_question(
		survey,
		title="How likely are you to still be here in a year?",
		question_type=TYPE_SCALE,
		scale_min=0,
		scale_max=10,
		scale_min_label="Very unlikely",
		scale_max_label="Very likely",
		mandatory=1,
	)
	_add_question(
		survey,
		title="What is one thing we should stop doing?",
		question_type=TYPE_SHORT_TEXT,
		placeholder="One sentence is plenty",
		allow_comments=1,
		comments_message="Anything to add?",
	)
	_add_question(
		survey,
		title="When did you last take a full week off?",
		question_type=TYPE_DATE,
	)

	return survey


# ----------------------------------------------------------------------
# 2. Product Knowledge Assessment — 15 questions, timed and scored
# ----------------------------------------------------------------------


def build_product_assessment():
	survey = _create_survey(
		title="Product Knowledge Assessment",
		description=(
			"<p>Fifteen questions. You have <strong>15 minutes</strong>, and the "
			"timer keeps running if you close the tab. 60% or better passes.</p>"
		),
		end_message="<p>Your result is shown above and has been recorded.</p>",
		pagination=PAGINATION_PER_QUESTION,
		progress_display="Number",
		scoring_type=SCORING_WITH_ANSWERS,
		passing_score=60,
		is_certification=1,
		is_time_limited=1,
		time_limit=15,
	)

	def quiz(title, correct, wrong, score=2, **values):
		options = [{"label": correct, "is_correct": 1, "score": score}]
		options += [{"label": label, "score": 0} for label in wrong]
		return _add_question(
			survey,
			title=title,
			question_type=TYPE_SINGLE_CHOICE,
			mandatory=1,
			options=options,
			**values,
		)

	quiz(
		"Which plan includes priority support?",
		"Enterprise",
		["Starter", "Team", "All of them"],
	)
	quiz(
		"How long is the free trial?",
		"14 days",
		["7 days", "30 days", "There is no trial"],
	)
	quiz(
		"Where do customers change their billing address?",
		"Settings → Billing",
		["Settings → Profile", "The invoice PDF", "By emailing support"],
	)
	quiz(
		"Which of these is *not* included in the Starter plan?",
		"Single sign-on",
		["Email support", "Two seats", "The mobile app"],
	)
	quiz(
		"What happens to data when a subscription lapses?",
		"It is kept read-only for 90 days",
		["It is deleted immediately", "It is kept forever", "It is exported and emailed"],
	)
	quiz(
		"Which integration is available on every plan?",
		"Slack",
		["Salesforce", "SAP", "None of them"],
	)
	quiz(
		"How often are backups taken?",
		"Every six hours",
		["Hourly", "Daily", "Weekly"],
	)
	quiz(
		"Who can invite new members to a workspace?",
		"Owners and admins",
		["Anyone in the workspace", "Owners only", "Support, on request"],
	)

	_add_question(
		survey,
		title="Select every region we host data in.",
		question_type=TYPE_MULTIPLE_CHOICE,
		mandatory=1,
		options=[
			{"label": "EU (Frankfurt)", "is_correct": 1, "score": 2},
			{"label": "US (Virginia)", "is_correct": 1, "score": 2},
			{"label": "India (Mumbai)", "is_correct": 1, "score": 2},
			{"label": "Australia (Sydney)", "score": -2},
		],
	)
	_add_question(
		survey,
		title="What is the seat minimum on the Team plan?",
		question_type=TYPE_NUMERIC,
		mandatory=1,
		correct_number=3,
		score=2,
	)
	_add_question(
		survey,
		title="How many days of notice does a plan change need?",
		question_type=TYPE_NUMERIC,
		mandatory=1,
		correct_number=0,
		score=2,
		description="<p>Enter 0 if changes take effect immediately.</p>",
	)

	quiz(
		"Which status page do we publish incidents to?",
		"status.example.com",
		["The blog", "The in-app banner only", "We email affected customers only"],
	)
	quiz(
		"What is the target first-response time for Enterprise support?",
		"One hour",
		["Four hours", "One business day", "Best effort"],
	)

	_add_question(
		survey,
		title="Match each feature to the lowest plan that includes it.",
		question_type=TYPE_MATRIX,
		matrix_subtype=MATRIX_SINGLE,
		mandatory=1,
		options=["Starter", "Team", "Enterprise"],
		matrix_rows=["Audit log", "Shared inbox", "SSO", "API access"],
	)
	_add_question(
		survey,
		title="In your own words, how would you explain our pricing to a new customer?",
		question_type=TYPE_LONG_TEXT,
		mandatory=1,
		placeholder="Two or three sentences",
	)

	return survey


# ----------------------------------------------------------------------
# 3. Customer Experience Survey — 20 questions, roaming + mandatory
# ----------------------------------------------------------------------


def build_customer_experience():
	survey = _create_survey(
		title="Customer Experience Survey",
		description=(
			"<p>Twenty questions, about ten minutes. You can move back and forth "
			"freely, and skip anything you would rather come back to — we will "
			"bring you back to whatever is still required before you finish.</p>"
		),
		end_message="<p>Thank you. We read every one of these.</p>",
		pagination=PAGINATION_PER_SECTION,
		progress_display="Percentage",
		allow_roaming=1,
	)

	# -- About you ----------------------------------------------------
	_add_section(survey, "About you", description="<p>So we can group the answers.</p>")
	_add_question(
		survey,
		title="How long have you been a customer?",
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=["Less than 3 months", "3–12 months", "1–3 years", "More than 3 years"],
	)
	_add_question(
		survey,
		title="How many people at your organisation use us?",
		question_type=TYPE_NUMERIC,
		mandatory=1,
		validate_entry=1,
		min_value=1,
		max_value=100000,
	)
	_add_question(
		survey,
		title="Which describes your organisation best?",
		question_type=TYPE_SINGLE_CHOICE,
		options=["Startup", "Small business", "Mid-market", "Enterprise", "Public sector"],
	)
	_add_question(
		survey,
		title="What is your role?",
		question_type=TYPE_SHORT_TEXT,
		placeholder="e.g. Operations lead",
	)

	# -- The product --------------------------------------------------
	_add_section(survey, "The product", description="<p>How it works for you day to day.</p>")
	_add_question(
		survey,
		title="How likely are you to recommend us to a colleague?",
		question_type=TYPE_SCALE,
		scale_min=0,
		scale_max=10,
		scale_min_label="Not at all likely",
		scale_max_label="Extremely likely",
		mandatory=1,
	)
	_add_question(
		survey,
		title="How often do you use the product?",
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=["Several times a day", "Daily", "Weekly", "Monthly", "Rarely"],
	)
	_add_question(
		survey,
		title="Rate each area.",
		question_type=TYPE_MATRIX,
		matrix_subtype=MATRIX_SINGLE,
		mandatory=1,
		options=["Poor", "Fair", "Good", "Excellent"],
		matrix_rows=["Speed", "Reliability", "Ease of use", "Look and feel", "Mobile"],
	)
	_add_question(
		survey,
		title="Which features do you use regularly?",
		question_type=TYPE_MULTIPLE_CHOICE,
		options=["Reports", "Automations", "Integrations", "Mobile app", "API", "Exports"],
	)
	_add_question(
		survey,
		title="What is missing that you expected to find?",
		question_type=TYPE_LONG_TEXT,
		placeholder="Be as specific as you like",
	)
	_add_question(
		survey,
		title="How easy was it to get started?",
		question_type=TYPE_SCALE,
		scale_min=1,
		scale_max=5,
		scale_min_label="Very hard",
		scale_max_label="Very easy",
		mandatory=1,
	)

	# -- Support ------------------------------------------------------
	_add_section(survey, "Support", description="<p>Only if you have contacted us.</p>")
	contacted = _add_question(
		survey,
		title="Have you contacted support in the last six months?",
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=["Yes", "No"],
	)
	yes = frappe.db.get_value(
		"Survey Question Option", {"question": contacted.name, "label": "Yes"}, "name"
	)

	_add_question(
		survey,
		title="How satisfied were you with the response?",
		question_type=TYPE_SCALE,
		scale_min=1,
		scale_max=5,
		scale_min_label="Very unsatisfied",
		scale_max_label="Very satisfied",
		mandatory=1,
		triggering_options=[yes],
	)
	_add_question(
		survey,
		title="How did you get in touch?",
		question_type=TYPE_MULTIPLE_CHOICE,
		options=["Email", "Live chat", "Phone", "The community forum"],
		triggering_options=[yes],
	)
	_add_question(
		survey,
		title="Was your issue resolved?",
		question_type=TYPE_SINGLE_CHOICE,
		options=["Yes, first time", "Yes, but it took a while", "No"],
		triggering_options=[yes],
	)
	_add_question(
		survey,
		title="Anything you would like to tell the person who helped you?",
		question_type=TYPE_LONG_TEXT,
		triggering_options=[yes],
	)

	# -- Value and renewal --------------------------------------------
	_add_section(survey, "Value and renewal", description="<p>Last few.</p>")
	_add_question(
		survey,
		title="How do you feel about what you pay?",
		question_type=TYPE_SINGLE_CHOICE,
		mandatory=1,
		options=["Very good value", "Fair", "A bit expensive", "Far too expensive"],
	)
	_add_question(
		survey,
		title="How likely are you to renew?",
		question_type=TYPE_SCALE,
		scale_min=0,
		scale_max=10,
		scale_min_label="Certainly not",
		scale_max_label="Certainly",
		mandatory=1,
	)
	_add_question(
		survey,
		title="Are you evaluating any alternatives?",
		question_type=TYPE_SINGLE_CHOICE,
		options=["No", "Looking casually", "Actively comparing", "Already decided to move"],
	)
	_add_question(
		survey,
		title="What would make the single biggest difference to you next year?",
		question_type=TYPE_LONG_TEXT,
		mandatory=1,
		placeholder="One thing",
	)
	_add_question(
		survey,
		title="May we contact you about your answers?",
		question_type=TYPE_SINGLE_CHOICE,
		options=["Yes", "No"],
		allow_comments=1,
		comments_message="If yes, the best address to use:",
	)

	return survey
