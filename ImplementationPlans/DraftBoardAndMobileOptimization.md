# Draft Board Page & Mobile Optimization

## Overview

Two major initiatives:

1. **Site-wide mobile optimization** — Audit every page and fix layout, typography, tables, navigation, and interactive elements to be fully usable on phone screens
2. **Draft Board page** — A live draft tracker (separate from `/mockdraft`) where users can cross off players as they are drafted in real leagues, see all teams' rosters build in real time, and receive AI-driven suggestions on who to target next. Supports Sleeper league linking (Phase 1), ESPN/Yahoo linking (Phase 3), and a fully manual mode

---

## Decisions (Locked In)

| Question | Answer |
|---|---|
| Draft Board vs. Mock Draft | Separate standalone page at `/draft-board` — Mock Draft is unchanged |
| Sleeper sync style | Auto-update in real time (poll every ~5–10 seconds) |
| Session persistence | Yes — save state to DB; on return, resume and apply any new picks made since last save |
| AI suggestion depth | Full: positional need + best available + predict what other teams will grab before your next pick |
| Manual mode team names | Auto-fill as Team 1, Team 2, etc. — user can rename any team inline |
| ESPN/Yahoo | Visible in UI as "Coming Soon" tabs, disabled until Phase 3 |

---

## Phase 1 — Site-Wide Mobile Optimization

### Current State

- Single media query at `max-width: 600px` in `styles.css`
- Rankings, player profile, and mock draft have large tables and dense layouts that overflow on mobile
- Navigation is a horizontal flex row that wraps awkwardly on small screens
- Mock draft lobby grid and board table are not mobile-friendly
- No touch-specific interactions

### Goals

- Every page is usable and readable on a 375px–430px viewport (iPhone SE through iPhone 15 Pro)
- No horizontal scroll except data tables (where intentional and contained)
- Navigation collapses into a hamburger menu on mobile
- All tap targets are at least 44×44px
- Font sizes are legible without zooming

### Scope by Page

#### Global (`styles.css` + nav template)
- Add hamburger menu toggle for `<nav>` on screens under 768px — JS toggles a `.nav-open` class, CSS handles show/hide
- Expand breakpoint system from single `600px` to two tiers: `768px` (tablet) and `480px` (phone)
- Scale down padding/margin on `main`, `.container`, section wrappers at each breakpoint
- Fix footer: stack links/columns vertically on mobile

#### Rankings Page (`rankings.html`)
- Wrap table in `overflow-x: auto` container
- Sticky player name column: `position: sticky; left: 0; background: var(--black)` so it doesn't scroll away
- Filter bar: switch from inline flex row to a vertical stack on mobile
- On phone: hide lower-priority columns (ADP source, model rank) by default; add a "show more columns" toggle

#### Player Profile Page (`player_profile.html`)
- Stats chart (Chart.js): canvas width 100%, font size reduction on mobile, simplified legend
- Season history table: horizontal scroll within a constrained container
- Header block (age, height, weight, position, team): switch from single-line inline to 2-column CSS grid

#### Mock Draft Page (`mockdraft.html`, `mockdraft.css`)
- Lobby: all setting inputs stack vertically on mobile
- Board table: pin the round/pick column with `position: sticky; left: 0`
- Player card pick confirmation: render as a full-screen bottom sheet on mobile instead of inline

#### Player Comps Page (`player_comps.html`)
- Side-by-side comparison: stack vertically on mobile (player A above player B)
- Chart: single visible metric at a time on phone with a metric toggle selector

#### My Drafts / View Draft Pages
- Draft result tables: same sticky-column + horizontal scroll pattern

#### Login / Register Pages
- Inputs and button already simple; ensure `width: 100%` on fields and button on mobile

---

## Phase 2 — Draft Board Page (Core Feature)

### Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/draft-board` | Renders `draft_board.html` |
| `POST` | `/draft-board/sleeper/lookup` | Takes Sleeper username → returns leagues list |
| `POST` | `/draft-board/sleeper/connect` | Takes league ID → fetches draft ID, settings, existing picks |
| `GET` | `/draft-board/sleeper/picks?draft_id=<x>` | Returns all picks from Sleeper API (used by polling) |
| `POST` | `/draft-board/save` | Saves or updates current board state to DB |
| `GET` | `/draft-board/load` | Returns saved board state for the current user |
| `POST` | `/draft-board/ai-suggest` | Takes roster + available players + picks_until_next → returns AI suggestions |

### Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  DRAFT BOARD                            [Sleeper][Manual][ESPN*][Yahoo*]
├──────────────┬──────────────────────────────────┬───────────────┤
│              │                                  │               │
│  AVAILABLE   │        DRAFT BOARD GRID          │  YOUR TEAM    │
│  PLAYERS     │  (all teams × all rounds)        │  ROSTER       │
│              │                                  │               │
│  [search]    │  Rd1  T1   T2  [You]  T4  T5...  │  QB: ___      │
│  [pos filter]│  Rd2  T5  T4  [You]  T2   T1...  │  RB1: ___     │
│              │  ...                             │  RB2: ___     │
│  1. Player A │                                  │  WR1: ___     │
│  2. Player B │                                  │  ...          │
│  ~~Drafted~~ │                                  │               │
│  3. Player C │                                  │               │
│  ...         │                                  │               │
├──────────────┴──────────────────────────────────┴───────────────┤
│  AI SUGGESTIONS                                                  │
│  Need: RB > WR > TE  |  Targets: Player X, Player Y, Player Z   │
│  Watch: Player Q likely gone in next 3 picks (Teams 4 & 7 need RB)│
├─────────────────────────────────────────────────────────────────┤
│  OTHER TEAMS  [Team 1 ▾] [Team 2 ▾] [Team 3 ▾] ...             │
│  (collapsible roster per team)                                   │
└─────────────────────────────────────────────────────────────────┘
* = Coming Soon (disabled)
```

### Section 1 — Setup Panel

Shown on first load or when no saved session exists. Tabbed interface:

**Tab: Sleeper**
1. Input: Sleeper username
2. Button: "Find My Leagues" → POST to `/draft-board/sleeper/lookup`
3. Dropdown: select league from returned list
4. Button: "Connect" → POST to `/draft-board/sleeper/connect`
5. Auto-fills: num teams, scoring format, roster slots, draft order
6. Board populates with any picks already made

**Tab: Manual**
1. Select: number of teams (8 / 10 / 12 / 14 / 16)
2. Select: scoring format (PPR / Half PPR / Standard)
3. Select: draft type (Snake / Auction — Auction is stretch goal)
4. Number: which pick slot is yours (1–N)
5. Number: roster spots per position (pre-filled with standard 1QB/2RB/2WR/1TE/1FLEX/1K/1DST + bench)
6. Team names: auto-generated ("Team 1", "Team 2", …) with inline edit on each
7. Button: "Start Draft Board"

**Tab: ESPN** — Disabled, tooltip "Coming Soon"

**Tab: Yahoo** — Disabled, tooltip "Coming Soon"

### Section 2 — Draft Board Grid

Full league grid — all teams (columns) × all rounds (rows):

- Column headers: team names (editable inline in manual mode)
- User's column: gold left-border accent, slightly lighter background
- Each cell shows: `[Position Badge] Player Name  NFL Team`
- Position badges are color-coded: QB=red, RB=green, WR=blue, TE=orange, K/DST=gray
- Snake order: even rounds reverse the column order visually (or use pick-number ordering)
- Empty upcoming cells: subtle dashed border, clickable to open player assignment
- Clicking a cell for another team also opens assignment (to mark what they drafted)

### Section 3 — Available Players Panel

- Data source: same `/mockdraft/players?scoring=<format>` endpoint already used by mock draft
- Displayed as a scrollable ranked list
- Search box: filters by name in real time (client-side)
- Position filter tabs: ALL | QB | RB | WR | TE | K | DST
- Each row: rank, player name, position badge, NFL team, model score
- Drafted players: `text-decoration: line-through`, grayed out, still visible (can un-cross if mistake)
- Clicking an available player in manual mode opens a confirmation to assign to the current or a selected pick slot
- In Sleeper mode, crossing off is automatic when sync picks up the pick

### Section 4 — Your Team Roster Panel

- Position slots listed (QB, RB1, RB2, WR1, WR2, TE, FLEX, Bench…)
- Filled slots show player name + position badge
- Empty slots show "---" placeholder
- Dynamically updates as picks are made or synced

### Section 5 — Other Teams' Rosters Panel

- Horizontal tab bar: one tab per opposing team
- Each tab shows that team's picks grouped by position (same layout as Your Team panel)
- Helps identify positional runs and other teams' needs
- In Sleeper mode, populated from synced pick data

### Section 6 — AI Suggestion Panel

Sticky bar at the bottom of the main content area. Updates after every pick (local or synced).

**Backend logic (`/draft-board/ai-suggest`):**

Input payload:
```json
{
  "user_roster": [{"name": "...", "position": "RB"}, ...],
  "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "bench": 6},
  "available_players": [{"name": "...", "position": "...", "rank": 12, "adp": 14}, ...],
  "other_teams": [{"picks": [...]}, ...],
  "pick_number": 23,
  "user_next_pick": 26,
  "total_picks": 144
}
```

Logic:
1. **Positional need** — compare filled slots vs. required slots; rank positions by urgency (empty starter > thin at starter > no bench depth)
2. **Top targets at needed positions** — filter available players to top position, return top 3 by model rank
3. **Best available** — top 3 regardless of position
4. **Danger players** — for each player in your top targets, estimate P(taken before your pick) based on: how many teams pick before you × how many of those teams need that position × player's ADP vs. current pick number
5. **Alert** — if any top target has >60% chance of being gone, surface as "Take now or lose them"

Output displayed:
- Positional need bar: QB | RB | WR | TE with urgency color (red/yellow/green)
- Top 3 targets (position-need-weighted)
- Top 3 best available
- 1–2 "Watch" alerts for players likely to be gone soon

---

## Phase 3 — Sleeper Live Auto-Sync

Build on top of Phase 2's Sleeper connect flow:

- After board is initialized from Sleeper, start `setInterval` polling every 8 seconds
- Each poll: `GET /draft-board/sleeper/picks?draft_id=<x>` → backend re-fetches from Sleeper API and returns full picks array
- Client diffs against current `DraftBoard.drafted` set by pick index or player ID
- For each new pick found:
  - Animate the player card sliding into the appropriate board cell
  - Cross off the player in the available list
  - Update the relevant team's roster panel
  - Re-run AI suggestions
  - Auto-save state to DB via debounced `POST /draft-board/save`
- Sync indicator: small "● Live" badge in the header; on error, shows "⚠ Sync paused — retrying"
- Manual "Sync Now" button as fallback
- Stop polling when all roster slots are filled (draft complete)

### Session Resume Logic

On page load, `GET /draft-board/load` returns any existing `DraftBoardSession` for the user:
- If found and source is `sleeper`: re-fetch current picks from Sleeper, diff against saved state, apply any new picks, then start live polling
- If found and source is `manual`: restore board exactly as saved
- If not found: show setup panel

---

## Phase 4 — ESPN & Yahoo Integration

> Both require OAuth 2.0 — significantly more complex than Sleeper's public API.

### ESPN
- User provides ESPN S2 cookie + SWID (found in browser cookies when logged into ESPN)
- Use `espn_api` Python library (`pip install espn-api`)
- `League(year, league_id, espn_s2, swid)` returns draft picks, team rosters, settings
- Same board population logic as Sleeper once authenticated

### Yahoo
- User authenticates via Yahoo OAuth 2.0 (redirect flow)
- Requires a registered Yahoo Developer app (client ID + secret stored in env vars)
- Use `yahoo_fantasy_api` Python library
- Draft picks pulled from the game/league endpoint

### Implementation Notes
- Both gated behind `FEATURE_ESPN_ENABLED` and `FEATURE_YAHOO_ENABLED` env var flags
- Front-end tabs un-disable when flag is true
- Backend routes return 501 if flag is false

---

## Database Model

```python
class DraftBoardSession(db.Model):
    __tablename__ = 'draft_board_session'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source      = db.Column(db.String(20))      # 'sleeper' | 'manual' | 'espn' | 'yahoo'
    league_id   = db.Column(db.String(100))     # external league ID
    draft_id    = db.Column(db.String(100))     # external draft ID (Sleeper draft_id)
    settings    = db.Column(db.JSON)            # { numTeams, scoringFormat, rosterSlots, teamNames, userSlot }
    state       = db.Column(db.JSON)            # { board[][], drafted[], userRoster[] }
    last_pick   = db.Column(db.Integer)         # total picks recorded at last save (for change detection)
