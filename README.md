# Go with the Flow

A voice-first assistant that decides what you should do right now, based on your time,
budget, mood and surroundings — using live web data, not a hardcoded list.

```
You:  I have two hours and I'm bored.
Bot:  Let's fix that. Where are you right now, and roughly how much do you want to spend?
You:  Downtown Dubai, 50 AED, no restaurants, something relaxing.
Bot:  Got it — Downtown Dubai, 2 hours, around 50 AED, chill vibe, no restaurants. Indoor or outdoor?
You:  Either is fine.       → searches live, returns 3–5 options with prices/hours and why each fits
You:  That's too expensive. → keeps every other slot, lowers only the budget, searches again
```

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export ELEVENLABS_API_KEY=...        # optional, see "Voice" below
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000, hit **Talk** and speak. Typing works too.

## Voice

With `ELEVENLABS_API_KEY` set, the browser records your mic and posts it to `/api/voice`,
which runs ElevenLabs Scribe speech-to-text, feeds the transcript to the *same* agent the
typed `/api/turn` endpoint uses, and the reply is spoken by ElevenLabs via `/api/speak`.
The voice layer only moves audio in and out — conversation state and slot logic are
untouched by it, so a spoken turn and a typed turn are indistinguishable to the agent.

Without a key the UI falls back to the browser's Web Speech API, and `/api/voice` and
`/api/speak` return 503. Override the voice or models with `ELEVENLABS_VOICE_ID`,
`ELEVENLABS_STT_MODEL`, `ELEVENLABS_TTS_MODEL`.

## How it works

| Layer | File | Responsibility |
| --- | --- | --- |
| State | `app/state.py` | The slots (`location`, `free_time_hours`, `budget_aed`, `exclusions`, `vibe`, `environment` + optional extras) and when there's enough to search |
| Extraction & refinement | `app/extraction.py` | Pulls slots out of natural speech; refinements ("too expensive", "closer", "more active", "less time") change *only* the slot they refer to |
| Live search | `app/search.py` | Builds queries from the current state, hits a live search backend, then fetches pages to confirm price / opening hours; round-up articles are expanded into individual, priceable suggestions |
| Ranking | `app/recommend.py` | Scores each live hit on budget, environment, vibe, duration, location and live-info quality; drops exclusions and junk; returns the top 3–5 with reasons |
| Voice | `app/voice.py` | ElevenLabs speech-to-text and text-to-speech; a thin adapter around the agent, not a second conversation engine |
| Dialogue | `app/dialog.py` | Asks only for what's missing, then searches; keeps state across turns |

Nothing is hardcoded: every recommendation comes from a live query made at the moment you ask.

### Search backends

Keyless by default (DuckDuckGo via `ddgs`). Set one of these to upgrade:

```bash
export TAVILY_API_KEY=...    # or SERPER_API_KEY / BRAVE_API_KEY
export SEARCH_PROVIDER=tavily  # optional, otherwise auto-detected
```

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/turn` | `{session_id, utterance}` → `{reply, state, recommendations, changed}` |
| `POST /api/voice` | multipart `audio` + `session_id` → the same payload plus the `transcript` |
| `POST /api/speak` | `{text}` → `audio/mpeg` of the spoken reply |
| `GET /api/state` | Current slots for a session |
| `POST /api/reset` | Start over |
| `GET /api/health` | Which search backend is live |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q     # slot extraction, refinement, ranking, dialogue (network mocked)
.venv/bin/ruff check .
```
