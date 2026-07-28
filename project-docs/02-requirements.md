# Requirements: AI Draft Copilot

## Scope reference

Covers PRD stories **P0 (S1–S7)** and **P1 (S8–S11)**. P2 stories (S12–S14) and Won't stories (W1–W3) are excluded from this document.

---

## Functional requirements

### REQ-1 — Chat panel open/close (S1, S11)

**Description:** A collapsible chat panel on the draft board where the user types natural-language messages to the AI copilot.

**Acceptance criteria:**

- **AC-1.1** Given the draft board is active (any source: Sleeper, ESPN, or manual), When the user clicks the copilot toggle button, Then a chat panel slides open on the right side of the board without reflowing the draft grid or left panel.
- **AC-1.2** Given the chat panel is open, When the user clicks the toggle button again (or a close/collapse icon inside the panel), Then the panel collapses and the board layout returns to its pre-open state.
- **AC-1.3** Given the chat panel is open, When the user types a message into the input field and presses Enter or clicks the send button, Then the message appears in the chat thread as a user bubble and the input field clears.
- **AC-1.4** Given the chat panel is open and empty (no messages yet), Then a placeholder/welcome message is displayed: "Ask me anything about your draft — who to pick, player comparisons, or strategy questions."
- **AC-1.5** Given the chat panel is collapsed, Then the copilot toggle button remains visible and shows an icon (e.g., sparkle/AI icon) so the user can re-open it.

**Business rules:**
- The panel must not exist before `initBoard()` completes — it is only available during an active draft session.
- The panel state (open/collapsed) does not persist across page reloads; it defaults to collapsed.
- The toggle button is hidden on the setup screen and only shown after a league is connected or manual draft is started.

**Edge cases & errors:**
- If the user double-clicks the toggle rapidly, the panel must not get stuck in an intermediate state. Use a CSS transition with pointer-events disabled during animation.
- If the draft board is in a historical season view (standings mode, no active draft), the copilot toggle button is hidden — copilot is only available during drafts.
- On screens narrower than 768px (mobile), the chat panel is rendered as a tab ("Copilot") inside the existing mobile slide-up drawer (`#db-drawer`) alongside "Available" and "Your Team" tabs, not as a side panel.

---

### REQ-2 — Copilot recommendation format (S2)

**Description:** The copilot responds with a structured recommendation: #1 pick, 2–3 alternatives, and rationale tied to roster needs and league format.

**Acceptance criteria:**

- **AC-2.1** Given the user sends a message asking who to pick (e.g., "Who should I draft?", "What's my best pick?"), When the copilot responds, Then the response includes: (a) a clearly labeled #1 recommendation with player name and position, (b) 2–3 alternative players with brief reasoning, and (c) a rationale paragraph referencing at least one of: roster need, positional scarcity, value over ADP, or league format.
- **AC-2.2** Given the copilot responds, Then every player name mentioned in the recommendation exists in the current `DB.players` list and is not in `DB.drafted`.
- **AC-2.3** Given the copilot responds, Then the response is rendered as formatted markdown (bold player names, bullet lists for alternatives) inside a copilot message bubble.

**Business rules:**
- The copilot must never recommend a player who has already been drafted. The backend must filter the available player list before passing it to the agent pipeline.
- The copilot must never recommend a player at a position that would exceed the user's roster slot limits (e.g., recommending a 3rd QB when `rosterSlots.QB = 1` and bench is full). The agent's roster analysis tool enforces this.
- If the copilot's #1 recommendation is a player not found in `DB.players` (hallucination), the backend must strip it and fall back to the top-ranked available player by VBD.

**Edge cases & errors:**
- If no players are available (board is full / draft is over), the copilot responds: "The draft is complete — no more picks to make!"
- If the user's roster is completely empty (pick 1), the copilot should recommend based purely on VBD/projection rankings without referencing roster gaps.
- If fewer than 3 alternatives exist (e.g., late rounds with few players left), return as many as are available without padding.

