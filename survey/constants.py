"""Shared enumerations and choice lists for the Survey app.

Every Select field in the DocType JSONs mirrors one of the tuples below.
Keep the two in sync: the JSON carries the newline-joined labels, the code
compares against these constants.
"""

# --------------------------------------------------------------------------
# Survey
# --------------------------------------------------------------------------

SURVEY_TYPE_SURVEY = "Survey"
SURVEY_TYPE_LIVE_SESSION = "Live Session"
SURVEY_TYPE_ASSESSMENT = "Assessment"
SURVEY_TYPE_CUSTOM = "Custom"

SURVEY_TYPES = (
	SURVEY_TYPE_SURVEY,
	SURVEY_TYPE_LIVE_SESSION,
	SURVEY_TYPE_ASSESSMENT,
	SURVEY_TYPE_CUSTOM,
)

STATUS_DRAFT = "Draft"
STATUS_OPEN = "Open"
STATUS_CLOSED = "Closed"

SURVEY_STATUSES = (STATUS_DRAFT, STATUS_OPEN, STATUS_CLOSED)

ACCESS_PUBLIC = "Public"
ACCESS_INVITED = "Invited Only"

ACCESS_MODES = (ACCESS_PUBLIC, ACCESS_INVITED)

PAGINATION_PER_QUESTION = "One Page Per Question"
PAGINATION_PER_SECTION = "One Page Per Section"
PAGINATION_ONE_PAGE = "All On One Page"

PAGINATIONS = (PAGINATION_PER_QUESTION, PAGINATION_PER_SECTION, PAGINATION_ONE_PAGE)

SELECTION_ALL = "All Questions"
SELECTION_RANDOM = "Randomized Per Section"

QUESTION_SELECTIONS = (SELECTION_ALL, SELECTION_RANDOM)

PROGRESS_PERCENT = "Percentage"
PROGRESS_NUMBER = "Number"

PROGRESS_DISPLAYS = (PROGRESS_PERCENT, PROGRESS_NUMBER)

SCORING_NONE = "No Scoring"
SCORING_AFTER_PAGE = "Scoring With Answers After Page"
SCORING_WITH_ANSWERS = "Scoring With Answers"
SCORING_WITHOUT_ANSWERS = "Scoring Without Answers"

SCORING_TYPES = (
	SCORING_NONE,
	SCORING_AFTER_PAGE,
	SCORING_WITH_ANSWERS,
	SCORING_WITHOUT_ANSWERS,
)

#: Scoring modes that reveal the correct answers to the respondent.
SCORING_TYPES_REVEALING_ANSWERS = (SCORING_AFTER_PAGE, SCORING_WITH_ANSWERS)

CERTIFICATE_LAYOUTS = (
	"Modern Purple",
	"Modern Blue",
	"Modern Gold",
	"Classic Purple",
	"Classic Blue",
	"Classic Gold",
)

# --------------------------------------------------------------------------
# Question
# --------------------------------------------------------------------------

TYPE_SINGLE_CHOICE = "Single Choice"
TYPE_MULTIPLE_CHOICE = "Multiple Choice"
TYPE_SHORT_TEXT = "Single Line Text"
TYPE_LONG_TEXT = "Multiple Line Text"
TYPE_NUMERIC = "Numeric"
TYPE_SCALE = "Scale"
TYPE_DATE = "Date"
TYPE_DATETIME = "Datetime"
TYPE_MATRIX = "Matrix"

QUESTION_TYPES = (
	TYPE_SINGLE_CHOICE,
	TYPE_MULTIPLE_CHOICE,
	TYPE_SHORT_TEXT,
	TYPE_LONG_TEXT,
	TYPE_NUMERIC,
	TYPE_SCALE,
	TYPE_DATE,
	TYPE_DATETIME,
	TYPE_MATRIX,
)

#: Types that present a fixed list of options to pick from.
CHOICE_TYPES = (TYPE_SINGLE_CHOICE, TYPE_MULTIPLE_CHOICE)

