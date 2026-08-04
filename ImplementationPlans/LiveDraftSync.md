# Live Draft Sync — Implementation Plan

## Overview

Enable real-time live draft tracking for both **Sleeper** and **ESPN** leagues on the Draft Board. When a user connects a league with an active or upcoming draft, the board should automatically detect and sync picks as they happen with minimal delay.

**Current State:**
- Sleeper: Polling exists at 30s intervals, only for `in_progress` drafts
- ESPN: Backend sync endpoint exists (`/draft-board/espn/sync`) but frontend never calls it — zero live capability
- Pre-draft: Board renders but no mechanism to detect when a draft starts

**Target State:**
- Both Sleeper and ESPN poll at **5-second intervals** during live drafts
- Pre-draft drafts show the empty board with a "Go Live" button; user manually starts polling
- Pre-draft polling (once started) uses a slower **30-second** interval, then auto-switches to 5s when draft begins
- Unified sync architecture — one polling system handles both platforms

---

## Architecture

### Unified Sync Flow

```
initBoard(cfg)
  └─ if draft is in_progress → startPolling() at 5s
  └─ if draft is pre_draft   → show "Go Live" button, no polling
  └─ if draft is complete    → show "Draft complete", no polling

User clicks "Go Live" (pre_draft)
  └─ startPolling() at 30s (slow pre-draft interval)
  └─ On each sync: if draft_status changes to in_progress → switch to 5s

syncDraft() [unified function, replaces syncFromSleeper]
  └─ if DB.source === 'sleeper' → fetch /draft-board/sleeper/sync
  └─ if DB.source === 'espn'    → fetch /draft-board/espn/sync
  └─ Response format is identical → same processing logic
```

### Key Design Decisions

1. **Unified `syncDraft()` function** — The Sleeper and ESPN sync endpoints return identical response formats (`picks`, `team_rosters`, `draft_status`, `roster_player_names`). One frontend function handles both; only the URL construction differs.

2. **5-second live interval** — ~12 API calls/min per user. Both Sleeper and ESPN APIs handle this comfortably. The backend proxies these calls so browser CORS isn't an issue.

3. **30-second pre-draft interval** — Saves API calls while waiting for the draft to start. Auto-transitions to 5s when `draft_status` flips to `in_progress`.

4. **Manual "Go Live" for pre-draft** — No automatic polling on pre-draft connection. User sees the empty board and clicks "Go Live" when they're ready to start watching.

5. **No WebSockets** — Both Sleeper and ESPN are REST-only APIs with no push mechanism. Polling is the only option.

---

## Implementation Steps

### Phase 1: Refactor Polling to Unified System

**File: `webapp/static/js/draft_board.js`**

#### Step 1.1: Update Poll Interval Constants

```javascript
// Replace:
const POLL_INTERVAL_MS = 30000;

// With:
const POLL_LIVE_MS     = 5000;    // 5s during active draft
const POLL_PREDRAFT_MS = 30000;   // 30s while waiting for draft to start
let   _currentPollMs   = POLL_LIVE_MS;
```

**Location:** Line ~1738

#### Step 1.2: Rename `syncFromSleeper()` → `syncDraft()`

Refactor the existing `syncFromSleeper()` function (lines 1774-1844) into a unified `syncDraft()` that works for both platforms:

