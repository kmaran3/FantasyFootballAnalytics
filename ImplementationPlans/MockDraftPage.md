# Mock Draft Page — Implementation Plan

## Overview

A full-featured mock draft simulator supporting snake and auction formats. Pulls player rankings from the existing DB tables (Full_PPR, Half_PPR, Non_PPR), simulates CPU team behavior with probabilistic picks, and allows the user to save and email completed drafts.

---

## 1. Settings & Configuration

Before a draft starts, the user configures all settings on a pre-draft lobby screen.

### Shared Settings (Snake + Auction)
| Setting | Options |
|---|---|
| Scoring Format | PPR / Half PPR / Standard |
| Number of Teams | 8, 10, 12, 14 |
| Draft Type | Snake / Auction |
| Your Draft Position | Pick slot (1–N) or Randomize |
| Roster Slots | QBs, RBs, WRs, TEs, Flex (RB/WR/TE), Bench |
| Timer Per Pick | None, 15s, 30s, 60s, 90s |

### Snake-Only Settings
- Timer behavior: auto-pick best available when timer expires

### Auction-Only Settings
| Setting | Options |
|---|---|
| Starting Budget | Configurable (default $200) |
| Bid Time Limit | Max seconds after last bid before player is awarded (e.g., 5s, 10s, 15s, 30s) |
| Minimum Bid | $1 (fixed) |

---

## 2. Data Layer

### Player Pool
- Pulled from the matching DB table based on scoring format:
  - PPR → `Full_PPR`
  - Half PPR → `Half_PPR`
  - Standard → `Non_PPR`
- Columns used: `Rank`, `Name`, `Team`, `Position`, `Bye Week`, `ESPN ADP`
- K and DEF excluded from the player pool

### Roster Validation
- Total rounds = QBs + RBs + WRs + TEs + Flex + Bench (auto-calculated)
- CPU teams must fill all roster slots by draft end — enforced via position-need logic during CPU pick simulation

### New DB Model: `MockDraft`
```python
class MockDraft(db.Model):
    id          # Primary key
    user_id     # FK to User
    created_at  # Timestamp
    draft_type  # "snake" or "auction"
    scoring     # "ppr", "half_ppr", "standard"
    settings    # JSON: num_teams, roster slots, timer, budget, etc.
    board       # JSON: full draft board (all picks, all teams)
    user_team   # JSON: just the user's picks
```

---

## 3. Draft Board Layout

### Snake Draft Board
- Full grid: rows = rounds, columns = teams
- User's column highlighted (Ocean Depths accent color)
- Each cell shows: player name, position badge, round/pick number
- As picks are made, cells fill in real time
- "Your Team" panel on the right sidebar updates live, grouped by position
- Available players list on the left, sorted by rank, filterable by position

### Auction Draft Board
- Left: Nomination queue (current nominating team highlighted)
- Center: Active bidding panel — player card, current high bid, high bidder, countdown timer
- Right: All teams' rosters + remaining budgets
- Bottom: Available players list sorted by rank

---

## 4. CPU Pick Logic

### Snake Draft — Probabilistic Pick Selection
- For each CPU pick, calculate selection probability for each available player using a **distance-weighted window**:
  - The top-ranked available player has the highest probability
  - Probability decreases with each rank below the top
  - Formula: `P(player_i) ∝ 1 / (1 + distance^1.5)` where `distance` is how far below rank 1 the player is
  - Hard cap: CPU will not pick a player ranked more than `(round * 2.5)` spots below the best available — prevents extreme reaches
- **Position needs enforcement**: In later rounds, probability is weighted toward unfilled roster slots. A CPU team with no QB drafted will significantly up-weight QBs.
- **Random seed per draft**: Randomized differently every run

### Auction Draft — CPU Bidding Behavior
- Each CPU team has a **player valuation** derived from rank:
  - `Base Value = (total_players - rank + 1) / total_players * budget * position_weight`
  - Position weights vary slightly per team (randomized per draft to simulate team tendencies)
- CPU teams bid if: `current_bid < their_valuation AND remaining_budget - bid >= remaining_roster_spots` (must keep $1/spot minimum)
- CPU teams won't over-extend: they track their budget vs. remaining roster needs
- After a bid, other CPU teams re-evaluate and may counter within the bid time limit
- CPU nomination: teams rotate in order; CPU picks highest-ranked undrafted player they most need

---

## 5. Snake Draft Flow

1. User configures settings → clicks "Start Draft"
2. Draft order generated (user slot placed at chosen or random position, rest randomized)
3. Round 1 begins — picks proceed in order (1 → N)
4. Odd rounds: 1 → N, Even rounds: N → 1 (standard snake)
5. For each CPU pick:
   - Brief delay (0.8–1.5s randomized) to simulate thinking
   - Probabilistic pick selected using logic above
   - Cell fills in on the board
