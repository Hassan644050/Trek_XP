# Trek_XP

Tells a traveller which gadgets they actually need for a specific trip.

You fill in a short form — where you are going, when, what kind of trip, what
you plan to do there — and Trek_XP combines destination facts (climate, plug
type, voltage) with gadget knowledge to return a prioritised packing list, with
the reasoning and the sources behind each item.

> **Status: v1 scaffold.** The request/response shapes and the source
> abstraction are in place. `POST /recommend` currently returns `501` — the
> destination and gadget services are the next build step.

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

## Roadmap

| Step | Scope |
|------|-------|
| 1 | ✅ Models, `GadgetSource` ABC, route skeleton |
| 2 | Destination services (Open-Meteo climate, REST Countries plug/voltage) in parallel |
| 3 | `LLMGadgetSource` with structured JSON output |
| 4 | Guardrails pass over `restrictions.json` |
| 5 | Tests + demoable v1 |
| 6+ | Redis cache → vector search → community catalog → MCP → streaming |

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/recommend` | Gadget recommendations for a trip |
| `GET` | `/health` | Health check |
