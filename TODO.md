# TODO

Deferred work, in the order it is expected to land. Anything marked
**decision** needs an answer before the phase that owns it starts.

---

## Phase 2 — Survey-taking API and portal player — **done**

- [x] `survey/api/player.py`: `start`, `get_state`, `begin`, `submit_page`,
      `go_back`. All `allow_guest=True`, all behind `player.access.resolve`.
- [x] The validity gate, with stable codes the player maps to screens.
- [x] `rate_limit` on `start` (30/hr) and `submit_page` (600/hr).
- [x] Answer persistence: delete-and-recreate for choice and matrix,
      overwrite for simple answers, skipped rows, separate `Comment` rows.
- [x] Server-side validation per question type, mirrored in the browser.
- [x] Portal page `www/s.py` + `www/s.html`, route `/s/<token>`.
- [x] Nine question renderers, progress bar, back button.
- [x] Resume: cookie + `last_displayed_question`.
- [x] Mobile matrix as stacked cards.

Deferred out of phase 2:

- [x] **Breadcrumb** for "One Page Per Section". Done in phase 3.
- [x] **`retry`** endpoint. Done in phase 6, alongside the attempt gate it needed.
- [x] **Timer UI.** Done in phase 3.
- [x] **decision**: translation strategy. Resolved against per-field
      `translatable` (the thin option) rather than one Survey document per
      language — checked how LimeSurvey, Odoo and SurveyJS actually do this
      (all one language-neutral structure + per-language text, not cloned
      documents) and how Frappe core/ERPNext/HRMS already do it (the same
      shape: `"translatable": 1` + the core `Translation` doctype). The
      fields were already flagged; the one missing piece — the player never
      looking a translation up — is fixed in `survey/player/serializers.py`
      (`translated()`), which runs every respondent-facing text field
      through `frappe._()` against `frappe.local.lang` before it reaches the
      browser. Translators add a translation the normal Frappe way: the
      translate icon next to the field in the desk form. No new doctypes, no
      cloned survey trees.

## Player rewrite — Vue 3 — **done**

The player is now Vue 3 SFCs, matching section H of the spec. The first
implementation was vanilla ES modules; that worked but made state and screen
two separate things to keep in step, which is where two of the bugs below came
from.

- [x] `App.vue` + `useSurvey.js` (the state machine) + 11 components.
- [x] Vue resolves from `apps/frappe/node_modules` via esbuild's `nodePaths`,
      so this app still has no `package.json` dependencies of its own.
- [x] Skip logic is a pure function of the answer state
      (`skip_logic.js`) rather than a DOM walk.
- [x] The matrix binds both layouts (table and cards) to one answer object,
      which removes the "read whichever layout is visible" hack.
- [x] SCSS is unchanged apart from the transition classes; no Tailwind, no
      `<style>` blocks in the SFCs.

**Cost:** the bundle went from 17 KB to 87 KB. That is the Vue runtime, and it
is the honest price of the rewrite.

**Not frappe-ui.** frappe-ui needs its own Vite sub-project, Tailwind and
node_modules (see `apps/hrms/frontend` for the pattern it forces). It is built
for authenticated desk-adjacent apps; this player is guest + token, server-
rendered shell, one bundle. Revisit it for the *builder* UI, not here.

## Player UI redesign + Test Survey — **done**

- [x] Full restyle: open canvas, large question type, card choices with
      A/B/C badges and a tick, hairline progress at the top, sticky
      Back/Continue bar, direction-aware slide transitions, staggered rise,
      shake on error, dark mode, reduced-motion respected.
- [x] Start screen with fact chips (questions, ~minutes, time limit, scored);
      finish screen with a score ring / check draw, confetti on pass, and a
      certificate download button.
- [x] Per-survey **Accent Colour** and **Auto-advance on Single Choice**
      (fields on Survey). Colour is validated before reaching a style attr.
