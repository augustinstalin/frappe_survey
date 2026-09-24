# Phase 7 — Live sessions: deferred to Quizzly

## Decision

Phase 7 (`TODO.md`) — a host-driven, PIN-joined, no-login live quiz — is
**not being built inside this app**. Install
[`bwhtech/quizzly`](https://github.com/bwhtech/quizzly) as a standalone
Frappe app instead. It already does exactly this, well, and duplicating it
here would just be a second, less mature implementation of the same thing.

`Survey.survey_type = "Live Session"` stays in the Survey app as a type
value with its own field defaults (`apply_type_defaults`,
`survey/survey/doctype/survey/survey.py`), but nothing currently builds on
top of it, and this note is not proposing that changes. If a real need to
integrate the two ever comes up, treat that as a fresh decision — this note
only records why nothing was built now.

## What Quizzly is

A live multiplayer quiz app on the Frappe Framework: a host puts a 6-digit
PIN (or a QR code) on a shared screen, players join from their phones with
no account, and the game is server-authoritative (the correct answer never
reaches a device before the question closes; scores come from a server-set
deadline). Its own words: *"Live multiplayer quiz, no login required."*

**Its DocTypes are unrelated to this app's schema** — installing it touches
nothing in `apps/survey`:

- `QZ Quiz` — a quiz, owning `QZ Question` child rows (fixed 4-option
  multiple choice, unlike Survey's nine question types). Not linked to
  `Survey` or `Survey Question` in any way.
- `QZ Session` — one live room: `quiz`, `host`, `game_pin`, `status`,
  `lobby_locked`, `auto_advance`, `randomize_answer_order`,
  `current_question`, `started_at`, `ended_at`.
- `QZ Participant` — an anonymous player: `session`, `nickname`, `avatar`,
  `token_hash` (their identity is a hashed join token, not a `User` or a
  `Survey Response`), `score`, `streak`, `rank`, `kicked`, `joined_at`.
- `QZ Answer` — `session`, `participant`, `question_row`, `selected_option`,
  `is_correct`, `response_ms`, `points`.

Stack: Frappe (DocTypes, permissions) + Vue 3/frappe-ui frontend +
Socket.IO for push + Redis for hot session state + RQ for the game loop.

## The realtime research finding (kept — useful regardless of this decision)

Frappe's own docs describe guest (unauthenticated) realtime as limited to
one shared `website` broadcast room — a guest can't join a
per-document/per-session room (`doc:{doctype}/{name}`) because that path
enforces a document-permission check no Guest session can pass. That reads,
at first, like realtime for anonymous attendees would need a big custom
lift, and an earlier pass of this research concluded the practical answer
here would be "attendees poll, only the logged-in host gets real push."

**Quizzly shows that conclusion was too pessimistic.** Frappe has a real,
documented extension point for exactly this: any app can drop a
`realtime/handlers.js` file, and Frappe's node socketio server auto-loads it
per app for every connected socket, guests included
(`apps/frappe/realtime/index.js:54`, confirmed directly in this bench's own
Frappe checkout — `require("../../${app}/realtime/handlers.js")`).
Quizzly's entire guest-room mechanism is about 15 lines built on that:

```js
// quizzly/realtime/handlers.js
const GAME_PIN = /^\d{6}$/;

function quizzly_handlers(socket) {
	socket.on("qz_join", (pin) => {
		if (typeof pin === "string" && GAME_PIN.test(pin)) {
			socket.join("qz_session_" + pin);
		}
	});
	socket.on("qz_leave", (pin) => {
		if (typeof pin === "string" && GAME_PIN.test(pin)) {
			socket.leave("qz_session_" + pin);
		}
	});
}

module.exports = quizzly_handlers;
```

The server then pushes to that exact room —
`frappe.publish_realtime(event=room, message={...}, room=room)` where
`room = f"qz_session_{pin}"` — properly scoped to that one session, not the
site-wide `website` firehose. **If this app (or any Frappe app) ever does
build its own live-session runtime, this is the extension point to reach
for, not a fallback to polling.**

## Other reusable patterns worth recording

- **One shared background job, not one per session.** `frappe.enqueue(...,
  job_id="qz_ticker", deduplicate=True)` runs a single self-looping RQ job
  (`while True: ... time.sleep(0.5)`) that advances *every* active session's
  phase machine each tick, reading/writing per-session state in Redis
  (`frappe.cache`) with a TTL, and committing the DB per session inside a
  savepoint so one bad session can't stall the others. Scales by staying a
  single job, not by spawning one job per live game.
- **Phase machine per session**: `get_ready` → `question` → (`explanation`
  and/or `stats`) → `scoreboard` → next question, each phase carrying only
  what the next one needs (`carry_over`), with an escape hatch
  (`ADVANCE_WAIT_CAP`, 5 minutes) so a host who never clicks "Next" doesn't
  strand the room forever.
- **Scoring formula** — a genuinely Kahoot-accurate shape, and worth
  flagging as **different from `TODO.md`'s current Phase 7 wording**
  ("full points under 2s, linear decay, floor 50%"):

  ```python
  def compute_points(response_ms, window_ms, streak, multiplier):
      response_ms = min(max(response_ms or 0, 0), window_ms)
      base = round((1 - (response_ms / window_ms) / 2) * 1000)
      bonus = min(streak - 1, 5) * 50
      return (base + bonus) * multiplier
  ```

  This decays continuously from the first millisecond (1000 points at
  `response_ms=0`, decaying to 500 at the deadline) rather than holding full
  points for a flat 2-second grace window, and adds a capped streak bonus on
  top. If a from-scratch build is ever reconsidered, decide explicitly
  between these two shapes rather than picking one by accident.

## If this decision is ever revisited

Install with:

```bash
bench get-app https://github.com/bwhtech/quizzly --branch develop
bench --site <site> install-app quizzly
```

It runs at `/quizzly` on the site, entirely independent of `/s/<token>` and
the rest of this app.
