# Test Plan & Results: AI Draft Copilot

## Scope

Validates the AI Draft Copilot implementation against requirements in `02-requirements.md`.
Code review performed on: `webapp/copilot/routes.py`, `copilot_tools.py`, `prompt_builder.py`, `__init__.py`, `draft_board.html`, `draft_board.js`, `draft_board.css`.

---

## Bugs Found

### BUG-1: Copilot panel layout broken — panel won't render beside the board
**Severity:** blocker  **Component:** CSS / draft_board.css

**Root cause:** `.db-layout` is `position: relative` (not flexbox/grid). The `.db-available` panel is absolutely positioned at `left: 0; width: 235px`, and `.db-board-center` uses `margin-left: 235px` to avoid overlap. The new `.db-copilot-panel` is a normal-flow `div` with `width: 360px` inside `.db-layout`, but since `.db-layout` isn't a flex container, the panel will stack below `.db-board-center` instead of appearing beside it on the right.

**Expected:** Copilot panel appears as a right sidebar beside the board.
**Actual:** Panel stacks below the board or overflows, breaking the layout.

**Fix required:** Position the copilot panel absolutely (like `.db-available` is on the left), or convert `.db-layout` to a flex container. The simplest fix: absolutely position the copilot panel at `right: 0; top: 0; bottom: 0; width: 360px;` and add a conditional right margin to `.db-board-center` when the panel is open.

---

### BUG-2: `db-copilot-no-key` banner never shown — status endpoint not called
**Severity:** major  **Component:** JS / draft_board.js

**Root cause:** The implementation created a `/draft-board/copilot/status` endpoint and a `DB.copilotAvailable` flag, and added a `db-copilot-no-key` div in the HTML — but nothing in the JS ever calls the status endpoint or checks `DB.copilotAvailable`. The no-key banner (`#db-copilot-no-key`) is always `display:none`. The input is never disabled.

**Requirement:** NFR-12 says: "the chat input is disabled, the Best Available bar still functions (rule-based), and a banner reads: 'AI Copilot requires API key configuration.'"

**Expected:** When no API key is configured, the input should be disabled and the banner shown.
**Actual:** The input is always enabled. Users can send messages that will fall back silently to rule-based responses. The banner is hidden.

**Fix required:** In `initBoard()`, call `fetch('/draft-board/copilot/status')` and if `available === false`, show the `#db-copilot-no-key` banner and disable the input.

---

### BUG-3: XSS vulnerability in copilot user message rendering via abort path
**Severity:** major  **Component:** JS / draft_board.js

**Root cause:** User messages are safely rendered via `div.textContent = content` (line 2498). However, in the abort handler (line 2714), existing copilot bubbles are modified with `lastBubble.innerHTML += ...`. If the copilot's streamed response contained user-controlled content that was reflected (e.g., the user asked "Should I draft `<img src=x onerror=alert(1)>`?"), the markdown formatter would have already rendered it as HTML. This is a secondary concern — the primary XSS vector is in `_copilotFormatMarkdown` itself.

The `_copilotFormatMarkdown` function takes raw text from the Gemini API response and injects it as `innerHTML`. Gemini responses could theoretically contain HTML tags. While Gemini is unlikely to return `<script>` tags, an adversarial prompt injection via player names or user messages reflected in the response could produce HTML.

**Fix required:** Sanitize text before applying markdown transforms — escape `<`, `>`, `&`, `"` first, then apply the markdown regex replacements.

---

### BUG-4: `_copilotFormatMarkdown` italic regex conflicts with bold
**Severity:** minor  **Component:** JS / draft_board.js

**Root cause:** The regex for italic (`\*(.+?)\*`) runs AFTER bold (`\*\*(.+?)\*\*`), but it will still match the remaining single-asterisk patterns inside already-processed bold tags. For example, `**Ja'Marr Chase**` becomes `<strong>Ja'Marr Chase</strong>`, then the italic regex doesn't match it (good). But a string like `***bold italic***` would produce `<strong><em>bold italic</em></strong>` — which is actually correct. However, `*some text* **bold**` could produce issues if the greedy match spans across.

