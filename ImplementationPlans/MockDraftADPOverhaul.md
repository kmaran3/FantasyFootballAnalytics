# Mock Draft ADP Overhaul

## Overview

Three interconnected changes:

1. **Rankings page ADP fix** — Sleeper ADP is scoring-format-agnostic right now (same ranks for PPR/Half/Standard); replace with format-specific ADP endpoints
2. **Mock draft player source** — Add a ranking source selector in the draft lobby: Darkhorse, Sleeper, ESPN, Yahoo. Player pool and order in the draft changes based on selection
3. **CPU pick logic overhaul** — Replace rank-based weighted random with a Gaussian ADP selection model with positional scarcity, human behavior modifiers, and stacking for snake draft; replace flat value estimate with VORP + budget curve logic for auction. Tiers are excluded for now — a future model will generate custom tiers to plug in.

---

## Current State

### Rankings page ADP
- `_fetch_sleeper_adp()` in `views.py` hits `https://api.sleeper.app/v1/players/nfl` and uses `search_rank` — a single universal rank, not scoring-format-aware
- The same `_sleeper_adp` DataFrame is joined to PPR, Half PPR, and Standard rankings — so the ADP column is identical across all three formats

### Mock draft player source
- `/mockdraft/players?scoring=<x>` returns `_model_table[scoring]` — always Darkhorse model rankings
- No option for external ADP sources in the lobby UI

### CPU snake pick logic (`cpuChoosePlayer`)
- Looks at top `max(8, round * 3)` available players
- Weights by `1 / (1 + i)^1.5` — purely rank-position based
- No ADP awareness, no stacking, no human behavior modifiers

### CPU auction bid logic (`cpuConsiderBid` / `cpuPlayerValue`)
- `playerVal = ((total - rank) / total) * budget * 0.8 * posWeight`
- Flat: no VORP, no budget phase curve, no positional scarcity pressure
- CPU bids `+$1` if `nextBid < playerVal` (with 20% random pass)

---

## Implementation Plan

---

### Part 1 — Fix Rankings Page ADP (scoring-format-specific)

**Backend: `views.py`**

1. Replace `_fetch_sleeper_adp()` with `_fetch_sleeper_adp(scoring)` that hits the correct endpoint per format:
   - PPR: `https://api.sleeper.app/v1/players/nfl` — use `search_rank` (already PPR-biased)
   - Half PPR: `https://api.sleeper.app/v1/players/nfl` — use `search_rank` from a half-PPR projection endpoint or compute as weighted average between PPR and standard ranks
   - Standard: use standard-specific endpoint if available, otherwise derive

   **Practical approach**: Sleeper's `/v1/players/nfl` only has one rank. Use their ADP endpoint instead:
   - `GET https://api.sleeper.app/v1/stats/nfl/2025?season_type=regular` — not ADP
   - Better: `GET https://api.sleeper.app/projections/nfl/2025/1?season_type=regular&position=QB&position=RB&position=WR&position=TE&order_by=<scoring_type>` for scoring-aware ordering

   **Simplest correct approach**: Fetch Sleeper ADP three times with different `order_by` params:
   ```
   PPR:      order_by=pts_ppr
   Half PPR: order_by=pts_half_ppr
   Standard: order_by=pts_std
   ```
   Endpoint: `GET https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=168&limit=200`
   — actually, best endpoint is the projections one. Document exact URL when confirmed working.

2. Store three separate DataFrames at startup:
   ```python
   _sleeper_adp = {
       'ppr':      _fetch_sleeper_adp('ppr'),
       'half_ppr': _fetch_sleeper_adp('half_ppr'),
       'standard': _fetch_sleeper_adp('standard'),
   }
   ```

3. In `_load_model_rankings(scoring)`, join the correct `_sleeper_adp[scoring]` instead of the single flat one

---

### Part 2 — Mock Draft Ranking Source Selector

**Backend: `views.py`**

1. Add new endpoint `GET /mockdraft/players?scoring=<x>&source=<s>` where `source` is one of:
   - `darkhorse` — existing `_model_table[scoring]` (default)
   - `sleeper` — `_sleeper_adp[scoring]`, return as ranked player list
   - `espn` — fetch from ESPN ADP endpoint at draft time (cached)
   - `yahoo` — fetch from Yahoo ADP endpoint at draft time (cached)