- [x] Image-choice zoom lightbox.
- [x] `Survey` form: **Test Survey** button (`survey.js`) →
      `survey.api.player.start_test`. Works on Draft surveys; the run is an
      `is_test` response bound to the author's session, never counted, and
      purged when the survey structure changes or the survey is deleted (it
      no longer locks editing). "Run the test again" on the finish screen.
- [x] `/s/<token>` no longer wrapped in the site navbar/footer/container.
- [x] Fixed: option `key` was the option's text, not a letter, so A–Z
      shortcuts never matched.

Not done from the Odoo list: multi-tab detection, image preloading, the
per-page correct-answer reveal UI (`correct_answers` is sent, not rendered).

## Phase 3 — Roaming, timers, and the rest of skip logic — **done**

Much of the skip-logic work landed in phase 2 because navigation could not
exist without it:

- [x] Server-side next/previous resolution for all three layouts.
- [x] Client-side show/hide for the multi-question layouts.
- [x] Answers to questions that became hidden are cleared
      (`persistence.clear_hidden_answers`).
- [x] Progress total excludes hidden questions, so the bar cannot go
      backwards. (Odoo has that bug; we do not inherit it.)
- [x] Back navigation with answers repopulated.

Phase 3 proper:

- [x] **Survey timer.** `Survey Response.time_remaining()` is the single
      source of truth and is measured from `started_on`, so closing the tab
      does not pause it. The payload carries a *duration* (`time_left`), never
      a deadline, and the browser anchors its countdown to its own clock the
      moment it arrives — which is why a machine with a wrong clock or a
      different timezone still counts down correctly. Every page turn re-syncs
      it. `SurveyTimer.vue` warns under 60s and auto-submits at zero.
- [x] **Server-side enforcement** with a 10-second grace window
      (`TIME_LIMIT_GRACE_SECONDS`). Past it, `_finish_if_out_of_time` submits
      the response and refuses the page. The grace is there to forgive network
      latency, not to let a stopped client clock buy time — the server clock
      is the only one consulted.
- [x] **Skipped-mandatory revisit queue.** Roaming lets a mandatory question
      through blank, so reaching the end sets `first_submitted` and doubles
      back through whatever is still outstanding instead of finishing. Forward
      then means "next unanswered", not "next page". The button relabels to
      **Next unanswered** and carries a count, because telling somebody
      "Submit" and then bouncing them backwards is a lie about what the button
      does.
- [x] **Breadcrumb** for One Page Per Section, with a dot per section, a
      marker on sections that still owe an answer, and jump-to-section (which
      saves the page it leaves, via `direction="jump"`).
- [x] The outstanding count is bounded by how far the respondent has actually
      got (`navigation.get_outstanding_pages`). Unbounded it reported every
      mandatory question in the survey on page one — "17 questions still need
      an answer" before being asked a single one.

Still open from this phase:

- [ ] Profile `get_triggering_options_map` under real page turns and cache it
      against the survey's `modified` stamp if it shows up.
- [ ] A per-question time limit (`is_time_customized`) is a live-session
      feature; it belongs with phase 7, not here.

## Phase 4 — Certification — **done**

- [x] `Survey Badge` and `Survey Badge Award` DocTypes. Award is a log entry
      only — created and deleted exclusively from `survey/certification.py`,
      never edited by hand.
- [x] `Survey.badge` Link field. `Survey Badge.survey` is the back-reference,
      kept in sync from the survey side only (`sync_badge_ownership`) —
      picking a badge already claimed by another survey is refused; swapping
      or turning off `give_badge` releases the old one.
- [x] Certificate Print Format (`Survey Certificate`), landscape A4. Two
      structural families (Modern adds a seal; Classic is unadorned serif,
      double border) × three accent colours (purple/blue/gold), which covers
      all six layouts the `certificate_layout` field offers, not just the two
      the plan called for.
- [x] `frappe.attach_print` + the certificate email on `on_submit`, via
      `certificate_email_template` (Email Template, optional — no email if
      unset, no error either).
