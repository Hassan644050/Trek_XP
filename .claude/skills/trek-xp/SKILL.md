---
name: trek-xp
description: Working on Trek_XP, the FastAPI travel-gadget advisor for Bangladesh (traveller packing lists, coordinator catalog, admin taxonomy, SEO gadget pages). Use for any feature, fix, migration, page or data change in this repo — it holds the architecture rules, conventions, recipes and pitfalls.
---

# Trek_XP

Trek_XP answers one question: **which gadgets does this specific trip need?**
A traveller picks a destination, dates, trip type and activities; the app
resolves the place, reads last year's climate and the country's plugs, and
returns a prioritised packing list. Coordinators maintain a verified catalog
of gadgets per destination; admins manage accounts and the taxonomy.

Launch market is **Bangladesh**; India, Nepal and Sri Lanka come later, so
anything country-shaped must stay pluggable.

Deep reference: `docs/ARCHITECTURE.md` (flows, data model, seams, failure
modes) and `README.md` (setup, endpoints). Read the relevant section before a
non-trivial change instead of guessing.

## Ground rules

- **Do not run the test suite unless the user asks.** Write or update tests
  with the change; a targeted in-process check of the one function you touched
  is fine (`.venv/bin/python -c "import tests.x as t; t.test_y()"`).
- **Secrets live in `.env` only** (`LLM_API_KEY`, `DATABASE_URL`, `R2_*`).
  Never echo, log, commit or repeat a credential, even one the user pasted.
- Verify UI changes live in the browser (desktop and 375px mobile, no
  horizontal scroll) before reporting them done.
- Commit only when asked or when the user's workflow expects it; one focused
  commit per feature, message explaining *why*.

## Stack

FastAPI · async SQLAlchemy 2 + asyncpg · Alembic · Neon Postgres (pooler) ·
Pydantic v2 · Gemini (or NVIDIA NIM) via `LLM_PROVIDER` · Pillow WebP
renditions · local disk or Cloudflare R2 for images · plain HTML/JS pages,
no frontend build step, no Jinja.

Run: `.venv/bin/uvicorn app.main:app --reload` · Migrate: `alembic upgrade head`
· First admin: `python -m scripts.create_admin` · Seed:
`python -m scripts.seed_catalog [--dry-run]`.

## Architecture rules

**Routes assemble, services fetch, models describe.** A service never imports
a route; a route never calls an external API directly. This is what keeps the
offline test tier offline.

| Path | Owns |
|---|---|
| `app/routes/` | HTTP surface: `recommend`, `destinations` (`/options`, featured), `coordinator`, `admin`, `auth`, `gadget_pages` (SSR `/gadget/{slug}`, `/gadgets`) |
| `app/models/` | Pydantic contracts (`trip`, `context`, `recommendation`, `catalog`) |
| `app/services/destination/` | geocode chain, climate, plugs, admin areas, `countries.py` |
| `app/services/gadgets/` | `GadgetSource` seam, `catalog.load_catalog`, prompt, reply parsing |
| `app/services/llm/` | `LLMProvider` seam (Gemini, NVIDIA), retry |
| `app/services/media/` | image processing, renditions, `ImageStorage` (local / R2) |
| `app/services/slug.py`, `taxonomy.py` | gadget URL slugs; admin-managed options |
| `app/auth/` | argon2id, DB sessions, roles, CSRF header check |
| `app/handlers/` | exception → status mapping, the **only** place statuses are chosen |
| `app/data/countries/<code>/` | owned static data per country |
| `app/static/` | `index.html` (traveller), `coordinator.html`, shared `site-header.css/js` |

Errors: services raise domain exceptions (`DestinationNotFoundException`,
`LLMTimeoutException`, `InvalidInputException`, `ResourceConflictException`, …);
never return a status code or leak provider/SQL detail from a service.

## Domain behaviour to preserve

- **Catalog first, then five novel model items.** `/recommend` loads the
  verified catalog for the destination (match by name + proximity, or by
  **division**, country-scoped), then asks the model for exactly five items not
  already on file — enforced again in code (`_novel`), never trusted to the
  prompt. Verified items lead the list with `origin="community"`, `verified=True`.
- **Degrade and say so.** Only location and model are hard dependencies.
  Climate, plugs, catalog fail soft and add a note. Model down + catalog items
  → catalog-only answer, not a 503. `sources` credits only what contributed.
- **Blocking SDKs run on worker threads** (`asyncio.to_thread`) with both
  `LLM_TIMEOUT_SECONDS` and `LLM_TOTAL_TIMEOUT_SECONDS`.
- **Taxonomy is data, not enums.** Divisions, trip types, activities live in
  tables edited from admin **Catalog settings**. Values are slugs. Traveller
  input stays loose; the coordinator route validates against active values.
- **Gadgets** have `slug` (unique, set via `unique_gadget_slug` on create and
  rename), brand, model_name, category, color, `is_active`, image renditions
  (thumb / detail / full), and **variants** ("Buying options": brand, colour,
  quality `budget|standard|premium`, price in BDT, vendor, url).
- **Home page hero photos** (`hero_images`): admins upload in Catalog
  settings; keyed by destination slug (same as `?to=`), `""` = the country
  default. The page shows the picked place's photo, else the default, else
  the gradient. Renditions: `HERO_VARIANTS` (small 1080, full 2400),
  keys under `heroes/`.
- **Public reads are cached in-process** (`services/read_cache.py`):
  `/options`, `/destinations/featured`, `/heroes`. Stale-while-revalidate
  after 60s, warmed at startup, cleared by middleware after any successful
  `/api/admin` or `/api/coordinator` write. A new public read the home page
  makes on every view should use a `ReadCache` too — each uncached Neon
  lookup costs seconds from a dev machine.
