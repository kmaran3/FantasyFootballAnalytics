# Architecture: AI Draft Copilot

## Decision record

| Decision | Choice | Why | Tradeoff |
|----------|--------|-----|----------|
| Agent runtime | Single Gemini call with tool-augmented prompt (no ADK, no multi-agent) | The 5-agent sequential pipeline takes 10-20s. A single `gemini-2.5-flash` call with pre-computed tool outputs injected into the prompt hits <5s p90 (NFR-1). | Loses multi-turn agent orchestration, but we don't need it — the tools are deterministic Python functions whose outputs can be computed in <100ms and injected into one prompt. |
| Streaming | SSE via Flask `Response(generator, mimetype='text/event-stream')` + gevent workers | Flask natively supports generator-based SSE. Gevent makes long-lived connections non-blocking. Railway supports gevent. | Adds `gevent` and `google-genai` to requirements. Minimal risk — gevent is a drop-in worker swap. |
| Copilot backend location | Embedded in Flask (new `copilot.py` blueprint) | Avoids inter-service latency, shared deployment, no new infra. The tool functions are pure Python — they port directly. | `views.py` is already 4000 lines. A separate blueprint keeps it clean. |
| Gemini SDK | `google-genai` (official Python SDK) — direct API call, not ADK | ADK adds session management, MCP server spawn, and async orchestration overhead we don't need. The SDK's `generate_content_stream()` gives us SSE tokens directly. | Can't use ADK's sub-agent delegation. Not needed — we pre-compute tool outputs. |
| ML model loading | Copy pickle files into `webapp/copilot/models/` and load with `lru_cache` at first request | Same pattern as the AIAgent project. Only 3 files (~5MB total): `combined_predictions_{ppr,half_ppr,standard}.pkl`. | Increases deploy artifact size by ~5MB. Acceptable. |
| Fallback without API key | Rule-based response formatter wrapping existing `ai-suggest` logic | Same data, formatted as markdown chat response. No conditional rendering in the UI. (NFR-12, NFR-13) | Fallback responses are less conversational but still accurate. |

---

## Component architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (draft_board.js)                                           │
│                                                                     │
│  ┌──────────────┐  ┌──────────────────────┐  ┌───────────────────┐ │
│  │ Draft Board   │  │ Copilot Panel (right) │  │ AI Bar (bottom)   │ │
│  │ + Sync Poll   │  │ - Best Available bar  │  │ (existing, kept)  │ │
│  │               │  │ - Chat thread         │  │                   │ │
│  │               │  │ - Input + Send        │  │                   │ │
│  └──────┬───────┘  └──────────┬───────────┘  └────────┬──────────┘ │
│         │                     │                        │            │
│   applyPick()          POST /copilot/chat        POST /ai-suggest  │
│   → fetchAISuggestions()  (EventSource SSE)      (existing, unchanged)│
│   → updateBestAvailBar()                                            │
└─────────┬─────────────────────┬────────────────────────┬────────────┘
          │                     │                        │
          ▼                     ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Flask Backend                                                      │
│                                                                     │
│  views.py (existing)          copilot.py (new blueprint)            │
│  ├─ /draft-board/ai-suggest   ├─ POST /draft-board/copilot/chat     │
│  │  (rule-based, <100ms)      │  → validate & rate-limit            │
│  │                            │  → run tool functions (sync, <100ms)│
│  │                            │  → build prompt with tool outputs   │
│  │                            │  → call Gemini stream               │
│  │                            │  → SSE generator yield chunks       │
│  │                            │  → on error: fallback to rule-based │
│  │                            │                                     │
│  │                            ├─ copilot_tools.py                   │
│  │                            │  (ported from AIAgent app/tools/)   │
│  │                            │  - analyze_roster()                 │
│  │                            │  - get_best_value_picks()           │
│  │                            │  - get_positional_scarcity()        │
│  │                            │  - get_player_projection()          │
│  │                            │  - compare_players()                │
│  │                            │                                     │
│  │                            ├─ models/                            │
│  │                            │  combined_predictions_ppr.pkl       │
│  │                            │  combined_predictions_half_ppr.pkl  │
│  │                            │  combined_predictions_standard.pkl  │
│  │                            │                                     │
│  │                            └─ prompt_builder.py                  │
│  │                               (assembles system + user prompt)   │
│  └────────────────────────────────────────────────────────────────  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## File plan

New files to create:

