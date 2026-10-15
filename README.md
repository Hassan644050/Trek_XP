# Trek_XP

Tells a traveller which gadgets they actually need for a specific trip.

You fill in a short form — where you are going, when, what kind of trip, what
you plan to do there — and Trek_XP combines destination facts (climate, plug
type, voltage) with gadget knowledge to return a prioritised packing list, with
the reasoning and the sources behind each item.

> **Status: working end to end, not yet deployed.** Travellers get real
> model-generated lists; coordinators have a full catalog area with sign-in,
> images and placements. The community catalog is modelled and ready but not
> yet wired into `/recommend`.

**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the system fits
together, request flows, the data model, and the extension seams.

## Setup

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add your LLM API key
```

## Run

```bash
uvicorn app.main:app --reload
```

Interactive docs: http://127.0.0.1:8000/docs

## Tests

```bash
pytest
```

The suite runs offline: external services (Open-Meteo, the LLM provider) are
faked, and any test that reaches the network fails loudly. No API key needed.

## Design notes

- **Structured input, not free text.** `TripRequest` is a validated form, which
  removes the need for an entity-extraction LLM call — one round trip per
  request instead of two, and bad input is rejected before any spend.
- **`GadgetSource` is the seam.** v1 uses the LLM's own knowledge. A
  community-contributed, coordinator-verified gadget catalog plugs in behind the
  same interface later, and every `Recommendation` carries `origin` +
  `verified` so customers can tell reviewed entries from generated ones.
- **`TripContext` decouples fetching from generating.** Routes assemble the
  context; gadget sources only consume it. Tests build a context literal rather
  than mocking HTTP.
- **Guardrails are data, not prompts.** Restrictions (drone bans, airline
  power-bank limits) belong in a rules file that is checked deterministically,
  so they are testable without the LLM and can be curated by the same community
  workflow as the catalog.
- **Provider-agnostic LLM layer** carried over from its predecessor: Gemini and
  NVIDIA NIM sit behind one `LLMProvider` interface chosen by env var.

## Coordinator area

A signed-in page at **`/coordinator`** where coordinators enter gadgets
(name, category, description, image) and say where they apply: a
destination, one or more trip types, and optional activities, with a
priority and a reason. Admins also manage coordinator accounts there.

### One-time setup

1. Create a PostgreSQL database (we use [Neon](https://neon.tech); pick the
   Singapore region) and put its connection string in `.env` as
   `DATABASE_URL`. Never commit it or paste it anywhere public.
2. Create the tables:
   ```bash
   alembic upgrade head
   ```
3. Create the first admin (prompts for the password, hidden):
   ```bash
   python -m scripts.create_admin
   ```
   Run it again with the same email to reset a forgotten admin password.
4. Start the app and open http://127.0.0.1:8000/coordinator.

There is no public sign-up: admins create coordinator accounts from the
**Accounts** tab.

### Seeding the catalog

To start travellers off with something rather than an empty catalog, a
dataset of generic travel products organized by destination ships in
`app/data/countries/bd/catalog_seed.json`. Load it with:

```bash
python -m scripts.seed_catalog          # --dry-run to preview
```

It creates the places, gadgets and placements behind those products, and
is safe to re-run: existing places (by name and coordinates), gadgets (by
name) and placements (by gadget-and-place) are left untouched. Coordinators
refine from there — adding photos, brands and more destinations.

### Adding a country

Bangladesh is the first market; the data is keyed by country so others
(India, Nepal, Sri Lanka) are a data drop-in rather than a code change.
Each country lives in `app/data/countries/<code>/` (lowercase ISO code):

| File | Contents |
|---|---|
| `destinations.json` | `{"country": {"code", "name"}, "divisions": [...]}` — the curated spots shown in the picker, grouped by division, one marked `"default": true` |
| `admin.json` | `{"divisions": [{"name", "districts": [{"name", "lat", "lon", "also?"}]}]}` — administrative areas, for manual places and region-level catalog matching |
| `catalog_seed.json` *(optional)* | Generic products by destination, loaded by `python -m scripts.seed_catalog <code>` |

Plug and voltage data is already global (`app/data/plugs.json`, keyed by
country). The app discovers the new folder automatically; set
`HOME_COUNTRY` to make it the default the home page opens on, or pass
`?country=<code>` to `/destinations/featured`. No code changes, and the
region-matching and manual-place flows work for it as soon as its
`admin.json` is present.

### Places the map services do not know

Spots like **Sada Pathor**, **Bichanakandi** and **Nilgiri** are in no
public gazetteer: Open-Meteo has no entry, and OpenStreetMap has only a
hotel named after one. Typing a nearby town is worse than useless —
"Bholaganj" resolves to a different Bholaganj 30 km away, and
"Companiganj" to the one in Noakhali, 200 km away.

So when **Look up** finds nothing, the form offers division → district
dropdowns instead. The district supplies the coordinates, which is precise
enough for climate (and so for gear), and records which Bholaganj is meant.
Once saved, the place is searchable for every coordinator.

District coordinates live in `app/data/countries/bd/admin.json` (8 divisions, 64
districts), taken from OpenStreetMap administrative boundaries. It is
static for the same reason the plug data is — but also because global
gazetteers get roughly 11% of Bangladeshi districts wrong, matching
same-named places hundreds of kilometres away. Renamed districts keep
their former spellings as aliases, so Chittagong, Comilla, Jessore and
Bogra all still match.

### Security model

- Passwords hashed with argon2id; accounts lock for 15 minutes after 5
  failed sign-ins.
- Sessions live in the database (revocable); the browser holds only an
  HttpOnly, SameSite=Strict cookie. Sign-out, deactivation and password
  resets end sessions immediately.
- Every write must carry the `X-Requested-With: trekxp` header (CSRF).
- Roles: **admin** (accounts + catalog) and **coordinator** (catalog).
- Uploaded images are checked by content, limited to 5 MB, resized to
  1200px and re-encoded as WebP, which strips EXIF data such as GPS location.
- Set `COOKIE_SECURE=true` in production (HTTPS only).

### Images in production

Local disk (`media/`) in development; **Cloudflare R2** in production, because
free hosting tiers erase disks on each deploy. Set the five `R2_*` variables in
`.env.example` and R2 is used automatically — setting only some of them is
refused at startup, since that would store images where the app cannot serve
them.

In the Cloudflare dashboard you need to: create a bucket, create an *Object
Read & Write* API token scoped to it, and turn on public access (the `r2.dev`
subdomain to start with, or a custom domain). Uploading does **not** make a
bucket readable.

### Database tests

Tests in `tests/db/` run against a real database when `TEST_DATABASE_URL`
is set, and are skipped otherwise. Use a **separate** database (e.g. a Neon
branch named `test`): the tests empty its tables, and refuse to run if it
matches `DATABASE_URL`.

## Roadmap

| Step | Scope |
|------|-------|
| 1 | ✅ Models, `GadgetSource` ABC, route skeleton |
| 2 | ✅ Destination services — Open-Meteo climate, OpenStreetMap landmarks, static plug data |
| 3 | ✅ `LLMGadgetSource` with structured JSON output and bounded timeouts |
| 4 | ✅ Coordinator area — auth, catalog, placements, image upload |
| 5 | ✅ Test suite (235 tests, offline by default) |
| 6 | ✅ Cloudflare R2 image storage |
| 7 | Deploy — Procfile, pinned Python, CORS lockdown, `alembic upgrade head` |
| 8 | Wire `CommunityCatalogSource` into `/recommend` so verified entries reach travellers |
| 9 | Guardrails pass over a `restrictions.json` data file |
| 10+ | Response cache → vector search → consent-based Facebook contributor channel |

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/recommend` | Gadget recommendations for a trip |
| `GET` | `/destinations` | Destination search for the picker |
| `GET` | `/destinations/featured` | Curated spots, grouped by division |
| `GET` | `/health` | Health check |
| `GET` | `/gadget/{slug}` | Public, SEO-friendly gadget detail page (server-rendered) |
| `GET` | `/gadgets` | Public index of all gadgets |
| `GET` | `/coordinator` | Coordinator page |
| `POST` | `/api/auth/login`, `/api/auth/logout` · `GET /api/auth/me` | Sign in / out, current user |
| `GET`, `POST` | `/api/coordinator/gadgets` | List / create gadgets |
| `GET`, `PATCH`, `DELETE` | `/api/coordinator/gadgets/{id}` | Read / update / delete a gadget |
| `PUT`, `DELETE` | `/api/coordinator/gadgets/{id}/image` | Upload / remove a gadget image |
| `POST` | `/api/coordinator/gadgets/{id}/placements` | Recommend a gadget for a destination |
| `PATCH`, `DELETE` | `/api/coordinator/placements/{id}` | Edit / remove a placement |
| `GET` | `/api/coordinator/places`, `/api/coordinator/places/lookup` | Saved places; full geocoder lookup |
| `POST` | `/api/coordinator/places/manual` | Save a place no gazetteer knows, by district |
| `GET` | `/api/coordinator/options`, `/api/coordinator/admin-areas` | Form choices; divisions and districts |
| `GET`, `POST` · `PATCH` | `/api/admin/users` · `/api/admin/users/{id}` | Manage accounts (admin only) |
