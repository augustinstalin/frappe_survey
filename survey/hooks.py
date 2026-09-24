app_name = "survey"
app_title = "Survey"
app_publisher = "Bosco Soft Technologies"
app_description = "Surveys, assessments and certifications for Frappe"
app_email = "augustinstalin@boscosofttech.com"
app_license = "mit"

# ----------------------------------------------------------------------
# Apps screen
#
# Without this the app has no tile on /apps and no entry in the app
# switcher, however many DocTypes it defines.
# ----------------------------------------------------------------------

add_to_apps_screen = [
	{
		"name": "survey",
		"logo": "/assets/survey/images/survey-logo.svg",
		"title": "Survey",
		"route": "/app/surveys",
		"has_permission": "survey.permissions.has_app_permission",
	}
]

# ----------------------------------------------------------------------
# Installation
# ----------------------------------------------------------------------

after_install = "survey.install.after_install"

# ----------------------------------------------------------------------
# Permissions
#
# Respondents are NOT covered here: the public endpoints authenticate them
# with an access token and then act with `ignore_permissions`. See
# survey/permissions.py for why this is a query condition and not a User
# Permission.
# ----------------------------------------------------------------------

permission_query_conditions = {
	"Survey": "survey.permissions.get_permission_query_conditions",
	"Survey Question": "survey.permissions.get_question_permission_query_conditions",
	"Survey Question Option": "survey.permissions.get_option_permission_query_conditions",
	"Survey Response": "survey.permissions.get_response_permission_query_conditions",
}

has_permission = {
	"Survey": "survey.permissions.has_survey_permission",
	"Survey Question": "survey.permissions.has_question_permission",
	"Survey Question Option": "survey.permissions.has_option_permission",
	"Survey Response": "survey.permissions.has_response_permission",
}

# ----------------------------------------------------------------------
# Document events
#
# Kept as lists so later phases (certification, badges, LMS/HR bridges) can
# append without touching the controllers.
# ----------------------------------------------------------------------

doc_events = {
	"Survey Response": {
		"on_submit": ["survey.certification.on_response_submit"],
		"on_cancel": ["survey.certification.on_response_cancel"],
	},
}

# ----------------------------------------------------------------------
# Scheduler
# ----------------------------------------------------------------------

scheduler_events = {
	"hourly": [
		"survey.tasks.close_expired_surveys",
		"survey.tasks.close_expired_responses",
	],
	"daily": [
		"survey.tasks.send_invite_reminders",
	],
	"daily_long": [
		"survey.tasks.cleanup_abandoned_responses",
	],
}

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

fixtures = [
	{"dt": "Role", "filters": [["name", "in", ["Survey Manager", "Survey User", "Survey Respondent"]]]},
]

# ----------------------------------------------------------------------
# Assets
#
# The player bundle is deliberately NOT in `web_include_js`: it would then
# load on every page of the website, and it is only ever needed on /s/<token>.
# `www/s.html` includes it itself.
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Website
#
# `/s/<token>` -> `www/s.py`. Werkzeug puts the `token` segment into
# `frappe.form_dict`, which is where `get_context` reads it.
# ----------------------------------------------------------------------

website_route_rules = [
	{"from_route": "/s/<token>", "to_route": "s"},
]

# ----------------------------------------------------------------------
# Portal
# ----------------------------------------------------------------------

standard_portal_menu_items = [
	{"title": "My Surveys", "route": "/my/surveys", "reference_doctype": "Survey Response"},
]