| File | Purpose |
|------|---------|
| `webapp/copilot/__init__.py` | Blueprint registration |
| `webapp/copilot/routes.py` | `/draft-board/copilot/chat` SSE endpoint |
| `webapp/copilot/copilot_tools.py` | Ported tool functions (roster, value, scarcity, projections) |
| `webapp/copilot/prompt_builder.py` | Builds the Gemini prompt from context + tool outputs |
| `webapp/copilot/models/` | Directory for pickle files (copied from AIAgent) |

Files to modify:

| File | Change |
|------|--------|
| `webapp/__init__.py` | Register copilot blueprint |
| `webapp/templates/draft_board.html` | Add copilot panel HTML + mobile tab |
| `webapp/static/js/draft_board.js` | Add copilot panel JS (toggle, chat, SSE, Best Available bar) |
| `webapp/static/css/draft_board.css` | Copilot panel styles |
| `requirements.txt` | Add `google-genai`, `gevent` |
| `Procfile` | Change to `gunicorn -k gevent -w 4 app:app` |
| `railway.toml` | Update `startCommand` to match |

---

## Data flow: chat request lifecycle

```
User clicks Send
  │
  ▼
1. Client JS assembles payload:
   {
     message: "Who should I draft?",
     context: {
       user_roster: [...],           // from DB.userRoster
       available_players: [...top30], // from DB.players filtered by DB.drafted, sorted by rank
       roster_slots: {...},           // from DB.rosterSlots
       scoring_format: "ppr",        // from DB.scoringFormat
       num_teams: 12,                // from DB.numTeams
       current_pick: 25,             // from DB.currentPickNo
       user_slot: 1,                 // from DB.userSlot
       league_type: "redraft"        // from DB.leagueType
     }
   }
  │
  ▼
2. Client opens EventSource: POST /draft-board/copilot/chat
   (fetch with ReadableStream, not EventSource — POST not supported by EventSource API)
  │
  ▼
3. Server: validate request
   - Check auth (login_required)
   - Check rate limit (10/min/user, in-memory counter dict)
   - Validate message length (≤2000 chars)
   - Validate context fields present
  │
  ▼
4. Server: run tool functions synchronously (~50-100ms total)
   a. analyze_roster(user_roster, roster_slots) → positional_gaps, bye_conflicts
   b. get_best_value_picks(available_players, current_pick, num_teams) → top_value_picks
   c. get_positional_scarcity(available_players, ['QB','RB','WR','TE']) → scarcity_levels
   d. get_player_projection(top candidates) → ppg, vbd, model agreement
  │
  ▼
5. Server: build prompt (prompt_builder.py)
   - System prompt: coordinator instructions (ported from AIAgent, trimmed)
   - Context block: roster, gaps, available players with projections
   - Tool outputs block: value picks, scarcity, roster analysis
   - User message
   Total: ~2000-3000 tokens input
  │
  ▼
6. Server: call Gemini
   - google.genai.Client(api_key=GEMINI_API_KEY)
   - model.generate_content_stream(prompt)
   - If GEMINI_API_KEY is None → skip, go to fallback (step 8)
  │
  ▼
7. Server: SSE generator
   - For each chunk from Gemini stream:
     yield f"data: {json.dumps({'type': 'chunk', 'text': chunk_text})}\n\n"
   - On final chunk:
     yield f"data: {json.dumps({'type': 'done', 'best_available': {...}})}\n\n"
  │
  ▼
8. Fallback path (no API key, or Gemini error/timeout):
   - Run existing ai-suggest logic (positional needs + targets + BPA)
   - Format as markdown: "## Recommended: **{target.name} ({target.position})**\n..."
   - Return as single SSE event with type 'done'
```

---

## Prompt design

The key architectural insight: instead of running 5 LLM agents sequentially (each making its own Gemini call), we run the **tool functions** (pure Python, deterministic, fast) and inject their outputs into a **single Gemini prompt**. This collapses 5+ Gemini roundtrips into 1.

### System prompt (trimmed coordinator prompt)