- [x] Guest-callable `survey.certification.download_certificate`, gated on
      the response's own access token (same model as the player) and on
      having actually passed. `is_certificate_available()` is the single
      predicate both the gate and the player's result screen read.
- [x] Per-section correct/partial/incorrect/skipped breakdown
      (`Survey Response.get_section_breakdown`). "Partial" only applies to
      Multiple Choice — Single Choice and the directly-scorable types have no
      partial-credit concept. Hidden from the certificate and the player
      result under `Scoring Without Answers`, same as everywhere else
      per-question correctness could leak.
- [x] `doc_events["Survey Response"]["on_submit"/"on_cancel"]` now point at
      `survey.certification.on_response_submit` / `on_response_cancel`.

**A genuine wkhtmltopdf/Qt-WebKit finding, worth remembering for any future
print format in this app:**

1. CSS custom properties (`var(--x)`) are not supported at all — a
   `border: 1mm solid var(--accent)` silently renders no border. Every colour
   in the certificate is a literal hex value; family/colour variation is done
   with plain CSS classes, not variables.
2. `margin-top: auto` inside a flex column does not push content to the
   bottom of an absolutely-positioned or explicitly-sized container. The
   footer is anchored with a single `position: absolute; bottom: Xmm`
   instead.
3. **`currentColor` on an SVG child does not reliably inherit `color` from an
   ancestor when a same-specificity-or-lower rule matches the child
   directly.** Frappe's own print bundle ships
   `@media print { *, *:before, *:after { color: #000 } }` — `*` matches a
   `<path>`/`<circle>` directly, and a direct match always beats inheritance,
   regardless of specificity. `fill="currentColor"`/`stroke="currentColor"`
   on the seal's shapes were silently resolving to black because of this. Fix:
   give the shape its own class and set `fill`/`stroke` explicitly
   (`.seal-star { fill: ... }`), never rely on inheriting through
   `currentColor`. This cost real time to track down — traced it by
   `pdfkit.from_string`-testing the exact same HTML through the *actual*
   `frappe.utils.pdf.get_pdf()` call versus a bare wkhtmltopdf invocation, and
   pixel-sampling the raw PPM output of each to compare, since low-resolution
   screenshots were not reliable enough to tell purple-vs-black-tinted-purple
   apart.
4. A local `frappe.get_print(as_pdf=True)` call needs the site's own hostname
   to actually resolve — `expand_relative_urls` bakes it into the HTML wkhtmltopdf
   then fetches static assets from as a real subprocess-level HTTP request.
   On a dev box where the site name isn't in `/etc/hosts` (this sandbox has no
   root), that fails with `HostNotFoundError`. Point-fix for testing:
   temporarily set `host_name` in `site_config.json` to an address that
   *does* resolve (`http://127.0.0.1:<port>`) with a `bench serve` actually
   listening there; route the request to the right site with the
   `X-Frappe-Site-Name` header instead of `Host`, since `Host` is what
   `get_url()` reads back out for the asset URLs. Not a code change — a real
   production deployment already has its own hostname in DNS.

## Phase 5 — Reports — **done**

- [x] Results dashboard with cross-question answer filtering. Not a Query
      Report — it needs AND-able "question = option" filter rows, built at
      request time, which Report Builder can't express (see the spec, section
      F). `survey.api.reports.get_filtered_responses` intersects one
      `Survey Response Answer` lookup per filter row as plain Python sets
      rather than hand-rolling repeated-join SQL; backs the new
      `survey-results` Desk Page (`survey/survey/page/survey_results/`),
      which also shows the header summary (`get_dashboard_summary`) and a
      filter-row builder fed by `get_choice_questions`. Per-question
      distributions and trend charts live in the report/dashboard below
      instead of being duplicated here.
- [x] Query Reports: **Survey Answers** (one row per answer),
      **Survey Answer Distribution** (option counts + % per choice question),
      **Score Distribution** (`score_percentage` bucketed into ranges).
      `survey/survey/report/`.
