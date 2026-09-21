# Survey

Surveys, assessments and certifications for Frappe v16.

A ground-up Frappe implementation of the survey domain: a builder for
multi-section questionnaires with nine question types, conditional (skip)
logic, scoring, certification and a token-based public response flow.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Core DocTypes, constraints, permissions, samples | **done** |
| 2 | Public survey-taking API + Vue 3 portal player | **done** |
| 3 | Skip logic, roaming, timers, breadcrumb | **done** |
| 4 | Certification: badges, certificate PDF, email, section breakdown | **done** |
| 5 | Reports & analytics | todo |
| 6 | Invitations & portal access | todo |
| 7 | Live sessions (optional) | todo |

See `TODO.md` for the deferred items and `ODOO_SURVEY_TO_FRAPPE_SPEC.md`
(in the analysis repo) for the full functional specification.

## Install

```bash
bench get-app survey /path/to/frappe-survey
bench --site <site> install-app survey
bench build --app survey
```

**Node 24 or newer is required** to build the assets — Frappe 16's own
`package.json` sets `"engines": {"node": ">=24"}`, and `bench build` fails on
anything older. With nvm: `nvm use 24`.

If the DocTypes do not appear after installing, the app was probably already
recorded as installed from an earlier failed attempt; `install_app` returns
early in that case and never syncs. Force it:

```bash
bench --site <site> install-app survey --force
# or, to sync this app only:
bench --site <site> execute frappe.model.sync.sync_for --args "['survey', 1]"
```

## Structure

```
survey/
├── constants.py          # question types, enums, shared choice lists
├── permissions.py        # permission query conditions + has_permission
├── samples.py            # four one-click sample surveys
├── utils/                # tokens, sequencing, scoring helpers
├── api/player.py         # the public, guest-callable endpoints
├── player/               # access gate, pagination, persistence, validation
├── www/s.py, s.html      # the /s/<token> page and its server-rendered shell
├── public/js/player/     # the Vue 3 player (App.vue + components/)
├── desktop_icon/         # v16 home-screen app tile
├── workspace_sidebar/    # v16 in-app left sidebar
└── survey/doctype/       # the DocTypes
```

### Desk navigation

Frappe v16 needs three separate records, not just a Workspace:

| Record | Ships as | Drives |
|---|---|---|
| `Desktop Icon` | `survey/desktop_icon/survey.json` | the tile on the home icon rail |
| `Workspace Sidebar` | `survey/workspace_sidebar/survey.json` | the left sidebar inside the app |
| `Workspace` | `survey/survey/workspace/survey/survey.json` | the landing page content |

`sync_for` picks up the first two from app-level folders
(`frappe/model/sync.py`, `app_level_folders`). The Workspace's `label` must
stay `Surveys` — it autonames from that field, and `/app/survey` would collide
with the Survey doctype list — while its `title` is what the sidebar shows.

## The player

A single portal page (`/s/<token>`) that renders a server-side shell for first
paint and then boots a Vue 3 app over it. Vue resolves from
`apps/frappe/node_modules` through esbuild's `nodePaths`, so this app carries
no `package.json` dependencies and `bench build` needs no extra setup.

It deliberately does **not** use frappe-ui: that needs its own Vite project,
Tailwind and node_modules (see `apps/hrms/frontend`), and is built for
authenticated desk-adjacent apps rather than a guest, token-authenticated
page.

## Tests

```bash
bench --site <site> set-config allow_tests true   # or it refuses to run
bench --site <site> run-tests --app survey
```

149 tests (one PDF test skips where the site hostname does not resolve). Run them on a real site — several defects only showed up under a
live database.

## Demo data

Three full-size surveys, one per player feature worth trying:

```bash
bench --site <site> execute survey.demo.create_demo_surveys
```

| Survey | Questions | Exercises |
|---|---|---|
| Employee Engagement Pulse | 10 | sections, breadcrumb, conditional follow-ups |
| Product Knowledge Assessment | 15 | the 15-minute timer, scoring, certification |
| Customer Experience Survey | 20 | roaming and the skipped-question queue |

It prints each survey's `/s/<token>` link. This is separate from `samples.py`,
which is the four one-click starters offered inside the builder.

## Licence

MIT