```

One session per user (upsert on save — not one per draft). If user starts a new draft, old session is overwritten.

---

## Frontend State Object (`draft_board.js`)

```javascript
const DraftBoard = {
  // Setup
  source: 'sleeper',        // 'sleeper' | 'manual' | 'espn' | 'yahoo'
  leagueId: null,
  draftId: null,
  numTeams: 12,
  numRounds: 15,
  userSlot: 1,              // 1-indexed pick slot in round 1
  teamNames: [],            // ['Team 1', 'Team 2', ...]
  scoringFormat: 'ppr',
  rosterSlots: {},          // { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DST: 1, bench: 6 }

  // Live state
  players: [],              // ranked player objects from /mockdraft/players
  playerIndex: {},          // player_id → index in players[] for O(1) lookup
  drafted: new Set(),       // set of player IDs that have been picked
  board: [],                // board[round][teamIndex] = pick object | null
  userRoster: [],           // picks assigned to user's team
  otherRosters: {},         // teamIndex → [picks]
  currentPickNumber: 0,     // overall pick count (used to determine whose turn it is)

  // Sync
  syncInterval: null,
  lastSyncAt: null,
  syncErrorCount: 0,
};
```

Key functions:
- `initBoard(settings)` — builds grid DOM, fetches player list
- `applyPick(pick)` — places pick in board, crosses off player, updates rosters, triggers AI refresh
- `diffAndApplyPicks(newPicksArray)` — compares Sleeper response against `drafted`, calls `applyPick` for new ones
- `startPolling()` / `stopPolling()` — manages `syncInterval`
- `saveState()` — debounced POST to `/draft-board/save`
- `updateAISuggestions()` — POST to `/draft-board/ai-suggest`, renders result panel
- `crossOffPlayer(playerId, manual)` — handles manual cross-off with undo support
- `renderBoard()` — full re-render of the grid (used on load/resume)
- `renderAvailablePlayers()` — re-renders the available list with current filter/search state

---

## Backend Helpers (`views.py`)

```python
def _fetch_sleeper_user(username):
    # GET https://api.sleeper.app/v1/user/{username}
    # Returns { user_id, display_name, avatar }

