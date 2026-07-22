# ESPN Draft Board Integration

## Overview

Add ESPN Fantasy Football as a live draft source for the Draft Board page, mirroring the existing Sleeper integration. Users will be able to connect their ESPN league, pull in draft picks and rosters, and sync live during a draft via polling.

---

## How ESPN's API Works (Context)

ESPN does not have an official public API. The community has reverse-engineered endpoints from browser network traffic. Key facts:

- **Base URL:** `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/segments/0/leagues/{LEAGUE_ID}`
- **View parameters** control what data comes back: `?view=mDraftDetail&view=mSettings&view=mTeam`
- **Public leagues:** No auth needed — just the league ID
- **Private leagues:** Require two browser cookies: `SWID` and `espn_s2`
- **Live draft:** The `mDraftDetail` view updates in real-time. The `draftDetail.picks` array grows as picks are made. `draftDetail.inProgress` and `draftDetail.drafted` indicate draft state
- **No WebSocket:** Polling is the only option (same as Sleeper). 15-30 second interval is standard
- **`espn-api` Python package:** Wraps all of this nicely, but we'll use raw `requests` calls to stay consistent with the Sleeper pattern and avoid an extra dependency

---

## Decisions

| Question | Answer |
|---|---|
| Use `espn-api` package or raw requests? | Raw requests — matches Sleeper pattern, avoids dependency, gives us full control |
| Auth approach for private leagues | User provides `SWID` + `espn_s2` cookies manually (instructions + link provided in UI) |
| Public league support | Yes — if no cookies provided, attempt unauthenticated request |
| Poll interval | 30 seconds (same as Sleeper sync) |
| Season year | Auto-detect current year, no user input needed |
| Player ID resolution | Use ESPN's own player data from `kona_player_info` view, cached like Sleeper's player map |
| Feature flag | No feature flag — ship it enabled since the Sleeper pattern is proven |

---

## Architecture: Matching the Sleeper Pattern

The Sleeper integration follows a three-endpoint pattern. ESPN will mirror it exactly:

| Step | Sleeper | ESPN |
|---|---|---|
| **Lookup** | User enters username → get user_id + leagues | User enters league_id → get league info + teams |
| **Connect** | POST league_id + user_id → full draft init data | POST league_id (+ optional cookies) → full draft init data |
| **Sync** | GET draft_id + league_id → poll for new picks | GET league_id (+ year) → poll `mDraftDetail` for new picks |

Key difference: ESPN doesn't have a "lookup by username" step. The user provides their league ID directly (found in the URL on ESPN's site). The lookup step instead validates the league ID and returns league info so the user can confirm it's the right league.

---

## Phase 1 — Backend: Helper Functions

### 1.1 `_get_espn_player_map()` (new)

Similar to `_get_sleeper_player_map()`. Fetches and caches (1-hour TTL) ESPN's player database.

- **Endpoint:** `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/players?view=kona_player_info`
- **Header:** `X-Fantasy-Filter: {"players":{"limit":2000,"filterActive":{"value":true}}}`
- **Returns:** `{espn_player_id: {name, position, team}}`
- **Cache:** Module-level `_espn_player_cache` with `_espn_player_cache_ts`, 1-hour TTL
- **ESPN team ID mapping:** Reuse the existing `_ESPN_TEAM_MAP` dict already in `views.py` (line ~380)
- **Position mapping:** ESPN uses numeric position IDs: `{1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST'}`

### 1.2 `_detect_espn_scoring(settings)` (new)

Infer scoring format from ESPN league settings.

- ESPN's `scoringSettings.scoringItems` contains a list of scoring rules
- Look for the `receivingReceptions` stat (stat ID 53): value 1.0 = PPR, 0.5 = Half PPR, 0 or absent = Standard
- **Returns:** `'ppr'` | `'half_ppr'` | `'standard'`

### 1.3 `_parse_espn_roster_slots(settings)` (new)

Convert ESPN's `rosterSettings.lineupSlotCounts` to our unified slot format.

ESPN uses numeric slot IDs:
```
0: QB, 2: RB, 4: WR, 6: TE, 23: FLEX, 17: K, 16: DST, 20: Bench, 21: IR
```

Map to: `{QB: n, RB: n, WR: n, TE: n, FLEX: n, K: n, DST: n, bench: n}`