- **Visitor analytics** (`services/analytics.py`, admin **Visitors** tab):
  cookie-free; page views of `/`, `/gadgets`, `/gadget/<slug>` counted by
  middleware, packing lists in `/recommend`. Visitors = daily-salted hash
  of IP + browser, salts deleted after the day; IPs never stored. Buffered
  in memory, flushed every 5 min, on shutdown, and before the admin
  summary. Bots, prefetches and requests with a session cookie are skipped.
  New public pages need a case in `page_label()` to be counted.
- **Model suggestions go to a review queue** (`services/gadgets/suggestions.py`):
  after `/recommend` responds, a background task saves the model's new items
  as inactive gadgets (`origin="model"`, `review_status="pending"`) with a
  placement holding the reason, and asks the model for a short description.
  Only curated/catalog destinations and active trip types are saved; loose
  name matches (`same_gadget`) add to `suggestion_count` instead of
  duplicating; coordinator and rejected gadgets are never touched. Pending
  ones are left out of the model's exclusion list. **No images are fetched**
  — the coordinator adds the photo when approving (`POST
  /api/coordinator/gadgets/{id}/review`, or switching Active on).
- **Detail page "More {type}s"** = other active gadgets of the same head noun
  (`_type_key`), not the same category. No "Recommended for" section.

## Conventions

- **Python:** type hints, Pydantic validators to tidy input (`_clean`),
  small functions, comments explain *why*. Match surrounding density.
- **SSR pages** (`gadget_pages.py`): build HTML with f-strings and escape
  every dynamic value with `html.escape` (`_e`). JSON-LD goes through
  `_json_ld` (escapes `<`, `>`, `&` for `<script>` context). Every page has
  title, meta description, canonical, OG/Twitter tags; 404s are `noindex`.
- **Static pages:** vanilla JS, `fetch` with `credentials: "same-origin"`;
  every write sends `X-Requested-With: trekxp` (CSRF). Escape before
  `innerHTML`.
- **Design system:** oklch forest-green / amber palette as CSS tokens on
  `:root` with a dark-mode override, Nunito (+ JetBrains Mono for labels),
  **square corners**, full-width layout, images `object-fit: contain`.
- **Master header:** every public page links `/site-header.css` and
  `/site-header.js` and carries the same `<header class="site-header">`
  markup (brand → `/`, Register, Login → `/coordinator`). Never restyle it
  per page; change the shared file.
- **Images:** request the rendition you show (`thumb_url` for cards,
  `detail_url` for the detail page). Storage keys are generated, never taken
  from input. Save/delete rendition sets with `services/media/image_sets.py`.

## Recipes

**Add a column / table**
1. Edit `app/db/models.py`.
2. New file `alembic/versions/000N_<name>.py` (next number), with backfill if
   existing rows need a value. Enums: `create_constraint=True`. Functional
   indexes (e.g. `lower(name)`) declared **outside** the class body.
3. Update Pydantic in/out models, the route, and the coordinator form; the
   form↔schema contract is guarded by `tests/test_form_contract.py`.
4. `alembic upgrade head` against Neon — a missing migration shows up as a
   500 on the gadget list.

**Add a public page**
Add the route to `gadget_pages.py` using `_shell(...)` (header, footer, SEO
head come for free), or link the shared header assets from a static page.

**Add a taxonomy option type or admin setting**
Table + migration + `taxonomy.py` helpers + `/api/admin/...` CRUD in
`admin.py` + a panel in coordinator **Catalog settings** + read it from
`/options` for the traveller form.

**Add a country** (India, Nepal, Sri Lanka)
Create `app/data/countries/<code>/` with `admin.json` (divisions, districts
with coordinates), `destinations.json` (curated spots), optional
`catalog_seed.json`; register it in `services/destination/countries.py`;
plugs come from `plugs.json`. Seed divisions for that country. No code path
may assume `BD` — use `home_country()` / the trip's country.

**Seed catalog data**
Edit `catalog_seed.json` (products by destination, plus a `variants` map),
run `python -m scripts.seed_catalog --dry-run`, then for real. Seeded prices
are illustrative until real vendor data replaces them.

## Pitfalls already paid for

- **Neon pooler (`-pooler` host) = PgBouncer transaction mode.**
  `app/db/engine.py` uses `NullPool`, `statement_cache_size=0` and unique
  prepared-statement names. Don't "simplify" it.
- **Gemini 3 thinking shares the output budget** — keep
  `thinking_level=MINIMAL`; report `MAX_TOKENS` as truncation.
- Global gazetteers misplace ~11% of Bangladeshi districts; trust
  `admin.json`, not a geocoder, for division membership.
- Neon responses can be slow: when checking pages in the browser, wait for
  the data before judging the UI.
- Don't chain `pkill …;` in front of other commands in one shell call — it
  can abort the rest. Restart the server in its own step.

## Tests

`tests/` is offline (an autouse fixture makes network and LLM calls raise);
`tests/db/` needs `TEST_DATABASE_URL` (never equal to `DATABASE_URL` — it
truncates). `tests/db/test_migrations.py` fails if models and migrations
drift. Add tests next to the feature (`test_gadget_pages.py`, `test_slug.py`,
`test_taxonomy.py`, …) — and remember: run the suite only when asked.

## Not built yet

Deployment (Procfile, CORS lockdown, prod secrets), response caching,
deterministic guardrails (drone / power-bank rules as data), reviews backend
("Share experience" is a stub), self-service sign-up (accounts are by
invitation), consent-based Facebook contributor channel.