6. For user pick:
   - Timer starts (if configured)
   - User clicks a player from the available list
   - If timer expires → auto-pick best available by rank
7. Repeat until all rounds complete
8. Post-draft screen: full board displayed, save/email options appear

---

## 6. Auction Draft Flow

1. User configures settings → clicks "Start Draft"
2. Nomination order determined (user slot placed at chosen or random position)
3. Round begins — nominating team (rotating) selects a player:
   - CPU: auto-nominates highest-ranked undrafted player they most need
   - User: picks from available list
4. Bidding opens:
   - Starting bid: $1
   - All teams can bid at any time (no fixed order)
   - Timer resets after each new bid
   - CPU teams bid based on valuation logic
   - User can type or click +$1, +$5, +$10 bid buttons or custom amount
5. Timer expires → player awarded to highest bidder
6. If user is awarded player: roster panel updates
7. Next team nominates → repeat until all teams have filled all roster slots
8. Post-draft screen: full board + budget summaries, save/email options

---

## 7. "Your Team" Panel

- Right sidebar, always visible during draft
- Grouped by position slot: QB, RB, RB, WR, WR, TE, FLEX, BN, BN...
- Empty slots shown as grayed-out placeholders
- Filled slots show: player name, NFL team, position badge
- Auction variant also shows: amount paid per player and remaining budget

---

## 8. Save & Email

### Save Options (post-draft only)
- **Save Full Board**: Entire draft grid for all teams
- **Save My Team Only**: Just the user's picks
- Both saved to `MockDraft` table in DB linked to the user account
- Accessible from a "My Drafts" section (can be a simple list view)

### Email Options (post-draft only)
- **Email Full Board**: HTML-formatted draft grid sent to login email
- **Email My Team Only**: Cleaner email with just the user's roster
- Uses Flask-Mail (or smtplib) — email formatted with Ocean Depths styling
- Subject line: `"Darkhorse Mock Draft — [Date] — [Scoring Format] [Draft Type]"`

---

## 9. Files to Create / Modify

### New Files
| File | Purpose |
|---|---|
| `webapp/templates/mockdraft.html` | Complete rewrite of existing minimal template |
| `webapp/static/css/mockdraft.css` | Draft-specific styles (grid, bidding panel, timers) |
| `webapp/static/js/mockdraft.js` | All draft simulation logic (snake + auction) |

### Modified Files
| File | Change |
|---|---|
| `webapp/views.py` | Add routes: `/mockdraft/start`, `/mockdraft/save`, `/mockdraft/email`, `/my_drafts` |
| `webapp/__init__.py` | Add `MockDraft` DB model |
| `webapp/templates/base.html` | Add "My Drafts" nav link (optional) |

---

## 10. New Routes

| Route | Method | Purpose |
|---|---|---|
| `/mockdraft` | GET | Render the pre-draft lobby/settings screen |
| `/mockdraft/players` | GET | Return player pool JSON for given scoring format |
| `/mockdraft/save` | POST | Save completed draft to DB |
| `/mockdraft/email` | POST | Send draft results to user's email |
| `/my_drafts` | GET | List all saved drafts for the user |
| `/my_drafts/<id>` | GET | View a specific saved draft |

---

## 11. Implementation Order

1. **DB model** — Add `MockDraft` to `__init__.py`, run migration
2. **Player data route** — `/mockdraft/players` endpoint returning ranked pool as JSON
3. **Pre-draft lobby UI** — Settings form in `mockdraft.html`
4. **Draft board UI** — Grid layout + your team sidebar (static/skeleton first)
5. **Snake draft logic** — CPU probabilistic picks, timer, auto-pick in `mockdraft.js`
6. **Auction draft logic** — Bidding engine, countdown timer, nomination rotation
7. **Post-draft screen** — Summary view, save/email buttons
8. **Save route** — `/mockdraft/save` + My Drafts list view
9. **Email route** — `/mockdraft/email` with HTML email template
10. **Polish** — Ocean Depths styling, responsive layout, edge cases (budget exhausted, roster full, etc.)

---

## 12. Key Edge Cases to Handle

- CPU team runs out of budget before roster is full (auction) — must always reserve $1/remaining slot
- User's draft slot lands on an out-of-bounds pick number when teams change
- All players at a position are drafted before a team fills that slot
- Draft interrupted mid-session (session storage to preserve state)
- Timer fires during a user input action (graceful auto-pick without disrupting UI)
- Flex slot eligibility: only RB/WR/TE eligible
- Auction: user wins a player for $1 when no CPU counters
