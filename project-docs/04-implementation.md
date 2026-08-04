# Implementation: AI Draft Copilot

## What was built

A chat-based AI copilot panel integrated into the draft board that provides real-time draft recommendations using Groq 2.5 Flash with pre-computed ML model analysis.

## Files created

| File | Purpose |
|------|---------|
| `webapp/copilot/__init__.py` | Blueprint registration (`copilot_bp`) |
| `webapp/copilot/routes.py` | SSE endpoint `/draft-board/copilot/chat` with rate limiting, streaming, and fallback |
| `webapp/copilot/copilot_tools.py` | Ported tool functions: `analyze_roster`, `get_best_value_picks`, `get_positional_scarcity`, `get_player_projection`, `compare_players` |
| `webapp/copilot/prompt_builder.py` | Prompt assembly (`build_prompt`) and rule-based fallback (`build_fallback_response`) |
| `webapp/copilot/models/*.pkl` | 3 pre-computed ML prediction files (PPR, half-PPR, standard) |

## Files modified

| File | Change |
|------|--------|
| `webapp/__init__.py` | Registered `copilot_bp` blueprint |
| `webapp/templates/draft_board.html` | Added copilot toggle button in topbar, copilot panel in layout, mobile "Copilot" tab in drawer |
| `webapp/static/js/draft_board.js` | Added copilot state to `DB`, toggle/send/stream functions, BAV bar updates, keyboard handlers, mobile drawer tab handler, init/reset hooks |
| `webapp/static/css/draft_board.css` | Full copilot panel styles (panel, header, BAV bar, chat messages, typing indicator, input, mobile hide) |
| `requirements.txt` | Added `openai>=1.0.0`, `gevent>=24.0`, `unidecode>=1.3.0` |
| `Procfile` | Changed to `gunicorn -k gevent -w 4 --timeout 30 app:app` |
| `railway.toml` | Updated `startCommand` to match Procfile |

## Architecture decisions & deviations

1. **Single Groq call (as designed)**: Tool functions run synchronously (~50-100ms), outputs injected into one prompt. No ADK, no multi-agent pipeline.
2. **SSE streaming via `stream_with_context`**: Uses Flask's generator-based SSE with gevent workers. Client uses `fetch + ReadableStream` (not `EventSource`) since POST is required.
3. **Copilot status endpoint**: Added `/draft-board/copilot/status` (GET) to check API key availability — not in the original architecture but needed for the client to know whether to disable the input.
4. **No `gevent.Timeout`**: Omitted the 15s timeout wrapper from the architecture. The gunicorn `--timeout 30` covers this. If needed, can add later.

## How to run

1. **Local dev (without Groq)**: Run Flask normally. The copilot will work in fallback mode (rule-based recommendations formatted as markdown).
2. **With Groq**: Set `GROQ_API_KEY` environment variable, then run with `gunicorn -k gevent -w 4 --timeout 30 app:app`.
3. **Railway**: Add `GROQ_API_KEY` to the Railway dashboard environment variables. Deploy — the updated `railway.toml` handles the rest.

## How to test

1. Connect a league (Sleeper, ESPN, or manual)
2. Click the "✦ Copilot" button in the topbar
3. Type a question like "Who should I draft?" and press Enter
4. Verify:
   - Typing indicator appears
   - Response streams in progressively (with Groq key) or appears at once (fallback)
   - Best Available bar updates after picks
   - Panel closes on ✕ or Escape
   - Rate limit kicks in after 10 rapid messages

## What needs credentials to test

- **Groq API key** (`GROQ_API_KEY`): Required for LLM-powered responses. Without it, fallback mode produces rule-based suggestions.
- **Pickle model files**: Already included in `webapp/copilot/models/`. These need numpy/pandas version compatibility with the deployment environment.

## Follow-ups

- P2: News agent integration (S12) — would require Google Search API access
- P2: Confidence indicators (S13) — model agreement data is available in `get_player_projection` (ridge_pred vs xgb_pred)
- P2: Conversation memory (S14) — currently single-turn; would need server-side session history

## Handoff

Ready for **qa-engineer** to validate against the requirements in `project-docs/02-requirements.md`. Key areas:
- REQ-1: Panel open/close, keyboard navigation, mobile drawer tab
- REQ-2: Recommendation format (needs Groq key for full test, fallback testable without)
- REQ-3: Best Available bar updates after picks
- REQ-6: Live sync integration (BAV updates from `fetchAISuggestions` debounce)
- REQ-10: Streaming response rendering
- NFR-7: Rate limiting (10/min)
- NFR-12: Graceful degradation without API key