```javascript
async function syncDraft() {
    if (!DB.leagueId) return;

    // Build URL based on source
    let url;
    if (DB.source === 'sleeper') {
        if (!DB.draftId) return;
        url = `/draft-board/sleeper/sync?draft_id=${encodeURIComponent(DB.draftId)}&league_id=${encodeURIComponent(DB.leagueId)}`;
    } else if (DB.source === 'espn') {
        url = `/draft-board/espn/sync?league_id=${encodeURIComponent(DB.leagueId)}`;
        if (DB.espnCookies) {
            url += `&espn_s2=${encodeURIComponent(DB.espnCookies.espn_s2)}&swid=${encodeURIComponent(DB.espnCookies.swid)}`;
        }
    } else {
        return; // manual source — no polling
    }

    try {
        const res  = await fetch(url);
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'sync error');

        DB.syncErrorCount = 0;
        DB.lastSyncAt     = new Date();
        _secondsLeft      = _currentPollMs / 1000;

        // ── Pre-draft → in_progress transition ──────────────
        if (data.draft_status === 'in_progress' && _currentPollMs !== POLL_LIVE_MS) {
            // Draft just started! Switch to fast polling
            _currentPollMs = POLL_LIVE_MS;
            clearInterval(DB.syncInterval);
            clearInterval(_countdownTimer);
            DB.syncInterval = setInterval(syncDraft, POLL_LIVE_MS);
            _startCountdown();
            _secondsLeft = POLL_LIVE_MS / 1000;
        }

        // ── Apply roster changes ────────────────────────────
        // (existing roster processing logic — unchanged)

        // ── Apply new draft picks ───────────────────────────
        // (existing pick detection/application logic — unchanged)

        // ── Draft complete? ─────────────────────────────────
        if (data.draft_status === 'complete' || DB.currentPickNo >= DB.numTeams * DB.numRounds) {
            stopPolling();
            DB.draftComplete = true;
            setSyncStatus('paused', 'Draft complete');
            updateCurrentPickBar();
            renderDraftCompleteAnalysis();
        } else if (data.draft_status === 'pre_draft') {
            setSyncStatus('live', `Waiting for draft · checking in ${_secondsLeft}s`);
        } else {
            setSyncStatus('live', `Live · next sync in ${_secondsLeft}s`);
        }

        scheduleSaveState();

    } catch (e) {
        DB.syncErrorCount++;
        if (DB.syncErrorCount >= 3) {
            stopPolling();
            setSyncStatus('error', '⚠ Sync paused — click to retry');
        } else {
            setSyncStatus('paused', `Retrying… (${DB.syncErrorCount})`);
        }
    }
}
```

**Key changes from current `syncFromSleeper()`:**
- URL construction branched by `DB.source` (sleeper vs espn)
- ESPN URL includes `espn_s2` and `swid` query params from `DB.espnCookies`
- Auto-detects `pre_draft → in_progress` transition and switches from 30s → 5s polling
- Shows "Waiting for draft" status during pre-draft polling
- After 3 errors: stops polling entirely and shows clickable retry status (instead of continuing)
- All response processing (roster changes, pick detection, draft complete) is identical — no branching needed since response formats match

#### Step 1.3: Update `startPolling()`

```javascript
function startPolling(intervalMs) {
    _currentPollMs = intervalMs || POLL_LIVE_MS;
    if (DB.syncInterval) clearInterval(DB.syncInterval);
    if (_countdownTimer)  clearInterval(_countdownTimer);

    syncDraft();   // immediate first fetch
    DB.syncInterval = setInterval(syncDraft, _currentPollMs);
    _startCountdown();
}
```

**Change:** Accept optional `intervalMs` parameter. Default to `POLL_LIVE_MS` (5s).

#### Step 1.4: Update `_startCountdown()`

```javascript
function _startCountdown() {
    _secondsLeft = _currentPollMs / 1000;
    clearInterval(_countdownTimer);
    _countdownTimer = setInterval(() => {
        _secondsLeft--;
        if (_secondsLeft <= 0) {
            _secondsLeft = _currentPollMs / 1000;
        }
        if (DB.syncErrorCount === 0 && DB.lastSyncAt) {
            const lbl = document.getElementById('db-sync-label');
            if (lbl) {
                if (_currentPollMs === POLL_PREDRAFT_MS) {
                    lbl.textContent = `Waiting for draft · checking in ${_secondsLeft}s`;
                } else {
                    lbl.textContent = `Live · next sync in ${_secondsLeft}s`;
                }
            }
        }
    }, 1000);
}
```

**Change:** Uses `_currentPollMs` instead of hardcoded `POLL_INTERVAL_MS`. Shows different label for pre-draft vs live.

### Phase 2: Update `initBoard()` Polling Logic

**File: `webapp/static/js/draft_board.js`**

#### Step 2.1: Expand Polling Trigger

Replace the current Sleeper-only check (line ~876):