- [x] Dashboard + Number Cards for the survey KPIs. "Survey Analytics"
      (`survey/survey/survey_dashboard/` — note the module-prefixed folder
      name; `frappe.utils.dashboard.sync_dashboards` looks for
      `<module>_dashboard`, not `dashboard`, which is not obvious from
      the Dashboard Chart/Number Card folders sitting right next to it
      unprefixed): Total Responses, Completed Responses, Average Score,
      Certificates Issued, plus a Responses Over Time chart.
- [x] Print Format for an individual response. `Survey Response Detail`,
      portrait A4, plain Jinja (not the certificate's bespoke CSS) —
      question/answer pairs grouped by section, correctness shown only when
      `Scoring Without Answers` doesn't withhold it. Reads
      `Survey Response.get_answer_rows()`, computed once in `before_print`
      alongside the certificate context.

## Phase 6 — Invitations and portal access — **done**

- [x] `Survey Invite` DocType + the send dialog. Standalone doctype
      (`survey/survey/doctype/survey_invite/`); `survey.api.invites.send_invites`
      get-or-creates one per recipient address (idempotent on survey+email)
      and is called from a "Send Invitations" button/dialog on `survey.js`.
- [x] Per-recipient token rendering in the email body. `Survey.invite_email_template`
      (same optional, no-email-if-unset contract as `certificate_email_template`)
      renders with `{{ invite_url }}` — `/s/<survey token>?invite=<invite token>`.
- [x] Attempt limiting enforcement at `start` (and at the new
      `start_via_invite`/`retry`). `player.access.check_attempts_remaining`,
      backed by `SurveyResponse.build_attempt_pool_filters` (the pooling
      logic that already existed for *ranking* attempts, now also used to
      *gate* a new one before it's created) — raises the
      already-defined-but-previously-unused `NO_ATTEMPTS_LEFT` code.
- [x] Login-required and signup redirect flows. `survey/www/s.py` now acts on
      `LOGIN_REQUIRED` (previously computed and never used) by bouncing to
      `/login?redirect-to=<page>`, the same idiom core portal pages use.
- [x] `/my/surveys` portal list. `survey/www/my/surveys.py` + `.html`,
      registered in `hooks.py` `standard_portal_menu_items`.
- [x] Filled in all four scheduled jobs in `tasks.py`.
  - [x] `close_expired_responses`: **decision resolved** — an expired
        in-progress response with any answers recorded submits with what it
        has (goes through the normal scoring/certification path); one with
        zero answers cancels, same as the already-handled unstarted case.
  - [x] `send_invite_reminders`
  - [x] `cleanup_abandoned_responses`

## Phase 8 — Recurring surveys and wave comparison — **done**

Added after the fact, not part of the original phase plan: comparing answers
across repeated instances of "the same" survey (an annual engagement survey,
a quarterly pulse survey) where a few questions change wording each time.
Researched how LimeSurvey/Qualtrics/Culture Amp/question-bank platforms
handle this first — they all converge on the same idea: a stable key
independent of wording, not a text match, plus a way to group the recurring
instances together. Gated behind a new `Survey.survey_type` value,
**`Recurring`**, so the fields and the one action that makes it usable only
ever show up for a survey that opted in.

- [x] `Survey.series`/`wave_label`/`wave_date` — reqd when `Recurring`,
      cleared by `apply_type_defaults` when switching away, locked once the
      wave has a real response (`validate_recurrence`,
      `survey/survey/doctype/survey/survey.py`). `(series, wave_date)` must
      be unique. `wave_label` is display-only text ("2026 Q2"); `wave_date`
      is what waves actually sort and compare by — kept separate on purpose
      so a quarterly/monthly cadence needs no schema change, only more rows
      in the same report.
- [x] `Survey Question.comparison_key` — the field that survives a reworded
      question. Refused outright on a non-`Recurring` survey, and refused
      twice on the same survey (`validate_comparison_key`,
      `survey/survey/doctype/survey_question/survey_question.py`).
- [x] `Survey.duplicate_to_next_wave(wave_label, wave_date)` — clones the
      whole question/option tree into a new Draft wave, carrying every
      `comparison_key` forward untouched and remapping cross-question
      triggers onto the new wave's own cloned options (this is the
      cloning approach originally explored for translation, before that
      decision went a different way — revived here for a use case that
      actually needs an independent second document). "Duplicate to Next
      Wave" button on `survey.js`, shown only for `Recurring` surveys. The
      author is then expected to edit only the 2–3 questions that changed;
      whether a reworded question keeps its old key is a judgement call the
      tool deliberately leaves to them.
- [x] `survey.api.comparison` + the `survey-comparison` Desk Page: pick a
      series, pick a comparison key, see one row per wave (an answer
      distribution for a choice question, an average for a directly-scorable
      one), in `wave_date` order. Same shape whether the series has 2 annual
      waves or a dozen quarterly ones.

**Known simplification:** matching carries over at the *question* level
(`comparison_key`) but not the *option* level — an option's label is matched
by its literal text, so retyping "Very Satisfied" as "Extremely Satisfied"
between waves would silently break that option's row in the comparison. Not
adding a second key there for now: an answer scale changing wording without
changing its meaning is rare in practice, and often signals the scale itself
changed, which breaks comparability regardless of tooling. Also, this only
compares *populations* (aggregate percentages per wave), not the same
individual's answer over time — that needs a stable identity (a login,
typically) carried across every wave's response, which is a separate,
not-yet-built feature.