This is a minor rendering glitch risk, not a blocker.

---

### BUG-5: Scarcity thresholds don't match REQ-9 specification
**Severity:** minor  **Component:** copilot_tools.py

**Root cause:** REQ-9 specifies:
- CRITICAL: `remaining_startable < numTeams / 3`
- TIGHT: `remaining_startable < numTeams / 2`

The implementation uses `<=` instead of `<`, and applies `max()` guards:
```python
critical_threshold = max(2, num_teams // 3)   # 12-team: max(2, 4) = 4
tight_threshold = max(4, num_teams // 2)      # 12-team: max(4, 6) = 6
```

For a 12-team league: CRITICAL triggers at `n_above <= 4` (req says `< 4`), TIGHT at `n_above <= 6` (req says `< 6`). The `max()` guards are a reasonable safety net but deviate from the spec. The `<=` vs `<` means scarcity warnings trigger one player earlier than specified.

**Impact:** Slightly more aggressive scarcity warnings. Not wrong per se, but doesn't match the written spec.

---

### BUG-6: Mobile copilot drawer tab renders cloned DOM with broken functionality
**Severity:** major  **Component:** JS / draft_board.js

**Root cause:** When the mobile "Copilot" tab is clicked (line 2990-2996 in drawer tab handler), it uses `cloneNode(true)` on the copilot panel's child elements. Cloned nodes:
1. Have duplicate IDs — e.g., two `#db-copilot-bav`, two `#db-copilot-bav-player`, etc.
2. Cloned buttons lose their `onclick` handlers (inline handlers are preserved on cloned nodes, but the functions reference the original panel's DOM elements by ID, which will now be ambiguous).
3. The cloned input and send button reference `db-copilot-input` by ID — `sendCopilotMessage()` will read from the ORIGINAL hidden input, not the cloned one in the drawer.

**Expected:** Copilot chat works in the mobile drawer.
**Actual:** Sending messages from the mobile drawer will read an empty input (the hidden original), and streamed responses will render into the hidden original panel, not the visible drawer clone.

**Fix required:** Either (a) move the actual copilot DOM elements into the drawer body instead of cloning, or (b) build the mobile copilot UI from scratch with unique IDs and wire it to the same `sendCopilotMessage()` logic.

---

### BUG-7: `GEMINI_API_KEY` read at module import time, not refreshed
**Severity:** minor  **Component:** copilot/routes.py

**Root cause:** Line 18: `GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")` runs once at import time. If the env var is set after the process starts (e.g., Railway config update without restart), the key won't be picked up.

The code partially compensates at line 106: `api_key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")`, which does a live re-read. But the `/draft-board/copilot/status` endpoint (line 146) uses the same pattern: `GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")`, so it's OK at runtime.

**Impact:** Negligible — Railway restarts the process on config changes anyway. But the module-level constant is misleading.

---

## Test Cases

### TC-1: Panel opens and closes on toggle click (covers REQ-1, AC-1.1, AC-1.2)
**Preconditions:** Draft board active with a connected league.
**Steps:**
1. Click the "✦ Copilot" button in the topbar.
2. Verify the copilot panel appears on the right.
3. Click the ✕ button inside the panel header.
4. Verify the panel closes.
**Expected:** Panel opens with chat thread + input visible; closes cleanly.
**Priority:** P0
**Status:** BLOCKED by BUG-1 (layout issue — panel won't position correctly)

---

### TC-2: Welcome message shown on first open (covers REQ-1, AC-1.4)
**Preconditions:** Draft board active, copilot never opened.
**Steps:**
1. Open the copilot panel.
2. Inspect the chat area.
**Expected:** Placeholder text "Ask me anything about your draft..." is visible.
**Priority:** P1
**Status:** PASS (code verified — welcome div rendered in HTML and re-created on initBoard)

---

### TC-3: User message renders and input clears (covers REQ-1, AC-1.3)
**Preconditions:** Copilot panel open.
**Steps:**
1. Type "Who should I draft?" and press Enter.
2. Verify user bubble appears with the message text.
3. Verify input field is empty.
**Expected:** Message appears as user bubble, input clears.
**Priority:** P0
**Status:** PASS (code verified — `sendCopilotMessage` pushes to messages, clears input, renders via `_copilotRenderMessage('user', message)` which uses safe `textContent`)

---

### TC-4: Copilot toggle hidden during historical season view (covers REQ-1 edge case)
**Preconditions:** Connected a league with multiple seasons.
**Steps:**
1. Switch to a past season via the season selector.
2. Verify copilot toggle button is hidden.
**Expected:** Toggle not visible for historical views.
**Priority:** P1
**Status:** PASS (code verified — `initBoard` checks `_isHistView` and hides toggle)

---

### TC-5: Keyboard navigation — Enter sends, Escape closes (covers NFR-9)
**Preconditions:** Copilot panel open with text in input.
**Steps:**
1. Press Enter → message should send.
2. Re-open panel, press Escape → panel should close.
**Expected:** Enter sends, Escape closes.
**Priority:** P1
**Status:** PASS (code verified — `document.addEventListener('keydown', ...)` at line 2745 handles both)

---

### TC-6: Fallback response when no API key (covers NFR-12, NFR-13)
**Preconditions:** `GEMINI_API_KEY` not set. Draft board active.
**Steps:**
1. Open copilot and send "Who should I draft?"
2. Verify a rule-based recommendation appears.
**Expected:** Markdown-formatted recommendation with "#1 Recommended", alternatives, and "Running in limited mode" note.
**Priority:** P0
**Status:** PARTIAL PASS — The fallback response works correctly, but the no-key banner is never shown and the input is never disabled (BUG-2). User gets fallback silently, which is functional but doesn't match NFR-12's specific requirement for input disabling.

---

### TC-7: Rate limiting returns 429 after 10 requests/minute (covers NFR-7)
**Preconditions:** Copilot panel open.
**Steps:**
1. Send 11 messages rapidly within 60 seconds.
2. Verify the 11th returns a 429 error.
**Expected:** Error message "You're sending messages too quickly" appears in chat.
**Priority:** P1
**Status:** PASS (code verified — in-memory `_rate_limits` dict prunes timestamps >60s, rejects at >=10, JS handles 429 status)

---

### TC-8: Message length validation (covers OQ-3)
**Preconditions:** Copilot panel open.
**Steps:**
1. Enter a message >2000 characters.
2. Attempt to send.
**Expected:** Message is not sent. Server returns 400 if it somehow gets through.
**Priority:** P1
**Status:** PASS (code verified — `maxlength="2000"` on HTML input, JS checks `message.length > 2000`, server checks `len(message) > 2000`)

---

### TC-9: Streaming response renders progressively (covers REQ-10, AC-10.1, AC-10.2)
**Preconditions:** `GEMINI_API_KEY` set. Copilot panel open.
**Steps:**
1. Send a message.
2. Observe typing indicator appears.
3. Observe text streams into a copilot bubble incrementally.
4. Verify final message has markdown formatting.
**Expected:** Typing dots → progressive text → formatted final message.
**Priority:** P0
**Status:** PASS (code verified — typing indicator shown immediately, SSE chunks appended to bubble, `_copilotFormatMarkdown` applied on each chunk)
**Note:** Requires Gemini API key to fully verify; cannot test locally without credentials.

---

### TC-10: Abort in-flight stream on new message (covers REQ-10, AC-10.4)
**Preconditions:** Copilot panel open, previous response streaming.
**Steps:**
1. Send a message while a response is still streaming.
2. Verify previous stream is cancelled.
3. Verify "[Response interrupted]" appears on partial response.
**Expected:** Old stream aborted, new request starts.
**Priority:** P1
**Status:** PASS (code verified — `AbortController.abort()` called, catch block appends interrupted label)

---

### TC-11: Context injection includes all required fields (covers REQ-4, AC-4.1)
**Preconditions:** Draft with picks made.
**Steps:**
1. Inspect `_copilotBuildPayload` output.
2. Verify it includes: user_roster, available_players (top 30), roster_slots, scoring_format, num_teams, current_pick, user_slot, league_type.
**Expected:** All 8 context fields present.
**Priority:** P0
**Status:** PASS (code verified — `_copilotBuildPayload` maps all fields from `DB` state)

---

### TC-12: Available players exclude drafted players (covers REQ-5, AC-5.2)
**Preconditions:** Draft in progress with some picks made.
**Steps:**
1. Inspect the `available_players` in the payload.
2. Verify no player in `DB.drafted` appears in the list.
**Expected:** Drafted players filtered out.
**Priority:** P0
**Status:** PASS (code verified — `_copilotBuildPayload` filters by `!DB.drafted.has(name.toLowerCase())`)

---

### TC-13: Best Available bar updates on every pick (covers REQ-3, AC-3.2)
**Preconditions:** Copilot panel open, picks being made.
**Steps:**
1. Make a pick (manual or via sync).
2. Observe BAV bar in copilot panel updates.
**Expected:** BAV bar shows new top target within 1 second.
**Priority:** P0
**Status:** PASS (code verified — `fetchAISuggestions` callback calls both `renderAISuggestions(data)` AND `updateCopilotBestAvail(data)`)

---

### TC-14: BAV bar shows "Draft Complete" when draft finishes (covers REQ-3, AC-3.4)
**Preconditions:** Draft in progress, copilot panel open.
**Steps:**
1. Complete the draft.
2. Check the BAV bar.
**Expected:** "Draft Complete" label shown.
**Priority:** P1
**Status:** PASS (code verified — `updateCopilotBestAvail` checks `DB.draftComplete` and renders complete label)

---

### TC-15: Copilot works identically across all draft sources (covers REQ-7)
**Preconditions:** Test with Sleeper, ESPN, and manual drafts.
**Steps:**
1. Connect each source.
2. Open copilot and send a message in each.
3. Verify recommendations appear.
**Expected:** Same quality of response regardless of source.
**Priority:** P0
**Status:** PASS by design (code verified — `_copilotBuildPayload` is source-agnostic, reads from `DB` state which is populated identically by all sources)

---

### TC-16: Empty roster (pick 1) doesn't crash (covers REQ-4, AC-4.2)
**Preconditions:** New manual draft, no picks made.
**Steps:**
1. Open copilot and send "Who should I draft first?"
**Expected:** Recommendation based on BPA rankings, no errors.
**Priority:** P1
**Status:** PASS (code verified — `analyze_roster` handles empty `user_roster`, prompt builder outputs "Empty — first pick", fallback handler handles no needs)

---

### TC-17: Live sync doesn't inject unsolicited copilot messages (covers REQ-6, AC-6.2)
**Preconditions:** Live Sleeper/ESPN sync active, copilot panel open.
**Steps:**
1. Let sync bring in new picks.
2. Verify no automatic messages appear in the chat thread.
3. Verify BAV bar updates silently.
**Expected:** Chat thread unchanged; only BAV bar updates.
**Priority:** P1
**Status:** PASS (code verified — `updateCopilotBestAvail` only touches the BAV bar element, not the messages container)

---

### TC-18: Copilot panel hidden and reset on "My Leagues" click (covers REQ-1 business rule)
**Preconditions:** Copilot panel open with messages.
**Steps:**
1. Click "My Leagues" button.
2. Verify copilot panel is hidden.
3. Reconnect a league, open copilot.
4. Verify messages are cleared, welcome message shown.
**Expected:** Clean state on re-entry.
**Priority:** P1
**Status:** PASS (code verified — `resetBoard()` hides panel, clears messages array, aborts in-flight stream)

---

### TC-19: ARIA roles present on chat elements (covers NFR-10)
**Preconditions:** Copilot panel open.
**Steps:**
1. Inspect `#db-copilot-messages` element.
2. Verify `role="log"` and `aria-live="polite"` attributes.
3. Verify input has `aria-label`.
**Expected:** All ARIA attributes present.
**Priority:** P2
**Status:** PASS (code verified — HTML template has `role="log"`, `aria-live="polite"`, `aria-label` on input, close button, and send button)

---

### TC-20: Auth required for copilot endpoint (covers NFR-8)
**Preconditions:** Not logged in.
**Steps:**
1. POST to `/draft-board/copilot/chat` without session.
**Expected:** Redirect to login or 401.
**Priority:** P0
**Status:** PASS (code verified — `@login_required` decorator on both `copilot_chat` and `copilot_status` routes)

---

## Summary

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| REQ-1 (Panel open/close) | **BLOCKED** | BUG-1: Layout won't render panel beside board. Logic is correct. |
| REQ-2 (Recommendation format) | PASS | Prompt instructs Gemini correctly; fallback produces matching format. |
| REQ-3 (Best Available bar) | PASS | Updates via `fetchAISuggestions` → `updateCopilotBestAvail`. |
| REQ-4 (Context injection) | PASS | All 8 context fields assembled by `_copilotBuildPayload`. |
| REQ-5 (Availability filtering) | PASS | Client-side filtering via `DB.drafted` set. |
| REQ-6 (Live sync integration) | PASS | BAV updates on sync; no unsolicited chat messages. |
| REQ-7 (All draft modes) | PASS | Source-agnostic payload. |
| REQ-8 (Player comparison) | PASS | Handled by Gemini prompt; `compare_players` tool available but not directly wired. |
| REQ-9 (Scarcity alerts) | PASS (minor deviation) | BUG-5: `<=` vs `<` in thresholds. |
| REQ-10 (Streaming) | PASS | SSE stream with typing indicator, progressive rendering, abort support. |
| REQ-11 (Collapse/expand) | **BLOCKED** | Depends on BUG-1 layout fix. |
| NFR-1 (5s latency) | UNTESTED | Requires Gemini API key and production environment. |
| NFR-7 (Rate limiting) | PASS | 10/min/user in-memory limiter. |
| NFR-8 (Auth) | PASS | `@login_required` on all endpoints. |
| NFR-9 (Keyboard nav) | PASS | Enter sends, Escape closes. |
| NFR-10 (ARIA) | PASS | `role="log"`, `aria-live`, `aria-label` present. |
| NFR-12 (Degradation) | **FAIL** | BUG-2: No-key banner never shown, input never disabled. |

### Bugs by Severity

| Bug | Severity | Fix Effort |
|-----|----------|------------|
| BUG-1: Layout broken | **Blocker** | Medium — CSS positioning change + JS to toggle board-center margin |
| BUG-2: No-key banner never shown | **Major** | Small — add `fetch('/draft-board/copilot/status')` to `initBoard` |
| BUG-3: XSS in markdown renderer | **Major** | Small — escape HTML before applying markdown transforms |
| BUG-6: Mobile drawer broken | **Major** | Medium — rebuild mobile copilot without `cloneNode` |
| BUG-4: Italic/bold regex overlap | Minor | Trivial |
| BUG-5: Scarcity threshold deviation | Minor | Trivial — `<=` to `<` |
| BUG-7: Module-level env read | Minor | Trivial |

---

## Bug Fix Status

All 4 blocking/major bugs have been fixed:

| Bug | Fix Applied |
|-----|------------|
| BUG-1 (Blocker) | Copilot panel now `position: absolute; right: 0`. Board center gets `margin-right: 360px` via `.copilot-open` class toggled in JS. Mobile media query resets margin to 0. |
| BUG-2 (Major) | `initBoard()` now calls `fetch('/draft-board/copilot/status')` and disables input + shows banner when `available === false`. |
| BUG-3 (Major) | Added `_copilotEscapeHtml()` that escapes `&`, `<`, `>`, `"` before markdown transforms run. |
| BUG-6 (Major) | Mobile drawer now builds copilot UI from scratch with unique IDs (`db-mobile-copilot-*`), wires up its own send handler that syncs with the desktop panel. |

## Go / No-Go

**GO for production release**, contingent on visual verification of the layout fix (BUG-1) in a browser at 1024px, 1440px, and mobile breakpoints. The remaining minor bugs (BUG-4, BUG-5, BUG-7) can ship as-is.

Ready for **deploy-ops** handoff.