### 1.4 `_format_espn_pick(pick, team_id_to_slot, player_map)` (new)

Normalize an ESPN pick object into the same format as `_format_sleeper_pick()`:

```python
{
    'player_id': pick['playerId'],
    'name': player_map.get(pick['playerId'], {}).get('name', f"Player {pick['playerId']}"),
    'position': player_map.get(pick['playerId'], {}).get('position', '??'),
    'nfl_team': player_map.get(pick['playerId'], {}).get('team', '??'),
    'round': pick['roundId'],
    'pick_no': pick['roundPickNumber'],
    'draft_slot': team_id_to_slot.get(pick['teamId'], pick['teamId']),
    'roster_id': pick['teamId'],
    'original_slot': team_id_to_slot.get(pick['teamId'], pick['teamId'])
}
```

### 1.5 `_espn_api_fetch(league_id, year, views, cookies=None)` (new)

Shared helper to make ESPN API calls with consistent error handling.

```python
def _espn_api_fetch(league_id, year, views, cookies=None):
    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/{league_id}"
    params = [('view', v) for v in views]
    jar = {}
    if cookies:
        jar = {'espn_s2': cookies.get('espn_s2', ''), 'SWID': cookies.get('swid', '')}
    resp = requests.get(url, params=params, cookies=jar, timeout=15)
    if resp.status_code == 401:
        return None, 'private'  # league is private, needs cookies
    if resp.status_code == 404:
        return None, 'not_found'
    resp.raise_for_status()
    return resp.json(), None
```

---

## Phase 2 — Backend: Three API Endpoints

### 2.1 `POST /draft-board/espn/lookup`

**Purpose:** Validate a league ID and return league info for confirmation.

**Request body:**
```json
{
    "league_id": "12345",
    "espn_s2": "optional...",
    "swid": "optional..."
}
```

**Logic:**
1. Build cookies dict if `espn_s2` and `swid` are provided
2. Call `_espn_api_fetch(league_id, current_year, ['mSettings', 'mTeam'], cookies)`
3. If error is `'private'`, return `{error: 'private', message: 'This league is private. Please provide your ESPN cookies (SWID and espn_s2).'}`
4. If error is `'not_found'`, return `{error: 'not_found', message: 'League not found. Check your league ID.'}`
5. Extract league name from `settings.name`
6. Extract team count from `settings.size`
7. Detect scoring format via `_detect_espn_scoring()`
8. Build team list from `teams` array: `[{id, name, abbrev, owner}]`

**Response:**
```json
{
    "league_id": "12345",
    "league_name": "My Fantasy League",
    "num_teams": 12,
    "scoring": "ppr",
    "season": 2025,
    "teams": [
        {"id": 1, "name": "Team Smith", "abbrev": "SMTH", "owner": "John Smith"},
        ...
    ]
}
```

### 2.2 `POST /draft-board/espn/connect`

**Purpose:** Full draft board initialization — same role as `/draft-board/sleeper/connect`.

**Request body:**
```json
{
    "league_id": "12345",
    "espn_s2": "optional...",
    "swid": "optional...",
    "user_team_id": 1
}
```

`user_team_id` is the ESPN team ID the user selected as "their team" from the lookup results.

**Logic:**
1. Fetch league data with views: `['mDraftDetail', 'mSettings', 'mTeam', 'mRoster']`
2. Extract league settings:
   - `settings.name` → league name
   - `settings.size` → num teams
   - `settings.draftSettings.pickOrder` → draft order
   - `_detect_espn_scoring()` → scoring format
   - `_parse_espn_roster_slots()` → roster slot configuration
   - `settings.draftSettings.type` → draft type (`'SNAKE'`, `'AUCTION'`, `'LINEAR'`)
3. Build `team_id_to_slot` mapping from draft order or team ID order
4. Build `team_names` array (0-indexed by slot) from `teams[].name`
5. Determine `user_slot` from `user_team_id` via `team_id_to_slot`
6. Extract draft data from `draftDetail`:
   - `draftDetail.drafted` → draft complete?
   - `draftDetail.inProgress` → draft live?
   - `draftDetail.picks` → existing picks
7. Determine `num_rounds`:
   - From `settings.draftSettings.rounds` if available
   - Fallback: calculate from total roster slots