2. For external sources (sleeper/espn/yahoo), the player objects returned need the same shape as Darkhorse:
   ```json
   { "Name": "...", "Position": "WR", "Team": "LA", "Rank": 12, "ADP": 12 }
   ```

3. ESPN ADP source:
   - `GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info`
   - Requires no auth for public ADP data; returns `players[].draftRanksByRankType.STANDARD/PPR/HALF`

4. Yahoo ADP source:
   - `GET https://pub.api.fantasy.yahoo.com/fantasy/v2/players?format=json&sort=AR&count=200`
   - Returns average draft rank `editorial_player_roster_stats`
   - Note: Yahoo may require OAuth — if so, label it "Yahoo (requires login)" and skip for MVP; implement Sleeper + ESPN first

5. Cache external ADP fetches at startup just like Sleeper (in-memory, refreshed on app restart)

**Frontend: `mockdraft.html` / lobby UI**

6. Add a "Rankings Source" toggle group in the lobby settings:
   ```
   [ Darkhorse ]  [ Sleeper ]  [ ESPN ]  [ Yahoo ]
   ```
   Default: `darkhorse`

7. Pass `source` param when fetching players on draft start:
   ```javascript
   $.get(`/mockdraft/players?scoring=${S.scoring}&source=${S.rankingSource}`, ...)
   ```

8. Show a note under the selector:
   - Darkhorse: "Darkhorse model predictions (2026 projections)"
   - Sleeper, ESPN, Yahoo: "Community ADP — reflects consensus draft value"

---

### Part 3 — Gaussian ADP Snake Pick Model

**Frontend: `mockdraft.js`** — replace `cpuChoosePlayer`

#### Core formula

```
pickScore(player, team) =
    gaussianADP(player.ADP, currentPick)   // how likely this player is available here
  + positionalScarcity(player.pos)          // urgency based on how many of this pos remain
  + rosterFitBonus(player.pos, team.needs)  // does team need this position now
  + humanModifier(player.pos, round)        // positional tendencies
  + noise(0.05)                             // small random factor

pick = weightedRandom(candidates, pickScore)
```

> **Note:** Tier bonuses are intentionally excluded. A future model will generate custom player tiers (e.g. based on projected PPG clusters) that will be plugged in here as an additional score component.

#### Gaussian ADP probability

```javascript
function gaussianADPProb(adp, currentPick) {
    // σ scales with pick number — more variance late in drafts
    const sigma = 8 + currentPick * 0.3;
    const delta = adp - currentPick;
    return Math.exp(-(delta * delta) / (2 * sigma * sigma));
}
```

- Players available well above their ADP get high probability (value picks)
- Players drafted near their ADP get moderate probability
- Players below their ADP get very low probability (CPU avoids reaching)

#### Positional scarcity multiplier

Count remaining players per position in `S.available`:
```javascript
function positionalScarcity(pos) {
    const remaining = S.available.filter(i => S.players[i].Position === pos).length;
    const total = S.players.filter(p => p.Position === pos).length;
    const pctLeft = remaining / total;
    // More scarce = higher multiplier
    return 0.3 * (1 - pctLeft);
}
```

#### Human behavior modifiers

```javascript
function humanModifier(pos, round, team) {
    let mod = 0;

    // RB scarcity early — CPUs run on RBs in rounds 1-4
    if (pos === 'RB' && round <= 4) mod += 0.25;

    // WR depth stability — CPUs stock WRs in rounds 5-9
    if (pos === 'WR' && round >= 5 && round <= 9) mod += 0.15;

    // QB late-round preference — most CPUs wait on QB
    if (pos === 'QB') {
        if (round <= 5) mod -= 0.3;          // penalize early QB
        if (round >= 8 && round <= 11) mod += 0.2; // reward QB in sweet spot
    }

    // TE Kelce effect — if a TE with ADP <= 12 is still available early, CPU grabs it
    if (pos === 'TE') {
        const eliteTE = S.available.some(i =>
            S.players[i].Position === 'TE' && (S.players[i].ADP || 999) <= 12
        );
        if (eliteTE && round <= 3) mod += 0.35;
        else if (round <= 6) mod -= 0.1; // otherwise deprioritize early TE
    }

    // Stacking — QB + WR same NFL team
    if (pos === 'WR') {
        const teamQB = team.picks.find(p => p.position === 'QB');
        if (teamQB) {
            // find WR's nfl_team matches QB's nfl_team
            // applied when evaluating specific player
        }
    }

    return mod;
}
```

