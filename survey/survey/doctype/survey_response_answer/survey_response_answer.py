# Copyright (c) 2026, Bosco Soft Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from survey.constants import ANSWER_TYPE_FIELD


class SurveyResponseAnswer(Document):
	def validate(self):
		self.validate_skipped_xor_answered()

	def validate_skipped_xor_answered(self):
		"""An answer row is either skipped or answered, never both, never neither.

		The value field matching `answer_type` must actually carry something.
		Two values need an explicit exemption: a numeric answer of `0` and a
		scale answer of `0` are real answers that happen to be falsy.
		"""
		if bool(self.skipped) == bool(self.answer_type):
			frappe.throw(
				_("A question can either be skipped or answered, not both."),
				title=_("Inconsistent Answer"),
			)

		if self.skipped:
			return

		if self.answer_type in ("Number", "Scale"):
			# 0 is a legitimate answer for both.
			value = self.value_number if self.answer_type == "Number" else self.value_scale
			if value is None:
				frappe.throw(_("{0} answers need a value.").format(_(self.answer_type)))
			return

		field = ANSWER_TYPE_FIELD.get(self.answer_type)
		if field and not self.get(field):
			frappe.throw(
				_("This {0} answer has no value.").format(_(self.answer_type)),
				title=_("Inconsistent Answer"),
			)

	def get_value(self):
		"""The answer as a plain Python value, for reports and exports."""
		if self.skipped:
			return None

		if self.answer_type == "Option":
			return self.selected_option

		field = ANSWER_TYPE_FIELD.get(self.answer_type)
		return self.get(field) if field else None

	@property
	def is_comment(self) -> bool:
		return self.answer_type == "Comment"