```
You are the Draft Copilot for a fantasy football draft board. You help users
make optimal draft picks based on their roster needs, available players, and
league settings.

You have been given pre-computed analysis from specialist tools:
- ROSTER ANALYSIS: positional gaps and bye week conflicts
- VALUE ANALYSIS: best value picks relative to current draft position
- SCARCITY ANALYSIS: how many startable players remain at each position
- PROJECTIONS: ML model predictions (PPG, VBD) for top candidates

Use this analysis to provide:
1. **#1 Recommended pick** with clear reasoning
2. **2-3 alternatives** with brief rationale
3. **Risk note** if any (injury, rookie uncertainty, model disagreement)

Rules:
- Never recommend a drafted player (they are not in the available list)
- Never recommend a position that exceeds roster limits
- Always acknowledge positional need before recommending
- Factor in scoring format (PPR/half-PPR/standard) and league size
- Flag rookies or low-confidence projections
- Be concise — this is a live draft, the user needs quick answers
```

### User prompt template

```
LEAGUE: {num_teams}-team {scoring_format} {league_type}
ROSTER SLOTS: {roster_slots}
MY PICK: #{current_pick} (slot {user_slot})

MY ROSTER:
{roster_list or "Empty — first pick"}

ROSTER ANALYSIS:
{tool output: positional gaps, bye conflicts}

AVAILABLE PLAYERS (top 30 by value):
{name | pos | team | ppg | vbd | value_delta}

VALUE PICKS:
{tool output: top 5 value picks with steal/reach assessment}

POSITIONAL SCARCITY:
{tool output: remaining startable players per position, scarcity levels}

USER QUESTION: {message}
```

---

## Client-side architecture

### Copilot panel structure

```html
<!-- Inside #db-active, after .db-board-center -->
<div class="db-copilot-panel" id="db-copilot-panel" style="display:none">
  <!-- Best Available bar -->
  <div class="db-copilot-bav" id="db-copilot-bav">
    <span class="db-copilot-bav-label">Best Pick For You</span>
    <div class="db-copilot-bav-player" id="db-copilot-bav-player">
      <!-- Populated by JS: position badge + name + ppg + reason -->
    </div>
  </div>

  <!-- Chat thread -->
  <div class="db-copilot-messages" id="db-copilot-messages" role="log" aria-live="polite">
    <!-- Welcome message rendered by JS on first open -->
  </div>

  <!-- Input -->
  <div class="db-copilot-input-wrap">
    <input type="text" id="db-copilot-input" class="db-copilot-input"
           placeholder="Ask about your draft..." maxlength="2000"
           aria-label="Draft copilot message">
    <button id="db-copilot-send" class="db-copilot-send" aria-label="Send message">
      <svg><!-- send icon --></svg>
    </button>
  </div>
</div>

<!-- Toggle button, inside #db-topbar -->
<button class="db-copilot-toggle" id="db-copilot-toggle" style="display:none"
        aria-label="Toggle AI Copilot" title="AI Draft Copilot">
  ✦
</button>
```

### Mobile integration

On screens ≤768px, the copilot panel is hidden and a third tab ("Copilot") is added to `#db-drawer .db-drawer-tabs`. When active, it renders the same chat UI inside `#db-drawer-body`.

### JS additions to `draft_board.js`

```javascript
// --- Copilot state ---
DB.copilotMessages = [];       // {id, role, content, status, timestamp}
DB.copilotOpen     = false;
DB.copilotAbort    = null;     // AbortController for in-flight stream

// --- Key functions ---

function toggleCopilot() {
  // Toggle panel visibility, update DB.copilotOpen
  // On first open: render welcome message
}

function sendCopilotMessage() {
  // 1. Read input, validate length
  // 2. Add user message to DB.copilotMessages, render it
  // 3. Abort any in-flight stream (DB.copilotAbort)
  // 4. Show typing indicator
  // 5. Build payload from DB state
  // 6. fetch('/draft-board/copilot/chat', { method: 'POST', body, signal })
  // 7. Read response as streaming text:
  //    const reader = response.body.getReader();
  //    while (true) {
  //      const {done, value} = await reader.read();
  //      // parse SSE lines, append to copilot bubble, scroll to bottom
  //    }
  // 8. On 'done' event: update Best Available bar, finalize message
  // 9. On error/timeout: show fallback + error message
}

function updateCopilotBestAvail(data) {
  // Called from fetchAISuggestions callback (existing debounce)
  // Updates the Best Available bar in the copilot panel
  // Uses rule-based ai-suggest data — no LLM call
}

// Hook into existing flow:
// In applyPick() → the existing fetchAISuggestions debounce also calls updateCopilotBestAvail
// In initBoard() → show copilot toggle if not historical season
// In resetBoard() → hide copilot toggle, clear messages
```

### SSE client pattern (fetch + ReadableStream, not EventSource)