#### Stacking bonus

```javascript
function stackingBonus(player, teamPicks) {
    if (player.Position !== 'WR' && player.Position !== 'TE') return 0;
    const teamQB = teamPicks.find(p => p.position === 'QB');
    if (!teamQB) return 0;
    if (player.Team === teamQB.nfl_team) return 0.2; // same NFL team bonus
    return 0;
}
```

#### Updated `cpuChoosePlayer`

```javascript
function cpuChoosePlayer(teamIdx) {
    if (S.available.length === 0) return -1;
    const teamPicks = S.board[teamIdx];
    const posNeeds  = computePosNeeds(teamPicks, S.totalRounds - S.round);
    const currentPick = S.currentPickIdx + 1;

    let candidates = [];

    for (const pIdx of S.available) {
        const p   = S.players[pIdx];
        const pos = (p.Position || '').toUpperCase();

        // Hard filter: if bench is 0 AND position isn't needed, skip
        if (posNeeds[pos] === 0 && posNeeds['FLEX'] === 0 && posNeeds['Bench'] === 0) continue;

        const adp = p.ADP || p.Rank || pIdx + 1;

        const score =
            gaussianADPProb(adp, currentPick)
          + positionalScarcity(pos)
          + rosterFitBonus(pos, posNeeds)
          + humanModifier(pos, S.round, { picks: teamPicks })
          + stackingBonus(p, teamPicks)
          + (Math.random() * 0.05); // noise

        candidates.push({ pIdx, score });
    }

    if (candidates.length === 0) return S.available[0];

    // Weighted random by score (softmax-style)
    return weightedRandom(candidates);
}
```

---

### Part 4 — Auction CPU Overhaul

**Frontend: `mockdraft.js`** — replace `cpuPlayerValue` and `cpuConsiderBid`

#### Player value formula

```javascript
function cpuPlayerValue(teamIdx, playerIdx) {
    const p         = S.players[playerIdx];
    const pos       = (p.Position || 'WR').toUpperCase();
    const adp       = p.ADP || p.Rank || playerIdx + 1;
    const totalPl   = S.players.length;
    const budget    = S.auctionBudget;

    // VORP: value over replacement baseline player at this position
    const baseline  = AUCTION_BASELINES[pos] || 100;
    const vorp      = Math.max(0, (baseline - adp) / baseline);  // 0-1 scale

    // Positional scarcity: how many of this pos still available?
    const scarc     = positionalScarcity(pos); // reuse from snake

    // ADP expectation: implied dollar value based on ADP
    // Rule of thumb: ADP 1 ≈ $60, ADP 200 ≈ $1 in a $200 budget 12-team league
    const impliedVal = Math.max(1, budget * 0.7 * Math.pow((totalPl - adp + 1) / totalPl, 1.4));

    // Budget pressure: how much of own budget is left relative to needs?
    const filled     = S.board[teamIdx].length;
    const slotsLeft  = S.totalRounds - filled;
    const budgetLeft = S.budgets[teamIdx];
    const budgetPct  = budgetLeft / budget;
    const needsPct   = slotsLeft / S.totalRounds;
    const pressure   = budgetPct - needsPct; // positive = flush, negative = tight

    // Combine
    let val = impliedVal * (1 + vorp * 0.4 + scarc * 0.3);

    // Aggression factor: each CPU team gets a random aggression multiplier at draft start
    const aggression = S.cpuAggression[teamIdx] || 1.0; // set at draft init, range 0.8–1.2
    val *= aggression;

    return Math.floor(val);
}
```

Baselines for VORP (ADP of last "starter" at each position in 12-team league):
```javascript
const AUCTION_BASELINES = { QB: 13, RB: 37, WR: 37, TE: 13 };
```

#### Budget curve logic