8. Format existing picks via `_format_espn_pick()`
9. Build `team_rosters` from `teams[].roster.entries`:
   - Each entry has `lineupSlotId` (starter slot or bench) and `playerPoolEntry.player`
   - Map `lineupSlotId` to position labels (0=QB, 2=RB, 4=WR, 6=TE, 23=FLEX, 17=K, 16=DST, 20=Bench, 21=IR)
   - Build `{starters: [{slot, player}], bench: [], reserve: []}` per team
10. Build `roster_player_names` — flat list of all rostered player names for marking players as drafted

**Response:** Same shape as Sleeper connect response:
```json
{
    "source": "espn",
    "league_id": "12345",
    "draft_id": null,
    "league_name": "My Fantasy League",
    "num_teams": 12,
    "num_rounds": 16,
    "user_slot": 3,
    "team_names": ["Team A", "Team B", ...],
    "scoring_format": "ppr",
    "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "bench": 6},
    "starter_slot_labels": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DST"],
    "existing_picks": [...],
    "team_rosters": [...],
    "roster_player_names": [...],
    "draft_status": "in_progress",
    "league_type": "redraft"
}
```

### 2.3 `GET /draft-board/espn/sync`

**Purpose:** Poll for live draft updates — same role as `/draft-board/sleeper/sync`.

**Query params:** `league_id`, `espn_s2` (optional), `swid` (optional)

**Logic:**
1. Fetch with views: `['mDraftDetail', 'mTeam', 'mRoster', 'mSettings']`
2. Get `draftDetail.picks` → format all picks via `_format_espn_pick()`
3. Determine `draft_status` from `draftDetail.inProgress` / `draftDetail.drafted`
4. Rebuild `team_rosters` from current roster data
5. Rebuild `roster_player_names`

**Response:** Same shape as Sleeper sync:
```json
{
    "picks": [...],
    "team_rosters": [...],
    "draft_status": "in_progress" | "complete" | "pre_draft",
    "roster_player_names": [...]
}
```

---

## Phase 3 — Database Changes

### 3.1 `SavedLeague` model updates

Add ESPN-specific columns (or reuse generically):
```python
espn_s2 = db.Column(db.Text, nullable=True)      # ESPN S2 cookie (encrypted at rest ideally)
espn_swid = db.Column(db.String(50), nullable=True)  # ESPN SWID cookie
```

The `source` field already allows `'espn'`. The `league_id` field is reusable. No new unique constraints needed.

### 3.2 Migration

Simple `ALTER TABLE` to add the two new nullable columns. Use Flask-Migrate or raw SQL:
```sql
ALTER TABLE saved_league ADD COLUMN espn_s2 TEXT;
ALTER TABLE saved_league ADD COLUMN espn_swid VARCHAR(50);
```

### 3.3 Security note

The `espn_s2` cookie is a session token. We should:
- Store it only in the DB (never log it)
- Transmit it over HTTPS only (already the case in production)
- Clear it if the user disconnects the league
- Consider encrypting at rest (stretch goal — not blocking for MVP)

---

## Phase 4 — Frontend: HTML Template

### 4.1 Enable the ESPN tab

In `draft_board.html`, remove the `disabled` attribute and `"soon"` label from the ESPN tab button.

### 4.2 Add `#setup-espn` panel

Add a new setup panel below `#setup-sleeper`, shown when the ESPN tab is active:

```html
<div id="setup-espn" class="db-setup-panel" style="display:none;">
    <!-- Step 1: League ID input -->
    <div class="db-field-group">
        <label>ESPN League ID</label>
        <input type="text" id="espn-league-id" placeholder="e.g. 12345678">
        <small class="db-help-text">
            Find this in your league URL: fantasy.espn.com/football/league?leagueId=<b>12345678</b>
        </small>
    </div>

    <!-- Step 2: Optional cookies for private leagues -->
    <details id="espn-private-toggle">
        <summary>Private league? Add ESPN cookies</summary>
        <div class="db-field-group">
            <label>SWID</label>
            <input type="text" id="espn-swid" placeholder="{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}">
        </div>
        <div class="db-field-group">
            <label>espn_s2</label>
            <textarea id="espn-s2" rows="3" placeholder="Paste your espn_s2 cookie here..."></textarea>
        </div>
        <small class="db-help-text">
            To find these: Log into ESPN in your browser → Open Developer Tools (F12) →
            Application tab → Cookies → fantasy.espn.com → Copy SWID and espn_s2 values.
        </small>
    </details>

    <!-- Step 3: Lookup button -->
    <button id="espn-lookup-btn" class="db-btn db-btn-primary" onclick="espnLookup()">
        Find League
    </button>

    <!-- Step 4: League confirmation (hidden until lookup succeeds) -->
    <div id="espn-league-info" style="display:none;">
        <div class="db-league-confirm">
            <h4 id="espn-league-name"></h4>
            <p id="espn-league-meta"></p>
        </div>
        <div class="db-field-group">
            <label>Which team is yours?</label>
            <select id="espn-team-select"></select>
        </div>
        <button id="espn-connect-btn" class="db-btn db-btn-primary" onclick="espnConnect()">
            Connect to League
        </button>
    </div>

    <p id="espn-error" class="db-error" style="display:none;"></p>
</div>
```

### 4.3 Tab switching logic

Update the existing tab click handler to show/hide `#setup-espn` alongside `#setup-sleeper` and `#setup-manual`.

---

## Phase 5 — Frontend: JavaScript

### 5.1 `espnLookup()` (new)

```javascript
async function espnLookup() {
    const leagueId = document.getElementById('espn-league-id').value.trim();
    if (!leagueId) return;

    const body = { league_id: leagueId };
    const swid = document.getElementById('espn-swid').value.trim();
    const s2 = document.getElementById('espn-s2').value.trim();
    if (swid) body.swid = swid;
    if (s2) body.espn_s2 = s2;

    // POST to /draft-board/espn/lookup
    // On success: populate #espn-league-name, #espn-league-meta, #espn-team-select
    // On 'private' error: open the cookies details element and show message
    // On 'not_found' error: show error message
}
```

### 5.2 `espnConnect()` (new)

```javascript
async function espnConnect() {
    const leagueId = document.getElementById('espn-league-id').value.trim();
    const teamId = document.getElementById('espn-team-select').value;

    const body = { league_id: leagueId, user_team_id: parseInt(teamId) };
    // Include cookies if provided
    const swid = document.getElementById('espn-swid').value.trim();
    const s2 = document.getElementById('espn-s2').value.trim();
    if (swid) body.swid = swid;
    if (s2) body.espn_s2 = s2;

    // POST to /draft-board/espn/connect
    // On success: call initBoard() with the returned data (same as sleeperConnect)
    // Save league via /draft-board/leagues/save (fire and forget)
    // Store cookies in DB.espnCookies for sync polling
}
```

### 5.3 `syncFromEspn()` (new)

```javascript
async function syncFromEspn() {
    let url = `/draft-board/espn/sync?league_id=${DB.leagueId}`;
    if (DB.espnCookies) {
        url += `&espn_s2=${encodeURIComponent(DB.espnCookies.espn_s2)}`;
        url += `&swid=${encodeURIComponent(DB.espnCookies.swid)}`;
    }

    // GET the sync endpoint
    // Same post-processing as syncFromSleeper():
    //   - Update DB.fullRosters
    //   - Rebuild DB.drafted Set from roster_player_names
    //   - Re-render Your Team, Other Teams, Available Players
    //   - Apply new picks via applyPick()
    //   - Detect draft completion, stop polling
}
```

### 5.4 Update `startPolling()` / sync dispatch

The existing polling logic dispatches to `syncFromSleeper()` when `DB.source === 'sleeper'`. Add an `else if (DB.source === 'espn')` branch that calls `syncFromEspn()`.

### 5.5 ESPN cookie state

Add `DB.espnCookies = null` to the state object. Set it during `espnConnect()` if cookies were provided, so `syncFromEspn()` can include them in requests.

---

## Phase 6 — Session Persistence & Saved Leagues

### 6.1 Saving ESPN leagues

The existing `/draft-board/leagues/save` endpoint accepts `source`, `league_id`, `league_name`, etc. Extend it to also accept and store `espn_s2` and `espn_swid` for ESPN leagues.

### 6.2 Loading saved ESPN leagues