```javascript
const response = await fetch('/draft-board/copilot/chat', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(payload),
  signal: abortController.signal
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, {stream: true});

  // Parse SSE lines from buffer
  const lines = buffer.split('\n');
  buffer = lines.pop(); // keep incomplete line
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6));
      if (event.type === 'chunk') appendToCurrentBubble(event.text);
      if (event.type === 'done')  finalizeBubble(event.best_available);
      if (event.type === 'error') showFallback(event.fallback);
    }
  }
}
```

---

## Server-side: `copilot/routes.py`

```python
from flask import Blueprint, request, Response, stream_with_context, jsonify
import json, time, os
from .copilot_tools import analyze_roster, get_best_value_picks, get_positional_scarcity, get_player_projection
from .prompt_builder import build_prompt

copilot_bp = Blueprint('copilot', __name__)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
_rate_limits = {}  # user_id -> [timestamps]

@copilot_bp.route('/draft-board/copilot/chat', methods=['POST'])
@login_required
def copilot_chat():
    user_id = current_user.id

    # Rate limit: 10/min
    now = time.time()
    _rate_limits.setdefault(user_id, [])
    _rate_limits[user_id] = [t for t in _rate_limits[user_id] if now - t < 60]
    if len(_rate_limits[user_id]) >= 10:
        return jsonify(error="You're sending messages too quickly. Please wait a moment."), 429
    _rate_limits[user_id].append(now)

    data = request.get_json()
    message = (data.get('message') or '').strip()
    context = data.get('context', {})

    if not message or len(message) > 2000:
        return jsonify(error="Message must be 1-2000 characters."), 400

    # Run tool functions (~50-100ms)
    roster_analysis = analyze_roster(
        context.get('user_roster', []),
        context.get('roster_slots', {}),
        context.get('scoring_format', 'ppr'),
        context.get('num_teams', 12)
    )
    available = context.get('available_players', [])
    value_picks = get_best_value_picks(
        available,
        context.get('current_pick', 1),
        context.get('num_teams', 12),
        context.get('scoring_format', 'ppr')
    )
    scarcity = get_positional_scarcity(
        available,
        context.get('scoring_format', 'ppr')
    )

    prompt = build_prompt(message, context, roster_analysis, value_picks, scarcity)

    if not GEMINI_API_KEY:
        # Fallback: rule-based response
        fallback = _build_fallback(context, roster_analysis, value_picks)
        return Response(
            f"data: {json.dumps({'type': 'done', 'text': fallback, 'best_available': _bav(value_picks)})}\n\n",
            mimetype='text/event-stream'
        )

    def generate():
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content_stream(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            full_text = ''
            for chunk in response:
                if chunk.text:
                    full_text += chunk.text
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk.text})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'best_available': _bav(value_picks)})}\n\n"
        except Exception as e:
            fallback = _build_fallback(context, roster_analysis, value_picks)
            yield f"data: {json.dumps({'type': 'error', 'fallback': fallback})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
```

---

## Tools to port

Only 4 functions are needed from the AIAgent project. They are pure Python with pandas — no ADK, no MCP, no async:

| AIAgent source | Port to | What changes |
|----------------|---------|--------------|
| `app/tools/roster.py → analyze_roster()` | `copilot/copilot_tools.py` | Adjust pickle path. Remove ADK `@tool` decorator. Accept dict args instead of individual params. |
| `app/tools/value.py → get_best_value_picks()` | Same file | Same adjustments. Accept player list as dicts (name+position+ppg) instead of string names — avoids redundant player lookup. |
| `app/tools/value.py → get_positional_scarcity()` | Same file | Same. |
| `app/tools/projections.py → get_player_projection(), compare_players()` | Same file | Same. Copy `_load_combined_predictions()` with updated pickle path. |

Functions NOT ported (not needed):
- `league_parser.py` — league settings already come from the draft board
- `sleeper.py` — Sleeper API calls already handled by existing `views.py`
- `news_tools` — deferred to P2 (S12)
- `strategy_agent` logic — folded into the system prompt as rules, not as a separate tool

---

## Deployment changes

### Gunicorn configuration

```
# Procfile
web: gunicorn -k gevent -w 4 --timeout 30 app:app

# railway.toml [deploy] section
startCommand = "gunicorn -k gevent -w 4 --timeout 30 app:app"
```