```javascript
// CURRENT:
if (DB.source === 'sleeper' && DB.draftId && !DB.draftComplete) {
    startPolling();
} else if (DB.draftComplete) {
    setSyncStatus('paused', 'Draft complete');
}

// NEW:
const canPoll = (DB.source === 'sleeper' && DB.draftId) || DB.source === 'espn';

if (canPoll && !DB.draftComplete) {
    if (cfg.draftStatus === 'in_progress') {
        startPolling(POLL_LIVE_MS);           // Live draft — 5s
    } else if (cfg.draftStatus === 'pre_draft') {
        setSyncStatus('paused', 'Draft not started · click Go Live to watch');
        // Don't auto-poll for pre_draft — user must click "Go Live"
    }
} else if (DB.draftComplete) {
    setSyncStatus('paused', 'Draft complete');
}
```

**Changes:**
- ESPN is now a valid polling source (no `draftId` required for ESPN)
- `in_progress` → auto-starts 5s polling
- `pre_draft` → shows status message, no auto-polling (user clicks "Go Live")

#### Step 2.2: Add "Go Live" Button for Pre-Draft

In `initBoard()`, after the polling logic, render a "Go Live" button when draft is pre-draft:

```javascript
// Show/hide the Go Live button
const goLiveBtn = document.getElementById('db-go-live-btn');
if (goLiveBtn) {
    if (canPoll && cfg.draftStatus === 'pre_draft') {
        goLiveBtn.style.display = 'inline-flex';
        goLiveBtn.onclick = () => {
            goLiveBtn.style.display = 'none';
            startPolling(POLL_PREDRAFT_MS);  // Start at 30s, auto-switch to 5s when draft begins
        };
    } else {
        goLiveBtn.style.display = 'none';
    }
}
```

### Phase 3: Add "Go Live" Button to HTML

**File: `webapp/templates/draft_board.html`**

Add a "Go Live" button next to the existing sync status indicator in the AI bar / status area:

```html
<button id="db-go-live-btn" class="db-go-live-btn" style="display:none">
    Go Live
</button>
```

**Placement:** Next to the `#db-sync-dot` / `#db-sync-label` elements in the draft board header/status area.

### Phase 4: Add "Go Live" Button Styling

**File: `webapp/static/css/draft_board.css`**

```css
.db-go-live-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    background: rgba(212, 175, 55, 0.15);
    border: 1px solid var(--gold);
    border-radius: 4px;
    color: var(--gold);
    font-size: 0.75em;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
}
.db-go-live-btn:hover {
    background: rgba(212, 175, 55, 0.3);
}
```

### Phase 5: Error Recovery — Click-to-Retry

**File: `webapp/static/js/draft_board.js`**

After 3 consecutive sync errors, polling stops. Make the sync status label clickable to retry:

```javascript
// In the catch block of syncDraft():
if (DB.syncErrorCount >= 3) {
    stopPolling();
    setSyncStatus('error', '⚠ Sync paused — click to retry');
    // Make status label clickable to restart polling
    const lbl = document.getElementById('db-sync-label');
    if (lbl) {
        lbl.style.cursor = 'pointer';
        lbl.onclick = () => {
            DB.syncErrorCount = 0;
            lbl.style.cursor = '';
            lbl.onclick = null;
            startPolling(_currentPollMs);
        };
    }
}
```

### Phase 6: Backend Optimization for Fast Polling

**File: `webapp/views.py`**

#### Step 6.1: Reduce Sleeper Sync API Calls

The current Sleeper sync makes **5 API calls** per poll. At 5s intervals, that's 60 calls/min to Sleeper per user. Optimize by skipping roster/league calls when only checking for new picks:

```python
@main.route('/draft-board/sleeper/sync')
@login_required
def draft_board_sleeper_sync():
    draft_id  = request.args.get('draft_id', '').strip()
    league_id = request.args.get('league_id', '').strip()
    last_pick = int(request.args.get('last_pick', 0))  # NEW: client sends last known pick count

    # Always fetch draft metadata + picks (2 calls)
    draft_resp = requests.get(f'https://api.sleeper.app/v1/draft/{draft_id}', timeout=8)
    draft = draft_resp.json() if draft_resp.status_code == 200 else {}
    draft_status = draft.get('status', 'in_progress')

    picks_resp = requests.get(f'https://api.sleeper.app/v1/draft/{draft_id}/picks', timeout=8)
    picks_raw = picks_resp.json() if picks_resp.status_code == 200 else []

    # If no new picks since last poll AND draft status unchanged, skip expensive roster fetch
    if len(picks_raw) == last_pick and draft_status != 'complete':
        return jsonify({
            'picks': [],
            'team_rosters': None,        # null = no change, frontend skips roster update
            'draft_status': draft_status,
            'roster_player_names': None,
            'pick_count': len(picks_raw),
        })

    # New picks detected — do full sync with roster resolution
    # ... (existing full sync logic) ...

    return jsonify({
        'picks': picks,
        'team_rosters': team_rosters,
        'draft_status': draft_status,
        'roster_player_names': roster_player_names,
        'pick_count': len(picks_raw),
    })
```