---

### REQ-3 — Best Available bar (S3)

**Description:** A persistent bar above the chat thread showing the top recommended player for the user's team, updating after each pick.

**Acceptance criteria:**

- **AC-3.1** Given the chat panel is open and at least one pick has been made, Then a "Best Available" bar is displayed above the chat messages showing: player name, position badge, projected PPG, and a one-line reason (e.g., "Fills your RB1 need").
- **AC-3.2** Given a new pick is applied to the board (via sync or manual entry), Then the Best Available bar updates within 1 second to reflect the new board state.
- **AC-3.3** Given the chat panel is collapsed, Then the Best Available bar is not visible (it lives inside the panel).
- **AC-3.4** Given the draft is complete, Then the Best Available bar is hidden and replaced with a summary label: "Draft Complete."

**Business rules:**
- The Best Available computation uses the same positional-need + VBD logic as the existing `ai-suggest` endpoint's target selection — it picks the highest-value player at the user's most-needed position.
- This bar updates on every pick (not just the user's picks) because opponent picks change availability and scarcity.
- The bar does NOT require a Gemini API call — it uses the rule-based logic from the existing `ai-suggest` endpoint for speed.

**Edge cases & errors:**
- If the `ai-suggest` request fails (network error), the bar shows the last known recommendation with a stale indicator (dimmed opacity + "May be outdated" tooltip).
- If no position has a need score > 0 (all starter slots filled), the bar shows the overall #1 ranked available player regardless of position.

---

### REQ-4 — Automatic context injection (S4)

**Description:** The copilot backend automatically receives the user's full draft context without the user needing to provide it.

**Acceptance criteria:**

- **AC-4.1** Given the user sends any chat message, When the backend processes it, Then the following context is included in the prompt to the AI agent pipeline: (a) `DB.userRoster` — full list of user's drafted players with positions, (b) `DB.rosterSlots` — league roster slot configuration, (c) `DB.scoringFormat` — ppr/half_ppr/standard, (d) `DB.numTeams` — league size, (e) `DB.currentPickNo` — current overall pick number, (f) `DB.userSlot` — user's draft slot position, (g) top 30 available players by VBD rank (names, positions, projected PPG, VBD).
- **AC-4.2** Given the user has drafted 0 players, Then the context still includes an empty roster and all available context fields — no null/undefined values crash the pipeline.
- **AC-4.3** Given the league is a dynasty/keeper league, Then `DB.leagueType` is also included in the context so the agent can factor in long-term value.

**Business rules:**
- Available players are capped at 30 (sorted by VBD rank) to stay within LLM context limits and keep response times under 5 seconds.
- The context is assembled server-side from the POST payload — the client sends the raw data, the server formats the prompt.
- Player names in the available list must be normalized (title case, trimmed) to reduce ambiguity.

**Edge cases & errors:**
- If `DB.userSlot` is `null` or `0` (e.g., manual draft with no slot assigned), omit draft-slot-specific advice ("you pick 3rd") but still provide roster-need and BPA recommendations.
- If `DB.scoringFormat` is missing, default to `'ppr'` and include a note in the response: "Assuming PPR scoring."
- If `DB.rosterSlots` contains non-standard slots (e.g., `SUPER_FLEX`, `REC_FLEX`), pass them through — the agent's roster analysis tool already handles these.

---

### REQ-5 — Real-time available player filtering (S5)

**Description:** The copilot only recommends players who are currently undrafted.

**Acceptance criteria:**

- **AC-5.1** Given Player X is in `DB.drafted`, When the user asks "Should I draft Player X?", Then the copilot responds: "Player X has already been drafted" and does NOT include them as a recommendation.
- **AC-5.2** Given the backend receives the available player list, Then every player in that list is verified to NOT be in the `DB.drafted` set before being passed to the agent pipeline.
- **AC-5.3** Given the agent pipeline returns a recommendation, Then the backend validates that every recommended player name matches a player in the available list. Any non-matching name is stripped from the response.

**Business rules:**
- The `DB.drafted` set is the single source of truth for player availability. It is updated by `applyPick()` on every pick from any source (sync, manual, mock).
- The client sends the filtered available list (already excluding drafted players) in the chat request payload. The server does not re-derive availability.

**Edge cases & errors:**
- If the agent hallucinates a player name not in the available list or the full player database, the backend strips it and appends: "Note: Some suggested players were unavailable and have been removed."
- If two players share a similar name (e.g., "Josh Allen QB" vs "Josh Allen LB"), the available list includes position to disambiguate. The agent must reference both name and position.

---

### REQ-6 — Live sync integration (S6)

**Description:** The copilot's context updates automatically as the live draft sync polling brings in new picks.

**Acceptance criteria:**

- **AC-6.1** Given live sync is active (Sleeper or ESPN, polling at 5s intervals), When a new pick arrives via `syncDraft()`, Then `applyPick()` fires, which triggers the debounced `fetchAISuggestions()` (400ms), which updates the Best Available bar.
- **AC-6.2** Given the chat panel is open and a new pick arrives, Then the Best Available bar updates but the chat thread is NOT interrupted — no automatic new message is injected. The user must ask for an updated recommendation.
- **AC-6.3** Given the draft transitions from `pre_draft` to `in_progress` (detected by sync), Then the copilot toggle button becomes enabled and the panel can be opened.

**Business rules:**
- The copilot does NOT generate unsolicited chat messages on every pick — that would flood the thread. Only the Best Available bar updates automatically.
- The copilot's context (available players, roster, pick number) is assembled fresh from `DB` state at the moment the user sends a message, so it always reflects the latest sync.
- If the user sends a message while a sync response is being processed, the message uses the pre-sync state. This is acceptable — the next message will have the updated state.

**Edge cases & errors:**
- If sync stops (3 consecutive errors, click-to-retry state), the copilot continues to work with the last known board state. No special degradation message unless the user asks "Is the draft still going?"
- If the draft completes mid-conversation (detected by sync), the Best Available bar transitions to "Draft Complete" and the copilot's next response acknowledges the draft is over.

---

### REQ-7 — Works in all draft modes (S7)

**Description:** The copilot functions identically whether the user is in a live Sleeper draft, live ESPN draft, or manual/mock draft.

**Acceptance criteria:**

- **AC-7.1** Given the user is in a manual draft (source = 'manual'), When they open the copilot and send a message, Then the copilot provides recommendations based on the manually-entered roster slots, manually-placed picks, and the available player list — identical in quality to a synced draft.
- **AC-7.2** Given the user is in an ESPN draft with authentication cookies, When they use the copilot, Then recommendations reflect ESPN-synced picks and rosters.
- **AC-7.3** Given the user is running a mock draft (Run Mock Draft button), When they use the copilot, Then recommendations update as mock picks are placed.

**Business rules:**
- The copilot backend is source-agnostic — it receives roster, available players, and settings from the client regardless of source. No source-specific branching in the copilot logic.
- The only difference by source is how picks arrive (sync vs. manual entry), which is handled upstream of the copilot.

**Edge cases & errors:**
- If a manual draft has no `userSlot` defined (user didn't specify their position), the copilot omits draft-position-specific advice but still provides roster-need and BPA recommendations.
- If an ESPN league's cookies expire mid-draft (401 error on sync), the copilot continues to work with stale data. The sync error is surfaced by the existing sync badge, not by the copilot.

---

### REQ-8 — Player comparison (S8)

**Description:** The user can ask the copilot to compare two or more specific players side-by-side.

**Acceptance criteria:**

- **AC-8.1** Given the user sends "Compare Player A and Player B", When the copilot responds, Then it returns a structured comparison including: projected PPG for each, VBD rank, positional scarcity context, fit with user's roster, and a recommendation of which to pick.
- **AC-8.2** Given the user names a player who has already been drafted, Then the copilot responds: "Player X has already been drafted" and compares only the remaining available players.
- **AC-8.3** Given the user names a player not found in the database (misspelling or non-existent), Then the copilot responds: "I couldn't find 'Playerr Name'. Did you mean [closest match]?" using fuzzy name matching.

**Business rules:**
- Comparisons are limited to 5 players per request. If the user names more than 5, the copilot responds: "I can compare up to 5 players at a time. Which 5 would you like?"
- The comparison must factor in the user's specific roster context (e.g., "Player A fills your WR2 slot, but you already have 3 WRs").

**Edge cases & errors:**
- If all named players have been drafted, the copilot says: "All of those players have been drafted. Would you like me to suggest alternatives?"
- If only one player is named, the copilot provides that player's full projection profile rather than a comparison.

---

### REQ-9 — Positional scarcity alerts (S9)

**Description:** The copilot proactively warns when a position group is running thin.

**Acceptance criteria:**

- **AC-9.1** Given the user asks for a recommendation, When a position the user still needs has a scarcity level of CRITICAL (fewer than `numTeams / 3` startable players remaining) or TIGHT (fewer than `numTeams / 2`), Then the copilot includes a scarcity warning in its response: e.g., "Warning: Only 4 startable RBs remain on the board."
- **AC-9.2** Given no positions are at CRITICAL or TIGHT scarcity, Then no scarcity warning is included (avoid noise).
- **AC-9.3** Given a position the user does NOT need is at CRITICAL scarcity, Then the copilot does not warn about it unless the user explicitly asks.

**Business rules:**
- "Startable" is defined as a player projected above the positional replacement baseline (the VBD > 0 threshold from the ML model).
- Scarcity is computed from the available (undrafted) player list at query time. Thresholds scale with league size:
  - CRITICAL: `remaining_startable < numTeams / 3`
  - TIGHT: `remaining_startable < numTeams / 2`
  - MODERATE/DEEP: above those thresholds (no warning)

**Edge cases & errors:**
- In a 2-QB or Superflex league, QB scarcity thresholds are doubled (QBs are consumed faster).
- If the model data is missing VBD for some players, those players are excluded from the startable count (conservative estimate).

---

### REQ-10 — Streaming responses (S10)

**Description:** Copilot responses stream progressively to the UI instead of appearing all at once.

**Acceptance criteria:**

- **AC-10.1** Given the user sends a message, When the copilot begins generating a response, Then a typing indicator (pulsing dots) appears in the chat thread within 500ms.
- **AC-10.2** Given the backend begins streaming, Then text appears in the copilot's response bubble incrementally (word-by-word or chunk-by-chunk) as it is generated.
- **AC-10.3** Given the response is fully streamed, Then the typing indicator disappears and the full message is rendered with final markdown formatting.
- **AC-10.4** Given the user sends a new message while a previous response is still streaming, Then the previous stream is cancelled (aborted), a "[Response interrupted]" label is appended to the partial response, and the new message is processed.

**Business rules:**
- Streaming uses Server-Sent Events (SSE) or chunked transfer encoding from the Flask backend. WebSockets are not required for this unidirectional stream.
- If streaming is not feasible for v1 (Gemini API constraint), fall back to: show typing indicator immediately, then render the full response when complete. This satisfies perceived performance even without true streaming.

**Edge cases & errors:**
- If the SSE connection drops mid-stream (network interruption), append "[Connection lost — response may be incomplete]" to the partial message and show a "Retry" button.
- If the backend times out (>15 seconds), cancel the stream, show the partial response if any, and append a rule-based fallback suggestion from `ai-suggest` with the label: "Quick suggestion while the AI catches up."

---

### REQ-11 — Panel collapse/expand (S11)

*Covered by REQ-1 (AC-1.1, AC-1.2, AC-1.5). No additional requirements beyond those.*

---

## Data requirements

### Entities

| Entity | Fields | Type | Required | Validation | Notes |
|--------|--------|------|----------|------------|-------|
| **CopilotMessage** (client-side only) | `id` | string (uuid) | yes | auto-generated | Unique message ID |
| | `role` | enum: 'user' \| 'copilot' | yes | — | Who sent it |
| | `content` | string | yes | max 2000 chars (user), no limit (copilot) | Message body (markdown for copilot) |
| | `timestamp` | ISO 8601 string | yes | auto-generated | Render time |
| | `status` | enum: 'sending' \| 'streaming' \| 'complete' \| 'error' | yes | — | For streaming state |
| **CopilotSession** (server-side, in-memory) | `session_id` | string | yes | matches draft session | Ties to current draft |
| | `messages` | list of `{role, content}` | yes | max 50 messages | Conversation history for context window |
| | `league_settings` | dict | yes | — | Cached from first request |

### Data flow

1. **Client → Server (POST `/draft-board/copilot/chat`):**
   ```json
   {
     "message": "Who should I draft next?",
     "context": {
       "user_roster": [{"name": "...", "position": "QB"}, ...],
       "available_players": [{"name": "...", "position": "RB", "ppg": 18.2, "vbd": 45.3}, ...],
       "roster_slots": {"QB": 1, "RB": 2, ...},
       "scoring_format": "ppr",
       "num_teams": 12,
       "current_pick": 25,
       "user_slot": 1,
       "league_type": "redraft"
     }
   }
   ```

2. **Server → Client (SSE stream or JSON response):**
   ```json
   {
     "response": "## My #1 Pick: **Ja'Marr Chase (WR)**\n\n...",
     "best_available": {"name": "Ja'Marr Chase", "position": "WR", "ppg": 19.8, "reason": "Fills WR1 need"},
     "scarcity_warnings": [{"position": "RB", "remaining": 4, "level": "CRITICAL"}]
   }
   ```

### Retention
- `CopilotMessage` history exists only in client-side JS memory (`DB.copilotMessages` array). It is not persisted to the database or included in `DraftBoardSession` save state.
- `CopilotSession` on the server is in-memory only, keyed by draft session. It is discarded when the server restarts or the draft ends.
- No PII is stored — messages contain only player names and draft strategy.

---

## Non-functional requirements

### Performance
- **NFR-1:** Copilot response (first token or full response) must return within **5 seconds** for 90th percentile of requests. Measured from the moment the user presses Send to the moment text appears in the chat.
- **NFR-2:** Best Available bar update must complete within **1 second** of a pick being applied. This uses the rule-based `ai-suggest` endpoint, not the LLM pipeline.
- **NFR-3:** Chat panel open/close animation must complete within **300ms** and not cause layout jank (no reflow of the draft grid).
- **NFR-4:** The copilot backend must handle **10 concurrent requests** without degradation (one per active draft session, with headroom).

### Security & privacy
- **NFR-5:** The Gemini API key must be stored as an environment variable (`GEMINI_API_KEY`), never in client-side code, templates, or committed to the repository.
- **NFR-6:** User chat messages are not logged to disk or database. They exist only in memory during the session.
- **NFR-7:** Rate limiting: maximum **10 copilot chat requests per minute per user session**. Exceeding the limit returns HTTP 429 with message: "You're sending messages too quickly. Please wait a moment."
- **NFR-8:** The copilot endpoint requires the same authentication as other draft-board endpoints (session-based auth via `@login_required` or equivalent).

### Accessibility
- **NFR-9:** The chat panel must be keyboard-navigable: Tab to input, Enter to send, Escape to close panel.
- **NFR-10:** Chat messages must have appropriate ARIA roles (`role="log"` for the thread, `role="status"` for the typing indicator).
- **NFR-11:** Color contrast in the chat panel must meet WCAG AA (4.5:1 for body text, 3:1 for large text/UI components).

### Reliability
- **NFR-12:** If the Gemini API key is not configured, the copilot must degrade gracefully: the chat input is disabled, the Best Available bar still functions (rule-based), and a banner reads: "AI Copilot requires API key configuration. Contact your admin."
- **NFR-13:** If the Gemini API returns an error (500, rate limit, timeout), the copilot displays an error message in the chat: "I'm having trouble thinking right now. Here's a quick suggestion:" followed by the rule-based `ai-suggest` result formatted as a recommendation.

---

## Open questions

| # | Question | Impact | Recommended default |
|---|----------|--------|---------------------|
| OQ-1 | Should conversation history be sent to Gemini on each request (multi-turn) or should each message be independent (single-turn with full context)? | Multi-turn gives continuity but increases token cost and latency. Single-turn is simpler. | **Single-turn with context.** Each request sends the full draft context + the user's current message. The client keeps message history for display, but the server does not send prior conversation turns to Gemini. This keeps latency predictable and avoids token bloat. Revisit for P2 story S14 (conversation memory). |
| OQ-2 | Should the copilot panel replace the existing `db-ai-bar` (needs/targets/BPA pills) or coexist alongside it? | Layout space, redundancy between BPA bar and existing pills. | **Coexist.** The existing `db-ai-bar` in the bottom drawer continues to function as-is (rule-based, fast updates). The copilot is a separate right-side panel for deeper chat interaction. The Best Available bar inside the copilot panel is a richer version (with reasoning) of the same data. |
| OQ-3 | What is the maximum message length a user can send? | Prompt injection risk, token cost. | **2000 characters.** Sufficient for any draft question. Enforce client-side with a character counter and server-side with validation. |
| OQ-4 | Should the copilot panel width be fixed or resizable? | UX, implementation complexity. | **Fixed at 360px.** Keeps implementation simple. The board center column compresses slightly — acceptable given most boards have horizontal scroll already. |
| OQ-5 | How do we handle the agent pipeline when Gemini quota is exhausted for the day? | Complete loss of copilot functionality. | **Fall back to rule-based.** Same as NFR-12/NFR-13 — format the `ai-suggest` output as a conversational response. Prefix with: "I'm running on limited mode right now. Here's what I'd suggest based on your roster needs:" |

---

## Risk-flagged requirements

The following requirements carry the most architectural risk and should receive priority attention from the solution architect:

1. **REQ-10 (Streaming)** — Requires SSE or chunked transfer encoding from Flask, which has implications for the WSGI server (gunicorn workers, async support). If the deployment uses sync workers, streaming may block a worker for the full response duration.
2. **NFR-1 (5-second latency target)** — The full 5-agent pipeline (Coordinator → Roster → Value → Strategy → Projection) makes multiple sequential Gemini calls. Achieving <5s p90 may require running agents in parallel or trimming the pipeline.
3. **REQ-4 + REQ-5 (Context injection + availability filtering)** — The copilot's value depends entirely on accurate context. Any mismatch between client-side `DB` state and what the agent sees will produce bad recommendations.
4. **NFR-12 (Graceful degradation without API key)** — Must be designed from the start, not bolted on. The rule-based fallback path needs to produce responses formatted identically to the LLM path so the chat UI doesn't need conditional rendering.

---

## Handoff

Ready for the **solution-architect** to design against these requirements. Key architecture inputs:

- **NFR-1 (5s latency)** is the hardest constraint. The existing AIAgent pipeline runs 5 sequential agents — the architect must decide whether to parallelize, trim, or cache.
- **REQ-10 (streaming)** has deployment implications — Railway uses gunicorn; SSE requires async workers or a different approach.
- **OQ-1 (single-turn vs. multi-turn)** affects both token cost and session state management.
- The existing `ai-suggest` endpoint and `fetchAISuggestions()` debounce are the integration seam — the copilot should hook into the same trigger for Best Available bar updates.