**Why 4 workers:** Railway's smallest instance has 0.5 vCPU / 512MB. 4 gevent workers share the CPU cooperatively (greenlets, not processes). Each SSE stream yields control while waiting for Gemini chunks, so 4 concurrent copilot streams won't block regular requests.

**Why gevent over sync:** A sync worker blocks for the entire duration of an SSE response (~3-5s). With 1 sync worker (current config), the entire server hangs during a copilot request. Gevent's cooperative scheduling lets the worker serve other requests during I/O waits.

### New dependencies

```
# Add to requirements.txt
google-genai>=1.0.0
gevent>=24.0
```

### Environment variable

```
GEMINI_API_KEY=<key>   # Set in Railway dashboard, not committed
```

---

## Layout integration

### Desktop (≥769px)

```
┌─────────────────────────────────────────────────────────────┐
│ Topbar: league name | meta | sync badge | [✦ Copilot]      │
├───────────┬─────────────────────────────┬───────────────────┤
│ Available │     Draft Board Grid        │  Copilot Panel    │
│ Players   │     (scrollable)            │  ┌─────────────┐  │
│ (left)    │                             │  │ Best Avail   │  │
│           │                             │  ├─────────────┤  │
│           │                             │  │ Chat thread  │  │
│           │                             │  │ (scrollable) │  │
│           │                             │  ├─────────────┤  │
│           │                             │  │ [Input] [▶]  │  │
│           │                             │  └─────────────┘  │
├───────────┴─────────────────────────────┴───────────────────┤
│ Bottom Drawer: Rosters | AI Bar (existing)                  │
└─────────────────────────────────────────────────────────────┘
```

- Copilot panel: fixed width 360px, right side of `.db-layout`
- When collapsed: panel has `display:none`, board center takes full remaining width
- CSS transition: `width` and `opacity` over 300ms
- Panel does NOT overlay — it's a flex child that compresses the board center

### Mobile (≤768px)

The existing `#db-drawer` gets a third tab: "Copilot". When selected, `#db-drawer-body` renders the chat UI (Best Available bar + messages + input). No side panel on mobile.

---

## Rate limiting detail

In-memory dict keyed by `user_id`. Each entry is a list of request timestamps. On each request:
1. Prune entries older than 60s
2. If ≥10 remain → 429
3. Else append current timestamp

This is sufficient for the expected scale (10 concurrent users). No Redis/external store needed.

---

## Error & fallback matrix

| Scenario | Response |
|----------|----------|
| No `GEMINI_API_KEY` env var | Chat input disabled. Banner: "AI Copilot requires API key configuration." Best Available bar still works (rule-based). |
| Gemini returns 429 (rate limit) | SSE error event → chat shows: "I'm being rate-limited. Here's a quick suggestion:" + rule-based fallback formatted as markdown. |
| Gemini returns 500 or network error | Same as above. |
| Gemini response >15s (timeout) | `gevent.Timeout(15)` kills the generator. SSE error event with partial text + fallback. |
| User sends empty message | 400 error, input validation prevents send. |
| User sends >2000 chars | 400 error, client-side char counter prevents this. Server validates as backup. |
| Available players list is empty | Copilot responds: "The draft is complete — no more picks to make!" (handled in prompt builder). |
| Hallucinated player name in response | Post-processing: not implemented in v1 single-prompt approach. Mitigated by injecting only available player names in the prompt with instruction "Only recommend players from this list." |

---

## Handoff

Ready for the **fullstack-engineer** to implement against this architecture. Priority order:

1. **Deployment changes first** — switch to gevent workers, add dependencies. Deploy and verify existing functionality is unbroken.
2. **Port tool functions** — `copilot_tools.py` with the 4 functions + pickle files. Unit-testable in isolation.
3. **Build prompt builder** — `prompt_builder.py`. Testable with mock tool outputs.
4. **Build SSE endpoint** — `routes.py`. Test with curl before wiring up the frontend.
5. **Frontend: copilot panel HTML/CSS** — static layout first, no JS.
6. **Frontend: copilot JS** — toggle, chat, SSE streaming, Best Available bar updates.
7. **Mobile tab** — add Copilot tab to drawer.
8. **Fallback path** — test with `GEMINI_API_KEY` unset.

The architecture avoids the riskiest parts of the AIAgent system (ADK runtime, MCP server, multi-agent orchestration) while preserving all the value (ML projections, roster analysis, value/scarcity tools, coordinator prompt). The single-call-with-tool-injection pattern is the key design decision that makes 5s latency achievable.