def _fetch_sleeper_leagues(user_id, season):
    # GET https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{season}
    # Returns list of { league_id, name, settings, scoring_settings, roster_positions }

def _fetch_sleeper_draft_id(league_id):
    # GET https://api.sleeper.app/v1/league/{league_id}/drafts
    # Returns first draft object with { draft_id, status, settings }

def _fetch_sleeper_picks(draft_id):
    # GET https://api.sleeper.app/v1/draft/{draft_id}/picks
    # Returns list of { pick_no, player_id, picked_by, metadata: { name, position, team } }

def _build_ai_suggestion(payload):
    # Compute positional need scores
    # Filter available players to top positions
    # Estimate P(gone before next pick) for top targets
    # Return { needs, targets, best_available, alerts }
```

---

## File Checklist

### New Files
- `webapp/templates/draft_board.html`
- `webapp/static/js/draft_board.js`
- `webapp/static/css/draft_board.css`

### Modified Files
- `webapp/views.py` — new routes, Sleeper helpers, AI suggestion logic, DraftBoardSession CRUD
- `webapp/__init__.py` — add `DraftBoardSession` model, add nav link
- `webapp/static/css/styles.css` — mobile breakpoints overhaul, hamburger nav
- All templates in `webapp/templates/` — mobile layout fixes (rankings, profile, mockdraft, comps, auth)
- `webapp/static/css/mockdraft.css` — mobile fixes

---

## Implementation Order

| Step | Work |
|---|---|
| 1 | Mobile audit — read all templates and styles.css, document specific breakages |
| 2 | Fix global styles — hamburger nav, breakpoint system, container padding |
| 3 | Fix page-by-page — rankings → player profile → mock draft → player comps → auth |
| 4 | Draft Board skeleton — route, template shell, setup panel (Manual mode fully functional) |
| 5 | DB model — `DraftBoardSession` migration, save/load routes |
| 6 | Sleeper link flow — lookup, connect, board population from existing picks |
| 7 | Board UI — grid table, available players panel, your team panel, other teams panel |
| 8 | AI suggestions — backend logic + frontend render panel |
| 9 | Live sync — polling, diff logic, sync indicator, auto-save on new picks |
| 10 | Session resume — load saved state on return, apply delta from Sleeper |
| 11 | ESPN/Yahoo stubs — disabled tabs, Coming Soon tooltips, feature flag backend stubs |
| 12 | Draft Board mobile layout — bottom drawer for available players, collapsible team cards, floating AI card |