The existing `/draft-board/leagues/list` endpoint returns saved leagues. When loading an ESPN league:
- Include `espn_s2` and `espn_swid` in the response so the frontend can reconnect without re-entering cookies
- The `espnConnect()` function should work with saved cookie values

### 6.3 Draft board session state

The existing `DraftBoardSession` model already supports `source='espn'`. The `settings` JSON column can store ESPN-specific data (cookies, team_id_to_slot mapping, etc.).

---

## Phase 7 — Testing & Edge Cases

### 7.1 Key test scenarios

| Scenario | Expected behavior |
|---|---|
| Valid public league ID | Lookup succeeds, no cookies needed |
| Valid private league ID without cookies | Returns `'private'` error with instructions |
| Valid private league ID with cookies | Lookup succeeds |
| Invalid league ID | Returns `'not_found'` error |
| Draft not yet started | Connect succeeds with empty picks, `draft_status: 'pre_draft'` |
| Draft in progress | Connect returns existing picks, sync polls for new ones |
| Draft complete | Connect returns all picks, sync shows `draft_status: 'complete'` |
| Expired cookies | Sync returns auth error, UI prompts to re-enter cookies |
| Auction draft | Pick format includes `bidAmount`, slot assignment differs (all picks go to same team differently) |
| Keeper/dynasty league | Pre-draft roster data shows keepers; picks array only has non-keeper selections |
| Traded picks | `teamId` on the pick reflects the team that actually made the pick (ESPN handles this natively) |

### 7.2 Known limitations

- **Auction drafts:** The board is designed for snake drafts. Auction draft support would require a different UI layout (stretch goal, not in scope)
- **Cookie expiration:** ESPN cookies expire periodically. If sync fails with 401, show a message asking the user to refresh their cookies
- **No username lookup:** Unlike Sleeper, we can't list all of a user's leagues. They need to know their league ID
- **ESPN API instability:** This is an unofficial API. Endpoints could change without notice. We should handle unexpected response shapes gracefully

---

## Implementation Order

| Step | Work | Files Modified |
|---|---|---|
| 1 | Add `espn_s2` and `espn_swid` columns to `SavedLeague` | `__init__.py`, migration |
| 2 | Write helper functions (`_get_espn_player_map`, `_detect_espn_scoring`, `_parse_espn_roster_slots`, `_format_espn_pick`, `_espn_api_fetch`) | `views.py` |
| 3 | Write `/draft-board/espn/lookup` endpoint | `views.py` |
| 4 | Write `/draft-board/espn/connect` endpoint | `views.py` |
| 5 | Write `/draft-board/espn/sync` endpoint | `views.py` |
| 6 | Update `/draft-board/leagues/save` and `/draft-board/leagues/list` for ESPN fields | `views.py` |
| 7 | Enable ESPN tab + add `#setup-espn` panel in template | `draft_board.html` |
| 8 | Write `espnLookup()`, `espnConnect()`, `syncFromEspn()` in JS | `draft_board.js` |
| 9 | Update polling dispatch + add `DB.espnCookies` state | `draft_board.js` |
| 10 | Update tab switching logic | `draft_board.js` |
| 11 | End-to-end testing with a real ESPN league | Manual QA |

---

## ESPN API Reference (Quick Cheat Sheet)

**Base URL:**
```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/segments/0/leagues/{LEAGUE_ID}
```

**Views:**
| View | Data |
|---|---|
| `mSettings` | League name, scoring rules, roster slots, draft settings |
| `mTeam` | Team names, owners, records |
| `mRoster` | Current rosters with players |
| `mDraftDetail` | Draft picks, draft status (inProgress, drafted) |

**Auth (private leagues only):**
```
Cookies: espn_s2=<token>; SWID=<{guid}>
```

**Player data:**
```
GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/players?view=kona_player_info
Header: X-Fantasy-Filter: {"players":{"limit":2000,"filterActive":{"value":true}}}
```

**ESPN Position IDs:** `1=QB, 2=RB, 3=WR, 4=TE, 5=K, 16=DST`

**ESPN Roster Slot IDs:** `0=QB, 2=RB, 4=WR, 6=TE, 23=FLEX, 17=K, 16=DST, 20=Bench, 21=IR`

**ESPN Team IDs:** Already mapped in `_ESPN_TEAM_MAP` in `views.py`