**Frontend change in `syncDraft()`:**
```javascript
// Add last_pick to Sleeper URL:
if (DB.source === 'sleeper') {
    url = `/draft-board/sleeper/sync?draft_id=...&league_id=...&last_pick=${DB.currentPickNo}`;
}

// In response processing:
// Skip roster update if server returned null (no new picks)
if (data.team_rosters) {
    // ... existing roster processing ...
}
if (data.pick_count != null) DB.lastPickCount = data.pick_count;
```

**Impact:** When no new picks have been made, the backend only makes **2 API calls** (draft metadata + picks) instead of 5. This is the common case — picks happen every 30-120 seconds, but we're polling every 5 seconds. ~80-95% of polls will take the fast path.

#### Step 6.2: ESPN Sync — Already Optimized

ESPN sync already makes a single API call with multiple views. No optimization needed. The `_espn_api_fetch()` call is efficient as-is.

### Phase 7: Cleanup & Edge Cases

**File: `webapp/static/js/draft_board.js`**

#### Step 7.1: Stop Polling on League Switch

In `resetBoard()` or wherever a league/year is switched, ensure polling is stopped:

```javascript
function resetBoard() {
    stopPolling();  // Must be first
    // ... existing reset logic ...
}
```

Also stop polling when switching seasons within a league (year arrows), since historical drafts don't need live sync.

#### Step 7.2: Stop Polling on Page Navigation

```javascript
window.addEventListener('beforeunload', stopPolling);
```

Prevents orphaned intervals if the user navigates away.

#### Step 7.3: Handle ESPN Auth Expiry During Polling

The ESPN sync endpoint returns `401` when cookies expire. Handle this in `syncDraft()`:

```javascript
if (res.status === 401 && DB.source === 'espn') {
    stopPolling();
    setSyncStatus('error', '⚠ ESPN auth expired — reconnect league');
    return;
}
```

---

## File Change Summary

| File | Changes |
|------|---------|
| `webapp/static/js/draft_board.js` | Refactor polling: `syncFromSleeper()` → `syncDraft()`, update intervals (5s live / 30s pre-draft), add ESPN URL branch, "Go Live" button logic, pre-draft → live transition, click-to-retry on error, last_pick optimization, cleanup on navigation |
| `webapp/static/css/draft_board.css` | Add `.db-go-live-btn` styling |
| `webapp/templates/draft_board.html` | Add `#db-go-live-btn` element near sync status |
| `webapp/views.py` | Sleeper sync: add `last_pick` parameter for fast-path optimization (skip roster fetch when no new picks) |

## Testing Checklist

- [ ] Sleeper live draft: connect league with active draft → board updates every 5s
- [ ] Sleeper pre-draft: connect league before draft → shows "Go Live" button → click it → polls at 30s → auto-switches to 5s when draft starts
- [ ] ESPN live draft: connect league with active draft → board updates every 5s
- [ ] ESPN pre-draft: same flow as Sleeper pre-draft
- [ ] ESPN auth expiry: cookies expire during polling → shows error, stops polling
- [ ] Draft completes during polling → stops polling, shows "Draft complete"
- [ ] 3+ sync errors → stops polling, shows clickable retry
- [ ] Switch leagues during live polling → old polling stops
- [ ] Switch year during live polling → polling stops (historical year)
- [ ] Navigate away from draft board → polling stops
- [ ] Multiple users polling same draft → server handles concurrent requests
- [ ] Railway deployment: verify sync endpoints work with production API calls
