// Copyright (c) 2026, Bosco Soft Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Survey", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Test Survey"),
			() => frm.trigger("run_test"),
			null
		);
		frm.change_custom_button_type(__("Test Survey"), null, "primary");

		frm.add_custom_button(__("Copy Public Link"), () => {
			const url = `${window.location.origin}/s/${frm.doc.access_token}`;
			frappe.utils.copy_to_clipboard(url);
		});

		frm.add_custom_button(__("Send Invitations"), () => frm.trigger("send_invitations"));

		if (frm.doc.survey_type === "Recurring") {
			frm.add_custom_button(__("Duplicate to Next Wave"), () => frm.trigger("duplicate_to_next_wave"));
		}

		if (frm.doc.status !== "Open") {
			frm.dashboard.set_headline_alert(
				__("This survey is {0}. Only \"Test Survey\" can open it; the public link works once it is Open.", [
					__(frm.doc.status),
				]),
				"orange"
			);
		}
	},

	/**
	 * Open a private test run in a new tab.
	 *
	 * Saves first: testing a survey with unsaved edits would show the
	 * previous version and make the button look broken.
	 */
	async run_test(frm) {
		if (frm.is_dirty()) await frm.save();

		// Open the tab synchronously, inside the click, or the popup blocker
		// eats it; point it at the run once the server has made one.
		const tab = window.open("", "_blank");

		try {
			const { message } = await frappe.call({
				method: "survey.api.player.start_test",
				args: { survey: frm.doc.name },
				freeze: true,
				freeze_message: __("Preparing a test run…"),
			});

			if (tab) tab.location.href = message.url;
			else window.location.href = message.url;
		} catch (error) {
			if (tab) tab.close();
			throw error;
		}
	},

	/**
	 * Collect recipient addresses and hand them to
	 * `survey.api.invites.send_invites`. Kept to a plain textarea rather than
	 * a grid — this is a "paste a list of emails" action, not a place to
	 * build up structured Contact/User rows.
	 */
	send_invitations(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Send Invitations"),
			fields: [
				{
					fieldtype: "Small Text",
					fieldname: "emails",
					label: __("Email Addresses"),
					description: __("One per line, or comma-separated."),
					reqd: 1,
				},
			],
			primary_action_label: __("Send"),
			primary_action: async ({ emails }) => {
				const recipients = emails
					.split(/[\n,]/)
					.map((email) => email.trim())
					.filter(Boolean)
					.map((email) => ({ email }));

				if (!recipients.length) {
					frappe.msgprint(__("Enter at least one email address."));
					return;
				}

				const { message } = await frappe.call({
					method: "survey.api.invites.send_invites",
					args: { survey: frm.doc.name, recipients },
					freeze: true,
					freeze_message: __("Sending…"),
				});

				dialog.hide();

				let summary = __("Sent {0} invitation(s).", [message.sent.length]);
				if (message.skipped.length) {
					summary += " " + __("{0} skipped.", [message.skipped.length]);
				}
				frappe.msgprint(summary);
			},
		});

		dialog.show();
	},

	/**
	 * Clone this wave into the next one, via `Survey.duplicate_to_next_wave`.
	 * Every question's `comparison_key` carries forward untouched — the
	 * author is expected to then edit just the questions that changed for
	 * this wave, not rebuild the survey.
	 */
	duplicate_to_next_wave(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Duplicate to Next Wave"),
			fields: [
				{
					fieldtype: "Data",
					fieldname: "wave_label",
					label: __("Wave Label"),
					description: __('How this wave reads to people, e.g. "2027" or "2026 Q3".'),
					reqd: 1,
				},
				{
					fieldtype: "Date",
					fieldname: "wave_date",
					label: __("Wave Date"),
					description: __("What this wave actually sorts and compares by."),
					reqd: 1,
				},
			],
			primary_action_label: __("Duplicate"),
			primary_action: async ({ wave_label, wave_date }) => {
				const { message: new_name } = await frappe.call({
					method: "duplicate_to_next_wave",
					doc: frm.doc,
					args: { wave_label, wave_date },
					freeze: true,
					freeze_message: __("Duplicating…"),
				});

				dialog.hide();
				frappe.set_route("Form", "Survey", new_name);
			},
		});

		dialog.show();
	},
});