#: Types that own `Survey Question Option` rows at all (choices + matrix columns).
TYPES_WITH_OPTIONS = (TYPE_SINGLE_CHOICE, TYPE_MULTIPLE_CHOICE, TYPE_MATRIX)

#: Types that may trigger a conditional question. Mirrors Odoo: only choice
#: questions can be used as a trigger, because only they have discrete answers.
TRIGGER_CAPABLE_TYPES = CHOICE_TYPES

#: Types whose answer is a single scalar value stored on the answer row.
SIMPLE_ANSWER_TYPES = (
	TYPE_SHORT_TEXT,
	TYPE_LONG_TEXT,
	TYPE_NUMERIC,
	TYPE_SCALE,
	TYPE_DATE,
	TYPE_DATETIME,
)

#: Types that can carry a correct answer on the question itself (as opposed to
#: on individual options). Text, scale and matrix questions are never scored.
DIRECTLY_SCORABLE_TYPES = (TYPE_NUMERIC, TYPE_DATE, TYPE_DATETIME)

#: Types that support the min/max "validate entry" constraint.
VALIDATABLE_TYPES = (TYPE_SHORT_TEXT, TYPE_NUMERIC, TYPE_DATE, TYPE_DATETIME)

#: Types that support an "other, please specify" comment box.
COMMENTABLE_TYPES = (TYPE_SINGLE_CHOICE, TYPE_MULTIPLE_CHOICE, TYPE_MATRIX)

#: Types that support a placeholder.
PLACEHOLDER_TYPES = SIMPLE_ANSWER_TYPES

MATRIX_SINGLE = "One Choice Per Row"
MATRIX_MULTIPLE = "Multiple Choices Per Row"

MATRIX_SUBTYPES = (MATRIX_SINGLE, MATRIX_MULTIPLE)

#: Hard bounds on the scale question, matching Odoo's CHECK constraint.
SCALE_ABSOLUTE_MIN = 0
SCALE_ABSOLUTE_MAX = 10

# --------------------------------------------------------------------------
# Response
# --------------------------------------------------------------------------

RESPONSE_NEW = "New"
RESPONSE_IN_PROGRESS = "In Progress"
RESPONSE_COMPLETED = "Completed"

RESPONSE_STATUSES = (RESPONSE_NEW, RESPONSE_IN_PROGRESS, RESPONSE_COMPLETED)

#: `Survey Response Answer.answer_type` -> the value field that must be set.
#: `None` means the row is a skipped answer and carries no value.
ANSWER_TYPE_FIELD = {
	"Text": "value_text",
	"Long Text": "value_long_text",
	"Number": "value_number",
	"Scale": "value_scale",
	"Date": "value_date",
	"Datetime": "value_datetime",
	"Option": "selected_option",
	"Comment": "value_text",
}

ANSWER_TYPES = tuple(ANSWER_TYPE_FIELD.keys())

#: Question type -> the answer_type used when storing a simple (non-option) answer.
QUESTION_TYPE_TO_ANSWER_TYPE = {
	TYPE_SHORT_TEXT: "Text",
	TYPE_LONG_TEXT: "Long Text",
	TYPE_NUMERIC: "Number",
	TYPE_SCALE: "Scale",
	TYPE_DATE: "Date",
	TYPE_DATETIME: "Datetime",
}

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

ROLE_MANAGER = "Survey Manager"
ROLE_USER = "Survey User"
ROLE_RESPONDENT = "Survey Respondent"

#: Length of the generated access tokens. 32 hex chars = 128 bits of entropy,
#: which is what guards every public route in the absence of an ACL.
TOKEN_LENGTH = 32

#: Questions are sequenced in steps so rows can be inserted between two
#: existing ones without renumbering the whole survey.
SEQUENCE_STEP = 10

#: Seconds a page submitted right on the buzzer is still accepted for.
#: Covers network latency and the browser's own timer drift; it is not a
#: negotiation, because the server clock is the only one consulted.
TIME_LIMIT_GRACE_SECONDS = 10

#: How close to the deadline the countdown starts warning, in seconds.
TIME_LIMIT_WARNING_SECONDS = 60