## Phase 7 — Live sessions (optional) — **deferred to Quizzly, see below**

**Decision: not building this here.**
[`PHASE_7_LIVE_SESSIONS.md`](PHASE_7_LIVE_SESSIONS.md) has the detail —
[`bwhtech/quizzly`](https://github.com/bwhtech/quizzly) is a mature,
standalone Frappe app that already does exactly this (host PIN, no-login
join, server-authoritative scoring, a shared RQ ticker, a genuinely simple
guest-realtime extension via `realtime/handlers.js`). Install it for this
need instead of duplicating it here. The bullets below are left unchecked
and unedited as a record of what a from-scratch build would have needed, in
case that decision is ever revisited — none of it is built.

- [ ] `Survey Session` DocType. Deliberately separate from `Survey`, unlike
      Odoo, so one survey can host concurrent sessions.
- [ ] Session fields on `Survey`/`Survey Question` are **not yet added**:
      `session_code`, `speed_rating`, `speed_rating_time_limit`,
      `is_time_limited`/`time_limit`/`is_time_customized` per question.
- [ ] Host panel, `/s` code entry, live chart, text-answer ticker.
- [ ] Speed-weighted scoring (full points under 2s, linear decay, floor 50%).
- [ ] Leaderboard with animated position shifts.
- [ ] Most-voted-answer conditional resolution for the room as a whole.
- [ ] **decision**: realtime vs polling. Frappe's socketio authenticates
      sessions, which is awkward for guest attendees. Polling every 2s is a
      legitimate fallback for a live quiz and removes a deployment class of
      problems. Decide before building the host panel.

---

## Cross-cutting

- [ ] Desk form script for the builder: the drag-drop section/question list
      (SortableJS in an HTML field, `survey.reorder` is already whitelisted),
      the trigger picker with its `get_query` filter, the misplaced-trigger
      indicator, and the header buttons (Test, Share, Results, Load Sample).
- [x] Workspace (`Surveys`), `add_to_apps_screen`, and the **v16 desk
      navigation trio**: `survey/desktop_icon/survey.json` (App tile, branded
      logo, blue), `survey/workspace_sidebar/survey.json` (the in-app left
      sidebar), and the Workspace itself. In Frappe v16 a Workspace alone is
      *not* enough -- the home icon rail reads `Desktop Icon` and the sidebar
      reads `Workspace Sidebar`; both are app-level folders picked up by
      `sync_for` (see `frappe/model/sync.py`, `app_level_folders`).
      NOTE: Workspace autoname is `field:label`, so `label` stays "Surveys"
      (route `/app/surveys`, which cannot collide with the Survey doctype
      list at `/app/survey`) while `title` -- what the sidebar shows -- is
      "Survey".
- [ ] List view settings: a status indicator on Survey and Survey Response,
      and a sensible default column set.
- [ ] `ODOO_PARITY.md` ticking off the 122 features in section B of the spec.
- [ ] Port Odoo's test scenarios: `test_survey_flow_with_conditions.py` and
      the JS tours are a ready-made acceptance matrix.

## Known limitations of the current code

- **A stuck mandatory question has no escape hatch.** With roaming on, the
  survey will not finish until every mandatory question is answered, and the
  revisit queue will keep returning to it. That is the intended bargain (and
  Odoo's), but it means a question nobody can answer blocks the whole run.
  The way out is for the author to unmark it mandatory.
- **`clear_hidden_answers` loses typed text.** Flip a trigger off and back on
  and the free-text answer behind it is gone. Odoo has the same behaviour and
  documents it; the alternative (keeping orphaned answers and excluding them
  everywhere) is worse.


- **Surveys lock once they have responses.** Adding or structurally changing
  a question is blocked; only cosmetic edits (title, description, messages)
  are allowed. This is stricter than Odoo on purpose — editing a question
  people have already answered silently changes what their answers mean. If
  users push back, the escape hatch is "duplicate the survey", which needs a
  duplicate action that remaps trigger references (not built yet).
- **`Survey.recompute_scores` is O(responses)** and runs inline. It needs to
  become a background job before it meets a survey with thousands of
  responses.
- **No duplicate/copy action yet.** Odoo's `copy()` remaps
  `triggering_answer_ids` to the cloned options by zipping them in order; the
  Frappe equivalent needs the same remap or skip logic silently points at the
  original survey's options.


---

## Bugs found by actually running the suite

The tests were written before the site existed and had never been executed.
Running them surfaced five real defects, all now fixed with regression tests:

1. **Scoring always produced zero.** `Survey Question.is_scored` is derived
   from whether any option is marked correct, but options are separate
   documents created *after* the question, and nothing recomputed it. Frappe
   has no dependency graph, so the option now pushes it
   (`survey_question.recompute_is_scored`, called from the option's
   `sync_parent_survey`). `samples.py` had a local workaround for this, which
   is why the sample surveys looked fine; nothing created through the UI did.
2. **An answer unlocked on the same page was silently discarded.** Skip logic
   is evaluated against *stored* answers, so a question revealed by an answer
   in the same submission still looked hidden when it arrived, and never made
   it into the save set. Saving now uses `navigation.get_page_for_save`, which
   keeps structurally-present questions; `clear_hidden_answers` still removes
   anything genuinely unreachable afterwards.
3. **The "skipped xor answered" rule never ran.** Frappe does not call a child
   DocType's `validate()` — only field-level checks
   (`frappe/model/document.py::_validate`). The parent now drives it.
4. **A negative question score was only rejected when entry validation
   happened to be on**, because the check sat inside `validate_limits`, which
   returns early. It has its own step now.
5. **`max(sequence)` passed to `get_value` as a string** is rejected outright
   in Frappe v16 (`frappe/database/query.py:2137`). Four call sites; all now
   order descending and take the first row.

Worth remembering: **run the suite on a real site**, not just read it.
`bench --site <site> set-config allow_tests true` first, or it refuses.


---

## A note on running the tests

`Survey.recompute_scores` used to call `frappe.db.commit()`. Frappe commits a
successful request on the way out anyway, so it bought nothing — but under
test it flushed the transaction the runner rolls back, which meant **every
fixture from every test up to that point stayed on the site**. A full run left
around eighty stray surveys behind. The commit is gone; a full run now leaves
the database exactly as it found it.

The general rule: no `frappe.db.commit()` inside a document method. Scheduled
jobs (`tasks.py`) are the exception, because committing per batch is how they
keep partial progress when a long run is interrupted.