```javascript
function budgetCurveMultiplier(teamIdx) {
    const filled    = S.board[teamIdx].length;
    const total     = S.totalRounds;
    const phasePct  = filled / total;

    if (phasePct < 0.3) return 1.15;  // early: spend freely, bid above value
    if (phasePct < 0.6) return 1.0;   // mid: disciplined
    if (phasePct < 0.85) return 0.9;  // late: conservative, save for needs
    return 1.2;                         // desperation: fill roster at any cost
}
```

#### Updated `cpuConsiderBid`

```javascript
function cpuConsiderBid(teamIdx) {
    if (S.currentNominee === null) return;
    if (S.rosterFilled[teamIdx]) return;
    if (teamIdx === S.currentBidder) return;

    const p         = S.players[S.currentNominee];
    const pos       = (p.Position || '').toUpperCase();
    const posNeeds  = computePosNeeds(S.board[teamIdx], S.totalRounds - S.board[teamIdx].length);
    const needsPos  = posNeeds[pos] > 0 || posNeeds['FLEX'] > 0 || posNeeds['Bench'] > 0;
    if (!needsPos) return; // CPU doesn't bid on positions it doesn't need

    const baseVal    = cpuPlayerValue(teamIdx, S.currentNominee);
    const curveMulti = budgetCurveMultiplier(teamIdx);
    const perceivedVal = Math.floor(baseVal * curveMulti);

    // Budget constraint: keep $1 per remaining slot
    const filled    = S.board[teamIdx].length;
    const slotsLeft = S.totalRounds - filled - 1;
    const maxCanBid = S.budgets[teamIdx] - Math.max(0, slotsLeft);

    const nextBid = S.currentBid + 1;
    if (nextBid > maxCanBid) return;
    if (nextBid > perceivedVal) return;

    // Random pass chance decreases when CPU really needs the position
    const passChance = needsPos ? 0.1 : 0.3;
    if (Math.random() < passChance) return;

    placeBidFrom(nextBid, teamIdx);
}
```

#### CPU aggression initialization

In `startAuction()`, assign a random aggression factor per CPU team at draft start:
```javascript
S.cpuAggression = Array(S.numTeams).fill(null).map((_, i) =>
    i === S.userTeamIdx ? 1.0 : 0.85 + Math.random() * 0.35  // 0.85–1.2
);
```

---

## File Changes Summary

| File | Change |
|------|--------|
| `webapp/views.py` | Replace `_fetch_sleeper_adp()` with scoring-aware version; add ESPN + Yahoo ADP fetchers; update `/mockdraft/players` to accept `source` param |
| `webapp/static/js/mockdraft.js` | Replace `cpuChoosePlayer` with Gaussian ADP model; add scarcity/stacking/human modifier functions; replace `cpuPlayerValue` + `cpuConsiderBid` with VORP + budget curve; add `S.cpuAggression` to state; add `S.rankingSource` to state |
| `webapp/templates/mockdraft.html` | Add "Rankings Source" toggle group in lobby; pass `source` to player fetch |

---

## Data Flow

```
Lobby: user picks scoring format + ranking source
  → Draft start: fetch /mockdraft/players?scoring=ppr&source=sleeper
      ← [{Name, Position, Team, Rank, ADP}, ...]
  → Players sorted by ADP (or Rank for Darkhorse)
  → Each CPU pick:
      for each available player:
          score = gaussianADP + scarcity + rosterFit + humanMod + stacking + noise
      pick = weightedRandom(scores)
  → Each CPU auction bid:
      perceivedVal = VORP_impliedVal * curveMultiplier * aggression
      bid if nextBid <= perceivedVal AND nextBid <= maxCanBid
```

---

## Testing Checklist

- [ ] Rankings page: PPR ADP differs from Half PPR ADP differs from Standard ADP
- [ ] Mock draft lobby shows 4 source options; selecting Sleeper/ESPN/Yahoo changes player order
- [ ] CPU picks feel realistic — no QB in round 1 (unless elite ADP), RB run in rounds 2-4
- [ ] Stacking: some CPU teams end up with QB + WR on same NFL team
- [ ] Auction: early picks (Tyreek, CMC, etc.) drive up to $50-70 range; late picks settle near $1-5
- [ ] Budget curve: CPU teams don't blow full budget in round 2 and then nominate with $0 left
- [ ] Desperation bidding visible in final rounds of auction
- [ ] All 4 ADP sources return sensible player pools with no crashes
