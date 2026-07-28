/* ═══════════════════════════════════════════════════════════════
   DRAFT BOARD — draft_board.js
   Real-time live draft tracker with Sleeper sync + AI suggestions
═══════════════════════════════════════════════════════════════ */

'use strict';

// ── State ─────────────────────────────────────────────────────
const DB = {
    // Session settings
    source:        'manual',
    leagueId:      null,
    draftId:       null,
    leagueName:    'Draft Board',
    numTeams:      12,
    numRounds:     15,
    userSlot:      1,          // 1-indexed
    teamNames:     [],
    scoringFormat: 'ppr',
    rosterSlots:   { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DST: 1, bench: 6 },

    // Sleeper user info (stored so polls know who the user is)
    sleeperUserId: null,

    // ESPN auth (stored so polls can include cookies)
    espnCookies:   null,   // {espn_s2, swid} or null

    // ESPN user team ID (for reconnecting / season switching)
    espnUserTeamId: null,

    // Season history
    season:            null,   // current season year being viewed
    previousLeagueId:  null,   // Sleeper's previous_league_id for chaining
    sleeperRootLeagueId: null, // the newest Sleeper league ID (for chaining to any season)
    sleeperRootSeason:   null, // the season of the root league
    seasonHistory:     [],     // [{year, leagueId}] for the season selector
    standings:         [],     // [{slot, name, wins, losses, ties, pts_for, seed, rank}]
    leagueStartYear:   null,   // earliest year the league existed

    // Live draft state
    players:        [],        // Full ranked list [{Rank, Name, Position, Team, ADP}]
    drafted:        new Set(), // Set of player Names that are drafted
    board:          [],        // board[r][t] = pick obj | null  (0-indexed round & team)
    userRoster:     [],        // user's picks in order
    otherRosters:   {},        // teamIdx (0-indexed) → [pick]
    currentPickNo:  0,         // last overall pick number that has been filled

    // Pending picker state (manual mode)
    pendingRound:   null,
    pendingTeamIdx: null,

    // Full league roster data — structured per Sleeper sections
    // fullRosters[teamIdx] = { starters:[{slot,player}], bench:[], reserve:[], taxi:[] }
    fullRosters:       null,
    starterSlotLabels: [],   // e.g. ['QB','RB','RB','WR','WR','TE','FLEX']
    draftComplete:     false,
    leagueType:        'redraft',   // 'redraft' | 'dynasty' | 'keeper'

    // Polling
    syncInterval:   null,
    lastSyncAt:     null,
    syncErrorCount: 0,

    // UI
    posFilter:       'ALL',
    searchQuery:     '',
    showAvailOnly:   false,    // when true, hide drafted players from the left panel
    activeOtTab:     -999,     // teamIdx shown in other-teams panel; -999 = My Team
    saveDebounce:    null,
    aiDebounce:      null,
};

// ── Panel top alignment ──────────────────────────────────────

function _syncPanelTop() {
    requestAnimationFrame(() => {
        const topbar = document.getElementById('db-topbar');
        const banner = document.querySelector('header.banner');
        if (!topbar) return;
        const bannerH = banner ? banner.offsetHeight : 0;
        document.documentElement.style.setProperty('--banner-h', bannerH + 'px');
        document.documentElement.style.setProperty('--panel-top', (bannerH + topbar.offsetHeight) + 'px');
    });
}

function _alignPanelHeader() {
    requestAnimationFrame(() => {
        const boardHeader = document.querySelector('#db-board-table thead');
        const panelHeader = document.querySelector('#db-available-panel .db-panel-header');
        const layout = document.querySelector('.db-layout');
        if (!boardHeader || !panelHeader || !layout) return;

        // Match panel header height to board thead
        const boardHeaderBottom = boardHeader.getBoundingClientRect().bottom;
        const panelTop = panelHeader.getBoundingClientRect().top;
        panelHeader.style.height = (boardHeaderBottom - panelTop) + 'px';
        panelHeader.style.boxSizing = 'border-box';

        // Draw one continuous gold line across the full layout width
        let goldLine = layout.querySelector('.db-gold-line');
        if (!goldLine) {
            goldLine = document.createElement('div');
            goldLine.className = 'db-gold-line';
            layout.appendChild(goldLine);
        }
        const layoutTop = layout.getBoundingClientRect().top;
        goldLine.style.top = (boardHeaderBottom - layoutTop) + 'px';

        // For standings view: align rows and draw continuous row lines
        // Remove old row lines
        layout.querySelectorAll('.db-row-line').forEach(el => el.remove());

        const isStandings = _isHistoricalSeason() && DB.standings && DB.standings.length > 0;
        if (isStandings) {
            const boardRows = document.querySelectorAll('#db-board-body tr');
            const standingsRows = document.querySelectorAll('#db-player-list .db-standings-row');
            if (standingsRows.length) {
                // Align standings rows that have corresponding board rows
                standingsRows.forEach((row, i) => {
                    if (boardRows[i]) {
                        row.style.height = boardRows[i].getBoundingClientRect().height + 'px';
                        row.style.minHeight = row.style.height;
                    } else {
                        // More standings than rounds — use default height
                        row.style.height = '';
                        row.style.minHeight = '';
                    }
                });

                // Draw continuous full-width lines where board rows exist
                const alignedCount = Math.min(boardRows.length, standingsRows.length);
                for (let i = 0; i < alignedCount - 1; i++) {
                    const rowBottom = boardRows[i].getBoundingClientRect().bottom;
                    const line = document.createElement('div');
                    line.className = 'db-row-line';
                    line.style.top = (rowBottom - layoutTop) + 'px';
                    layout.appendChild(line);
                }

                // Draw left-panel-only lines for standings rows beyond board rounds
                const panel = document.getElementById('db-available-panel');
                const panelW = panel ? panel.offsetWidth + 'px' : '236px';
                // Lines between standings rows beyond board rounds (not the last one)
                for (let i = Math.max(alignedCount - 1, 0); i < standingsRows.length - 1; i++) {
                    const rowBottom = standingsRows[i].getBoundingClientRect().bottom;
                    const line = document.createElement('div');
                    line.className = 'db-row-line';
                    line.style.top = Math.round(rowBottom - layoutTop) + 'px';
                    line.style.width = panelW;
                    layout.appendChild(line);
                }
                // Last row gets a CSS class for its bottom line (via ::after pseudo-element)
                standingsRows[standingsRows.length - 1].classList.add('db-standings-last');

                // Now that rows are resized, update active/panel height for standings handle
                const isDynasty = DB.leagueType === 'dynasty' || DB.leagueType === 'keeper';
                const isFirstYear = DB.leagueStartYear && DB.season === DB.leagueStartYear;
                if (isDynasty && !isFirstYear) {
                    const active = document.getElementById('db-active');
                    const lastRow = standingsRows[standingsRows.length - 1];
                    const lastRowBottom = lastRow.getBoundingClientRect().bottom;
                    const panelTop = panel.getBoundingClientRect().top;
                    const panelH = lastRowBottom - panelTop;
                    if (active) active.style.height = panelH + 'px';
                    if (panel) {
                        panel.style.height = panelH + 'px';
                        panel.style.maxHeight = panelH + 'px';
                    }
                }
            }
        }
    });
}

function _autosizeBoardHeight() {
    const board = document.getElementById('db-board-scroll');
    const table = document.getElementById('db-board-table');
    const panel = document.getElementById('db-available-panel');
    const active = document.getElementById('db-active');
    const layout = document.querySelector('.db-layout');
    const playerList = document.getElementById('db-player-list');
    if (!board || !table) return;

    const isDynasty = DB.leagueType === 'dynasty' || DB.leagueType === 'keeper';
    const isFirstYear = DB.leagueStartYear && DB.season === DB.leagueStartYear;

    // Standings are shown for any historical season with standings data.
    // Dynasty (non-first-year): handle aligns to standings bottom, board scrolls.
    // Non-dynasty: board height drives layout, but panel must still fit all standings.
    const hasStandings = _isHistoricalSeason() && DB.standings && DB.standings.length > 0;
    const isDynastyStandings = isDynasty && !isFirstYear && hasStandings;

    if (isDynastyStandings && panel && playerList) {
        // Historical dynasty standings mode: layout driven by standings height.
        // Standings should NOT scroll — show all teams fully.
        playerList.style.overflow = 'visible';
        playerList.style.flex = 'none';
        panel.style.overflow = 'visible';

        // Measure actual content: panel header + standings rows
        panel.style.height = '';
        panel.style.maxHeight = '';
        panel.style.bottom = '';
        if (layout) layout.style.height = '';

        // Measure from panel top to bottom of last standings row + 1px for the line
        const standingsRows = playerList.querySelectorAll('.db-standings-row');
        const lastRow = standingsRows.length ? standingsRows[standingsRows.length - 1] : null;
        let panelH;
        if (lastRow) {
            const panelTop = panel.getBoundingClientRect().top;
            panelH = lastRow.getBoundingClientRect().bottom - panelTop;
        } else {
            const panelHeader = panel.querySelector('.db-panel-header');
            const headerH = panelHeader ? panelHeader.offsetHeight : 0;
            panelH = headerH + playerList.scrollHeight;
        }

        // Set db-active height so the handle sits right after the final line.
        if (active) active.style.height = panelH + 'px';
        // Fix panel at standings height — remove bottom:0 so it doesn't stretch
        panel.style.height = panelH + 'px';
        panel.style.maxHeight = panelH + 'px';
        panel.style.bottom = 'auto';
        if (layout) layout.style.height = '';
        board.style.overflowY = 'auto';
    } else if (isDynasty && !_isHistoricalSeason() && playerList) {
        // Dynasty current year: align handle with the bottom of the 7th player row
        board.style.overflowY = 'auto';
        playerList.style.overflow = '';
        playerList.style.flex = '';
        if (panel) panel.style.overflow = '';

        // Measure height through the 7th player row
        const rows = playerList.querySelectorAll('.db-player-row');
        let targetH = 0;
        if (rows.length >= 7) {
            const listTop = playerList.getBoundingClientRect().top;
            const row7 = rows[6]; // 0-indexed
            targetH = row7.getBoundingClientRect().bottom - listTop;
        }
        // Add panel header height (everything above the player list)
        const panelHeaderH = playerList.offsetTop; // distance from panel top to list top
        const cutoff = panelHeaderH + targetH;

        if (cutoff > 0 && panel) {
            if (active) active.style.height = cutoff + 'px';
            panel.style.height = '100%';
            panel.style.maxHeight = '100%';
        } else {
            // Fallback to board table height
            const tableH = table.offsetHeight;
            if (active) active.style.height = tableH + 'px';
            if (panel) { panel.style.height = '100%'; panel.style.maxHeight = '100%'; }
        }
        if (layout) layout.style.height = '';
    } else {
        // Default: layout driven by board table height
        const tableH = table.offsetHeight;
        board.style.overflowY = '';
        if (playerList) {
            playerList.style.overflow = '';
            playerList.style.flex = '';
        }

        // If standings are showing (non-dynasty historical), ensure panel fits all rows
        if (hasStandings && panel && playerList) {
            playerList.style.overflow = 'visible';
            playerList.style.flex = 'none';
            panel.style.overflow = 'visible';
            const panelHeader = panel.querySelector('.db-panel-header');
            const headerH = panelHeader ? panelHeader.offsetHeight : 0;
            const listH = playerList.scrollHeight;
            const panelH = headerH + listH;
            // Use whichever is taller: board or standings
            const finalH = Math.max(tableH, panelH);
            if (active) active.style.height = finalH + 'px';
            panel.style.height = panelH + 'px';
            panel.style.maxHeight = panelH + 'px';
            panel.style.bottom = 'auto';
        } else {
            if (active) active.style.height = tableH + 'px';
            if (panel) {
                panel.style.height = '100%';
                panel.style.maxHeight = '100%';
                panel.style.overflow = '';
            }
        }
        if (layout) layout.style.height = '';
    }
}

// ── Snake draft math ──────────────────────────────────────────

/** pick_no (1-indexed) → {round, teamIdx} (both 0-indexed internally, round is 1-indexed) */
function pickToSlot(pickNo, numTeams) {
    const round        = Math.ceil(pickNo / numTeams);
    const posInRound   = pickNo - (round - 1) * numTeams;
    const teamIdx      = (round % 2 === 1) ? posInRound - 1 : numTeams - posInRound;
    return { round, teamIdx };
}

/** round (1-indexed) + teamIdx (0-indexed) → pick_no (1-indexed) */
function slotToPickNo(round, teamIdx, numTeams) {
    const posInRound = (round % 2 === 1) ? teamIdx + 1 : numTeams - teamIdx;
    return (round - 1) * numTeams + posInRound;
}

/** Returns the next overall pick_no where the user drafts, after currentPickNo */
function userNextPickNo() {
    const userIdx = DB.userSlot - 1;
    for (let p = DB.currentPickNo + 1; p <= DB.numTeams * DB.numRounds; p++) {
        if (pickToSlot(p, DB.numTeams).teamIdx === userIdx) return p;
    }
    return -1;
}

/** Picks until user's next turn */
function picksUntilUser() {
    const next = userNextPickNo();
    if (next < 0) return 99;
    return next - DB.currentPickNo - 1;
}

// ── Player name helpers ───────────────────────────────────────
function shortName(name) {
    if (!name) return '';
    const parts = name.trim().split(/\s+/);
    if (parts.length < 2) return name;
    return parts[0][0] + '. ' + parts.slice(1).join(' ');
}

/** Convert Sleeper slot labels to readable form: SUPER_FLEX → "Super Flex", IDP_FLEX → "IDP", etc. */
function formatSlotLabel(label) {
    if (!label) return '?';
    const map = {
        'SUPER_FLEX': 'Super Flex',
        'IDP_FLEX':   'IDP',
        'FLEX':       'Flex',
        'DST':        'D/ST',
        'QB':         'QB',
        'RB':         'RB',
        'WR':         'WR',
        'TE':         'TE',
        'K':          'K',
        'BN':         'BN',
        'IR':         'IR',
        'TAXI':       'TAXI',
    };
    return map[label.toUpperCase()] || label;
}

function normalizeName(name) {
    return (name || '')
        .toLowerCase()
        .replace(/[^a-z0-9 ]/g, '')           // strip punctuation
        .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '') // strip name suffixes
        .replace(/\s+/g, ' ')
        .trim();
}

/** Build a link to the player profile page. */
function profileUrl(name, pos, nflTeam) {
    return `/player/${encodeURIComponent(name)}?pos=${encodeURIComponent(pos || '')}&team=${encodeURIComponent(nflTeam || '')}&back=/draft-board`;
}

function posClass(pos) {
    const p = (pos || '').toUpperCase();
    const map = { QB: 'pos-QB', RB: 'pos-RB', WR: 'pos-WR', TE: 'pos-TE', K: 'pos-K', DST: 'pos-DST', DEF: 'pos-DST' };
    return map[p] || '';
}

function badge(pos) {
    return `<span class="db-pos-badge ${posClass(pos)}">${pos || '?'}</span>`;
}

function escHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function buildPlayerUpdateMarkup(update) {
    if (!update || !update.has_update || !update.summary) return '';
    const parts = [update.summary];
    if (update.detail) parts.push(update.detail);
    if (update.updated_label) parts.push(`Updated ${update.updated_label}`);
    const text = parts.join(' | ');
    return `<div class="db-player-update db-player-update-${update.tone || 'info'}" title="${escHtml(update.title || text)}">${escHtml(text)}</div>`;
}

// ── Setup panel logic ─────────────────────────────────────────

function initSetupPanel() {
    // Source tab switching
    document.querySelectorAll('.db-source-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            document.querySelectorAll('.db-source-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const src = btn.dataset.source;
            document.getElementById('setup-sleeper').style.display = (src === 'sleeper') ? '' : 'none';
            document.getElementById('setup-manual').style.display  = (src === 'manual')  ? '' : 'none';
            const espnEl = document.getElementById('setup-espn');
            if (espnEl) espnEl.style.display = (src === 'espn') ? '' : 'none';
        });
    });

    // Sleeper lookup
    document.getElementById('sleeper-lookup-btn').addEventListener('click', sleeperLookup);
    document.getElementById('sleeper-username').addEventListener('keydown', e => {
        if (e.key === 'Enter') sleeperLookup();
    });

    // Sleeper league selection → show connect button
    document.getElementById('sleeper-league-select').addEventListener('change', function () {
        const has = this.value !== '';
        document.getElementById('sleeper-connect-btn').style.display = has ? '' : 'none';
        document.getElementById('sleeper-scoring-group').style.display = has ? '' : 'none';
    });

    document.getElementById('sleeper-connect-btn').addEventListener('click', sleeperConnect);

    // ESPN lookup + connect
    document.getElementById('espn-lookup-btn').addEventListener('click', espnLookup);
    document.getElementById('espn-league-id').addEventListener('keydown', e => {
        if (e.key === 'Enter') espnLookup();
    });
    document.getElementById('espn-connect-btn').addEventListener('click', espnConnect);

    // Manual: populate slot selects + team names
    const numTeamsSel = document.getElementById('manual-num-teams');
    numTeamsSel.addEventListener('change', buildManualTeamUI);
    buildManualTeamUI();

    document.getElementById('manual-start-btn').addEventListener('click', manualStart);
}

async function sleeperLookup() {
    const username = document.getElementById('sleeper-username').value.trim();
    if (!username) return;
    const errEl = document.getElementById('sleeper-error');
    errEl.style.display = 'none';
    const btn = document.getElementById('sleeper-lookup-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="db-spinner"></span>Searching…';

    try {
        const res = await fetch('/draft-board/sleeper/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username }),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            showSetupError('sleeper', data.error || 'Could not find Sleeper user.');
            return;
        }

        DB.sleeperUserId = data.user_id;

        const sel = document.getElementById('sleeper-league-select');
        sel.innerHTML = '<option value="">Choose a league…</option>';
        (data.leagues || []).forEach(lg => {
            const opt = document.createElement('option');
            opt.value = lg.league_id;
            opt.textContent = `${lg.name} (${lg.num_teams} teams, ${lg.scoring.toUpperCase()})`;
            opt.dataset.scoring = lg.scoring;
            sel.appendChild(opt);
        });

        document.getElementById('sleeper-league-group').style.display = '';
        document.getElementById('sleeper-connect-btn').style.display   = 'none';
        document.getElementById('sleeper-scoring-group').style.display  = 'none';
    } catch (e) {
        showSetupError('sleeper', 'Network error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Find Leagues';
    }
}

async function sleeperConnect() {
    const leagueId = document.getElementById('sleeper-league-select').value;
    if (!leagueId) return;

    const selectedOpt = document.querySelector('#sleeper-league-select option:checked');
    const detectedScoring = selectedOpt?.dataset?.scoring || 'ppr';
    document.getElementById('sleeper-scoring-select').value = detectedScoring;

    const scoringFormat = document.getElementById('sleeper-scoring-select').value;
    const errEl = document.getElementById('sleeper-error');
    errEl.style.display = 'none';
    const btn = document.getElementById('sleeper-connect-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="db-spinner"></span>Connecting…';

    try {
        const res = await fetch('/draft-board/sleeper/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ league_id: leagueId, sleeper_user_id: DB.sleeperUserId }),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            showSetupError('sleeper', data.error || 'Could not connect to league.');
            return;
        }

        // Save this league to the user's account
        try {
            const saveRes = await fetch('/draft-board/leagues/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    league_id:        leagueId,
                    league_name:      data.league_name,
                    source:           'sleeper',
                    num_teams:        data.num_teams,
                    scoring:          scoringFormat,
                    league_type:      data.league_type || 'redraft',
                    sleeper_user_id:  DB.sleeperUserId,
                    user_slot:        data.user_slot,
                }),
            });
            if (!saveRes.ok) console.error('League save failed:', saveRes.status, await saveRes.text());
        } catch (e) { console.error('League save error:', e); }

        // Store root league info for season navigation
        DB.sleeperRootLeagueId = leagueId;
        DB.sleeperRootSeason = parseInt(data.season) || new Date().getFullYear();

        await initBoard({
            source:             'sleeper',
            leagueId:           leagueId,
            draftId:            data.draft_id,
            leagueName:         data.league_name,
            numTeams:           data.num_teams,
            numRounds:          data.num_rounds,
            userSlot:           data.user_slot,
            teamNames:          data.team_names,
            scoringFormat:      scoringFormat,
            rosterSlots:        data.roster_slots,
            starterSlotLabels:  data.starter_slot_labels || [],
            existingPicks:      data.picks || [],
            teamRosters:        data.team_rosters || null,
            rosterPlayerNames:  data.roster_player_names || [],
            draftStatus:        data.draft_status || 'pre_draft',
            leagueType:         data.league_type  || 'redraft',
            season:             data.season || new Date().getFullYear(),
            previousLeagueId:   data.previous_league_id || null,
            standings:          data.standings || [],
            leagueStartYear:    data.league_start_year || null,
        });
    } catch (e) {
        showSetupError('sleeper', 'Network error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Connect to League';
    }
}

// ── ESPN paste-cookies helper (called from inline onclick) ────
window.espnShowPasteBox = function () {
    const box = document.getElementById('espn-paste-box');
    if (!box) return;
    box.style.display = '';
    box.focus();
    box.addEventListener('input', function handler() {
        const raw = box.value.trim();
        if (!raw) return;
        try {
            const obj = JSON.parse(raw);
            if (obj.espn_s2 && obj.swid) {
                document.getElementById('espn-s2').value   = obj.espn_s2;
                document.getElementById('espn-swid').value = obj.swid;
                document.getElementById('espn-cookie-status').textContent = '✓ Cookies pasted';
                document.getElementById('espn-cookie-status').style.color = 'var(--green, #4caf50)';
                box.style.display = 'none';
                box.removeEventListener('input', handler);
            }
        } catch (_) { /* not valid JSON yet */ }
    });
};

async function espnLookup() {
    const leagueId = document.getElementById('espn-league-id').value.trim();
    if (!leagueId) return;

    const errEl = document.getElementById('espn-error');
    errEl.style.display = 'none';
    const btn = document.getElementById('espn-lookup-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="db-spinner"></span>Searching…';

    const espnS2  = document.getElementById('espn-s2').value.trim();
    const espnSwid = document.getElementById('espn-swid').value.trim();

    try {
        const body = { league_id: leagueId };
        if (espnS2 && espnSwid) {
            body.espn_s2 = espnS2;
            body.swid    = espnSwid;
        }

        const res = await fetch('/draft-board/espn/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();

        if (!res.ok || data.error) {
            if (data.error === 'private') {
                showSetupError('espn', 'This league is private. Add your ESPN cookies above and try again.');
                const toggle = document.getElementById('espn-private-toggle');
                if (toggle) toggle.open = true;
            } else {
                showSetupError('espn', data.message || data.error || 'Could not find ESPN league.');
            }
            return;
        }

        // Populate league info
        document.getElementById('espn-league-name').textContent = data.league_name;
        document.getElementById('espn-league-meta').textContent =
            `${data.num_teams} teams · ${(data.scoring || 'ppr').toUpperCase()} · ${data.season}`;
        document.getElementById('espn-league-info').style.display = '';

        // Populate team select
        const sel = document.getElementById('espn-team-select');
        sel.innerHTML = '<option value="">Choose your team…</option>';
        (data.teams || []).forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.name || t.abbrev || `Team ${t.id}`;
            sel.appendChild(opt);
        });

        // Store league data for connect step
        sel.dataset.leagueId   = data.league_id;
        sel.dataset.leagueName = data.league_name;
        sel.dataset.numTeams   = data.num_teams;
        sel.dataset.scoring    = data.scoring;
    } catch (e) {
        showSetupError('espn', 'Network error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Find League';
    }
}

async function espnConnect() {
    const sel = document.getElementById('espn-team-select');
    const userTeamId = sel.value;
    if (!userTeamId) {
        showSetupError('espn', 'Please select your team.');
        return;
    }

    const leagueId = sel.dataset.leagueId;
    const scoring  = sel.dataset.scoring || 'ppr';
    const errEl    = document.getElementById('espn-error');
    errEl.style.display = 'none';
    const btn = document.getElementById('espn-connect-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="db-spinner"></span>Connecting…';

    const espnS2  = document.getElementById('espn-s2').value.trim();
    const espnSwid = document.getElementById('espn-swid').value.trim();

    try {
        const body = { league_id: leagueId, user_team_id: userTeamId };
        if (espnS2 && espnSwid) {
            body.espn_s2 = espnS2;
            body.swid    = espnSwid;
        }

        const res = await fetch('/draft-board/espn/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            showSetupError('espn', data.error || 'Could not connect to league.');
            return;
        }

        // Store ESPN state for season switching
        DB.espnCookies     = (espnS2 && espnSwid) ? { espn_s2: espnS2, swid: espnSwid } : null;
        DB.espnUserTeamId  = userTeamId;

        // Save league with user_slot; stash user_team_id in sleeper_user_id column
        try {
            const saveRes = await fetch('/draft-board/leagues/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    league_id:       leagueId,
                    league_name:     data.league_name,
                    source:          'espn',
                    num_teams:       data.num_teams,
                    scoring:         scoring,
                    league_type:     data.league_type || 'redraft',
                    espn_s2:         espnS2 || null,
                    espn_swid:       espnSwid || null,
                    user_slot:       data.user_slot,
                    sleeper_user_id: userTeamId,
                }),
            });
            if (!saveRes.ok) console.error('League save failed:', saveRes.status, await saveRes.text());
        } catch (e) { console.error('League save error:', e); }

        await initBoard({
            source:             'espn',
            leagueId:           leagueId,
            draftId:            data.draft_id,
            leagueName:         data.league_name,
            numTeams:           data.num_teams,
            numRounds:          data.num_rounds,
            userSlot:           data.user_slot,
            teamNames:          data.team_names,
            scoringFormat:      scoring,
            rosterSlots:        data.roster_slots,
            starterSlotLabels:  data.starter_slot_labels || [],
            existingPicks:      data.picks || [],
            teamRosters:        data.team_rosters || null,
            rosterPlayerNames:  data.roster_player_names || [],
            draftStatus:        data.draft_status || 'pre_draft',
            leagueType:         data.league_type  || 'redraft',
            season:             data.season || new Date().getFullYear(),
            previousLeagueId:   data.previous_league_id || null,
            standings:          data.standings || [],
            leagueStartYear:    data.league_start_year || null,
        });
    } catch (e) {
        showSetupError('espn', 'Network error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Connect to League';
    }
}

function buildManualTeamUI() {
    const n   = parseInt(document.getElementById('manual-num-teams').value, 10);
    const sel = document.getElementById('manual-user-slot');
    const grid = document.getElementById('manual-team-names');

    sel.innerHTML = '';
    for (let i = 1; i <= n; i++) {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = `Slot ${i}`;
        sel.appendChild(opt);
    }

    grid.innerHTML = '';
    for (let i = 1; i <= n; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'db-team-name-entry';
        wrap.id = `team-entry-${i}`;
        wrap.innerHTML = `
            <span class="slot-label">${i}</span>
            <input class="db-form-input" id="team-name-${i}" type="text"
                   value="Team ${i}" style="font-size:0.82em;padding:5px 8px">
        `;
        grid.appendChild(wrap);
    }

    // Highlight user slot when it changes
    sel.addEventListener('change', highlightUserSlot);
    highlightUserSlot();
}

function highlightUserSlot() {
    const n    = parseInt(document.getElementById('manual-num-teams').value, 10);
    const slot = parseInt(document.getElementById('manual-user-slot').value, 10);
    for (let i = 1; i <= n; i++) {
        const entry = document.getElementById(`team-entry-${i}`);
        if (entry) entry.classList.toggle('user-slot', i === slot);
    }
}

function manualStart() {
    const n       = parseInt(document.getElementById('manual-num-teams').value, 10);
    const slot    = parseInt(document.getElementById('manual-user-slot').value, 10);
    const scoring = document.getElementById('manual-scoring').value;
    const rounds  = parseInt(document.getElementById('manual-num-rounds').value, 10);

    const rosterSlots = {
        QB:    parseInt(document.getElementById('slot-QB').value, 10) || 1,
        RB:    parseInt(document.getElementById('slot-RB').value, 10) || 2,
        WR:    parseInt(document.getElementById('slot-WR').value, 10) || 2,
        TE:    parseInt(document.getElementById('slot-TE').value, 10) || 1,
        FLEX:  parseInt(document.getElementById('slot-FLEX').value, 10) || 1,
        K:     1,
        DST:   1,
        bench: parseInt(document.getElementById('slot-bench').value, 10) || 6,
    };

    const teamNames = [];
    for (let i = 1; i <= n; i++) {
        teamNames.push(document.getElementById(`team-name-${i}`)?.value.trim() || `Team ${i}`);
    }

    initBoard({
        source:        'manual',
        leagueId:      null,
        draftId:       null,
        leagueName:    'My Draft',
        numTeams:      n,
        numRounds:     rounds,
        userSlot:      slot,
        teamNames,
        scoringFormat: scoring,
        rosterSlots,
        existingPicks: [],
    });
}

function showSetupError(panel, msg) {
    const el = document.getElementById(`${panel}-error`);
    if (el) { el.textContent = msg; el.style.display = ''; }
}

// ── Board initialisation ──────────────────────────────────────

async function initBoard(cfg) {
    window.scrollTo(0, 0);
    DB.source        = cfg.source;
    DB.leagueId      = cfg.leagueId;
    DB.draftId       = cfg.draftId;
    DB.leagueName    = cfg.leagueName || 'Draft Board';
    DB.numTeams      = cfg.numTeams;
    DB.numRounds     = cfg.numRounds;
    DB.userSlot      = cfg.userSlot;
    DB.teamNames     = cfg.teamNames;
    DB.scoringFormat = cfg.scoringFormat;
    DB.rosterSlots   = cfg.rosterSlots;

    DB.draftComplete      = cfg.draftStatus === 'complete';
    DB.leagueType         = cfg.leagueType || 'redraft';
    DB.fullRosters        = cfg.teamRosters || null;
    DB._analysisCache     = {};
    DB.starterSlotLabels  = cfg.starterSlotLabels || [];
    DB.season             = parseInt(cfg.season) || new Date().getFullYear();
    DB.previousLeagueId   = cfg.previousLeagueId || null;
    DB.standings          = cfg.standings || [];
    DB.leagueStartYear   = cfg.leagueStartYear || null;

    // Reset active tab to user's team
    DB.activeOtTab = (cfg.userSlot > 0) ? cfg.userSlot - 1 : 0;

    // Reset live state
    DB.drafted       = new Set();
    DB.board         = Array.from({ length: DB.numRounds }, () => Array(DB.numTeams).fill(null));
    DB.userRoster    = [];
    DB.otherRosters  = {};
    DB.currentPickNo = 0;
    for (let t = 0; t < DB.numTeams; t++) DB.otherRosters[t] = [];

    // Pre-populate drafted set from all roster players.
    // Primary: flat list of names resolved via Sleeper's own player map (most reliable).
    // Fallback: structured fullRosters data.
    if (cfg.rosterPlayerNames && cfg.rosterPlayerNames.length) {
        cfg.rosterPlayerNames.forEach(n => DB.drafted.add(normalizeName(n)));
    } else if (DB.fullRosters) {
        DB.fullRosters.forEach(roster => {
            if (!roster) return;
            const allPlayers = [
                ...(roster.starters || []).map(s => s.player).filter(Boolean),
                ...(roster.bench    || []),
                ...(roster.reserve  || []),
                ...(roster.taxi     || []),
            ];
            allPlayers.forEach(p => { if (p && p.name) DB.drafted.add(normalizeName(p.name)); });
        });
    }

    // Show board UI
    document.getElementById('db-setup-wrap').style.display  = 'none';
    document.getElementById('db-topbar').style.display      = '';
    const activeEl = document.getElementById('db-active');
    activeEl.style.display = '';
    activeEl.style.height = '';  // Clear any previous drag-resize height
    document.getElementById('db-bottom-drawer').style.display       = '';
    _syncPanelTop();
    // Auto-size board scroll area after rendering
    requestAnimationFrame(() => { _autosizeBoardHeight(); _alignPanelHeader(); });
    document.getElementById('db-league-name').textContent    = DB.leagueName;
    const _isHistorical = DB.season && DB.season < new Date().getFullYear();
    document.getElementById('db-topbar-meta').textContent   =
        `${DB.numTeams} teams · ${DB.scoringFormat.toUpperCase()} · ${DB.numRounds} rounds` +
        (_isHistorical ? ` · ${DB.season} season` : '');

    if (DB.source === 'sleeper' || DB.source === 'espn') {
        document.getElementById('db-sync-badge').style.display   = '';
        document.getElementById('db-sync-now-btn').style.display = '';
    }

    // Season selector — show for Sleeper and ESPN linked leagues
    const seasonWrap = document.getElementById('db-season-wrap');
    if (seasonWrap && (DB.source === 'sleeper' || DB.source === 'espn')) {
        seasonWrap.style.display = 'flex';
        buildSeasonSelector(parseInt(cfg.season) || new Date().getFullYear());
    } else if (seasonWrap) {
        seasonWrap.style.display = 'none';
    }

    // Render skeleton board and your-team slots
    renderBoard();
    renderRosterSlots();
    renderOtherTeamTabs();

    // Fetch player list
    DB.players = await fetchPlayers(DB.scoringFormat);
    renderLeftPanel();

    // Apply any existing picks (from Sleeper connect or saved session)
    for (const pick of (cfg.existingPicks || [])) {
        applyPick(pick, false);
    }

    updateCurrentPickBar();
    scheduleSaveState();

    // Re-align after all picks are rendered (board rows now have final heights)
    requestAnimationFrame(() => { _autosizeBoardHeight(); _alignPanelHeader(); });

    // Start live polling for Sleeper (only if draft is still in progress)
    if (DB.source === 'sleeper' && DB.draftId && !DB.draftComplete) {
        startPolling();
    } else if (DB.draftComplete) {
        setSyncStatus('paused', 'Draft complete');
    }

    // Trigger analysis now that all picks are loaded (runs for any draft state)
    renderDraftCompleteAnalysis(DB.activeOtTab);

    // Mobile FAB
    if (window.innerWidth <= 768) {
        document.getElementById('db-mobile-fab').style.display = 'flex';
    }
}

async function fetchPlayers(scoring) {
    try {
        const res = await fetch(`/mockdraft/players?scoring=${scoring}&source=darkhorse`);
        return res.ok ? await res.json() : [];
    } catch {
        return [];
    }
}

// ── Apply a pick ──────────────────────────────────────────────

/**
 * pick = { name, position, nfl_team, round, pick_no, draft_slot }
 *   OR  { name, position, nfl_team, round, teamIdx }  (manual)
 */
function applyPick(pick, animate) {
    animate = (animate !== false);

    const name     = pick.name || '';
    const pos      = (pick.position || '').toUpperCase();
    const nflTeam  = pick.nfl_team || pick.Team || '';
    let   round    = pick.round;
    let   teamIdx;

    if (pick.pick_no != null) {
        const slot = pickToSlot(pick.pick_no, DB.numTeams);
        round   = slot.round;
        teamIdx = slot.teamIdx;
    } else if (pick.draft_slot != null) {
        teamIdx = parseInt(pick.draft_slot, 10) - 1;
    } else if (pick.teamIdx != null) {
        teamIdx = pick.teamIdx;
    } else {
        return;
    }

    if (round < 1 || round > DB.numRounds) return;
    if (teamIdx < 0 || teamIdx >= DB.numTeams) return;
    if (DB.board[round - 1][teamIdx]) return; // already filled

    const pickObj = { name, position: pos, nfl_team: nflTeam, round, teamIdx };
    DB.board[round - 1][teamIdx] = pickObj;

    // Track drafted
    if (name) DB.drafted.add(normalizeName(name));

    // Update rosters
    if (teamIdx === DB.userSlot - 1) {
        DB.userRoster.push(pickObj);
    } else {
        DB.otherRosters[teamIdx].push(pickObj);
    }

    // Track current pick
    const pickNo = slotToPickNo(round, teamIdx, DB.numTeams);
    if (pickNo > DB.currentPickNo) DB.currentPickNo = pickNo;

    // Update DOM
    updateBoardCell(round, teamIdx, pickObj, animate);
    requestAnimationFrame(() => _autosizeBoardHeight());
    if (!_isHistoricalSeason() || !DB.standings || !DB.standings.length) renderAvailable();
    renderYourTeam();
    if (DB.activeOtTab === teamIdx) renderOtherTeamBody(teamIdx);
    updateCurrentPickBar();

    // Invalidate analysis cache for the affected team so next view re-fetches
    if (DB._analysisCache) {
        delete DB._analysisCache[teamIdx];
        delete DB._analysisCache[MY_TEAM_TAB]; // clear legacy key too
    }

    // Trigger AI (debounced)
    clearTimeout(DB.aiDebounce);
    DB.aiDebounce = setTimeout(fetchAISuggestions, 400);

    // Auto-save (debounced)
    scheduleSaveState();
}

// ── Board rendering ───────────────────────────────────────────

function renderBoard() {
    const header = document.getElementById('db-board-header');
    const body   = document.getElementById('db-board-body');

    // Header — no explicit widths; table-layout:fixed + width:100% distributes equally
    header.innerHTML = '<th class="db-round-col">Rd</th>';
    DB.teamNames.forEach((name, i) => {
        const th = document.createElement('th');
        th.className = 'db-team-col' + (i === DB.userSlot - 1 ? ' db-user-col' : '');
        th.textContent = name;
        header.appendChild(th);
    });
    // Scale font size down for large leagues so everything fits
    const table = document.getElementById('db-board-table');
    if (table) {
        const scale = DB.numTeams <= 10 ? 1 : DB.numTeams <= 12 ? 0.88 : DB.numTeams <= 14 ? 0.80 : 0.74;
        table.style.fontSize = scale + 'em';
    }

    // Rows
    body.innerHTML = '';
    for (let r = 1; r <= DB.numRounds; r++) {
        const tr = document.createElement('tr');
        tr.id = `db-row-${r}`;

        const rdTd = document.createElement('td');
        rdTd.className = 'db-round-cell';
        rdTd.textContent = r;
        tr.appendChild(rdTd);

        for (let t = 0; t < DB.numTeams; t++) {
            const td = buildEmptyCell(r, t);
            tr.appendChild(td);
        }
        body.appendChild(tr);
    }
}

function buildEmptyCell(round, teamIdx) {
    const pickNo   = slotToPickNo(round, teamIdx, DB.numTeams);
    const isUser   = teamIdx === DB.userSlot - 1;
    const td       = document.createElement('td');
    td.id          = `db-cell-${round}-${teamIdx}`;
    td.className   = `db-cell db-cell-empty${isUser ? ' db-user-cell' : ''}`;
    td.dataset.round   = round;
    td.dataset.team    = teamIdx;
    td.dataset.pick    = pickNo;
    const pickInRound  = pickNo - (round - 1) * DB.numTeams;
    td.innerHTML       = `<span class="db-pick-label">${round}.${String(pickInRound).padStart(2,'0')}</span>`;
    td.addEventListener('click', () => openPicker(round, teamIdx));
    return td;
}

function updateBoardCell(round, teamIdx, pickObj, animate) {
    const td = document.getElementById(`db-cell-${round}-${teamIdx}`);
    if (!td) return;

    const isUser = teamIdx === DB.userSlot - 1;
    td.className = `db-cell db-cell-filled${isUser ? ' db-user-cell' : ''}`;
    td.removeEventListener('click', openPicker);

    // Compute pick notation: round.pickWithinRound  (e.g. "2.01")
    const pickNo      = slotToPickNo(round, teamIdx, DB.numTeams);
    const pickInRound = pickNo - (round - 1) * DB.numTeams;
    const pickLabel   = `${round}.${String(pickInRound).padStart(2, '0')}`;

    td.innerHTML = `
        <div class="db-cell-inner">
            <span class="db-pick-label db-pick-label-filled">${pickLabel}</span>
            <div class="db-cell-player-row">
                ${badge(pickObj.position)}
                <a class="db-cell-name db-profile-link" href="${profileUrl(pickObj.name, pickObj.position, pickObj.nfl_team)}">${shortName(pickObj.name)}</a>
            </div>
            <span class="db-cell-nfl">${pickObj.nfl_team || ''}</span>
        </div>
    `;

    if (animate) {
        td.style.animation = 'none';
        td.style.background = 'rgba(212,175,55,0.18)';
        setTimeout(() => { td.style.background = ''; }, 800);
    }
}

// ── Available players list ────────────────────────────────────

function _isHistoricalSeason() {
    return DB.season && DB.season < new Date().getFullYear();
}

function renderLeftPanel() {
    const layout = document.querySelector('.db-layout');
    if (_isHistoricalSeason() && DB.standings && DB.standings.length > 0) {
        renderStandings();
        if (layout) layout.classList.add('db-standings-mode');
    } else {
        renderAvailablePlayers();
        if (layout) layout.classList.remove('db-standings-mode');
    }
    requestAnimationFrame(() => _autosizeBoardHeight());
}

function renderStandings() {
    const panel = document.getElementById('db-available-panel');
    if (!panel) return;

    // Update header
    const header = panel.querySelector('.db-panel-header');
    if (header) header.innerHTML = `${DB.season} Final Standings`;

    // Hide search and position tabs
    const searchWrap = panel.querySelector('.db-search-wrap');
    const posTabs = panel.querySelector('.db-pos-tabs');
    if (searchWrap) searchWrap.style.display = 'none';
    if (posTabs) posTabs.style.display = 'none';

    const list = document.getElementById('db-player-list');
    if (!list) return;
    list.innerHTML = '';

    DB.standings.forEach((team, i) => {
        const div = document.createElement('div');
        div.className = 'db-standings-row';
        const record = `${team.wins || 0}-${team.losses || 0}${team.ties ? '-' + team.ties : ''}`;
        const pts = team.pts_for ? parseFloat(team.pts_for).toFixed(1) : '';
        div.innerHTML = `
            <span class="db-standings-rank">${team.seed || team.rank || i + 1}</span>
            <span class="db-standings-divider"></span>
            <span class="db-standings-name">${team.name || 'Team ' + (i+1)}</span>
            <span class="db-standings-divider"></span>
            <span class="db-standings-record">${record}</span>
            <span class="db-standings-divider"></span>
            <span class="db-standings-pts">${pts} pts</span>
        `;
        list.appendChild(div);
    });
}

function renderAvailablePlayers() {
    // Restore player panel header and controls
    const panel = document.getElementById('db-available-panel');
    if (panel) {
        const header = panel.querySelector('.db-panel-header');
        if (header) {
            header.innerHTML = `Players <span class="db-avail-count" id="db-avail-count">—</span>
                <button class="db-avail-toggle" id="db-avail-toggle" title="Show available only">Available only</button>`;
            // Re-bind toggle
            document.getElementById('db-avail-toggle')?.addEventListener('click', function () {
                DB.showAvailOnly = !DB.showAvailOnly;
                this.classList.toggle('active', DB.showAvailOnly);
                renderAvailable();
            });
        }
        const searchWrap = panel.querySelector('.db-search-wrap');
        const posTabs = panel.querySelector('.db-pos-tabs');
        if (searchWrap) searchWrap.style.display = '';
        if (posTabs) posTabs.style.display = '';
    }
    renderAvailable();
}

function renderAvailable() {
    const list    = document.getElementById('db-player-list');
    const countEl = document.getElementById('db-avail-count');
    if (!list) return;

    const query    = DB.searchQuery.toLowerCase();
    const posF     = DB.posFilter;
    let   availCnt = 0;

    const rows = DB.players.map((p, idx) => {
        const name    = p.Name || '';
        const pos     = (p.Position || '').toUpperCase();
        const team    = p.Team || '';
        const byeWeek = p['Bye Week'];
        const drafted = DB.drafted.has(normalizeName(name));

        if (!drafted) availCnt++;

        // Available-only filter: skip drafted players entirely when toggle is on
        if (DB.showAvailOnly && drafted) return null;

        if (posF !== 'ALL' && pos !== posF) return null;
        if (query && !name.toLowerCase().includes(query)) return null;

        const div = document.createElement('div');
        div.className = `db-player-row${drafted ? ' db-player-drafted' : ''}`;
        div.dataset.idx = idx;
        const subParts = [];
        if (team) subParts.push(team);
        if (byeWeek) subParts.push(`Bye ${byeWeek}`);
        div.innerHTML = `
            <span class="db-player-rank">${p.Rank || idx + 1}</span>
            ${badge(pos)}
            <div class="db-player-main">
                <a class="db-player-name db-profile-link" href="${profileUrl(name, pos, team)}">${name}</a>
                <div class="db-player-sub">${subParts.join(' | ')}</div>
                ${buildPlayerUpdateMarkup(p.InjuryNews)}
            </div>
        `;
        if (!drafted) {
            // Non-name area click = pick action; name link navigates to profile
            div.addEventListener('click', e => {
                if (e.target.closest('.db-profile-link')) return; // let link navigate
                if (DB.source === 'manual') {
                    quickAssignPlayer(p);
                } else {
                    toggleManualCrossOff(p, div);
                }
            });
        }
        return div;
    }).filter(Boolean);

    list.innerHTML = '';
    rows.forEach(r => list.appendChild(r));
    if (countEl) countEl.textContent = availCnt;

    // Mirror into mobile drawer if available tab is active
    syncDrawerAvailable();
}

function toggleManualCrossOff(player, div) {
    // In Sleeper mode, let the user manually cross off a pick if Sleeper sync missed it
    const key = normalizeName(player.Name);
    if (DB.drafted.has(key)) {
        DB.drafted.delete(key);
        div.classList.remove('db-player-drafted');
    } else {
        DB.drafted.add(key);
        div.classList.add('db-player-drafted');
        scheduleSaveState();
    }
}

function quickAssignPlayer(player) {
    // Determine the next un-filled pick slot in draft order
    for (let p = DB.currentPickNo + 1; p <= DB.numTeams * DB.numRounds; p++) {
        const { round, teamIdx } = pickToSlot(p, DB.numTeams);
        if (!DB.board[round - 1][teamIdx]) {
            applyPick({
                name:      player.Name,
                position:  player.Position,
                nfl_team:  player.Team,
                round,
                teamIdx,
                pick_no:   p,
            }, true);
            return;
        }
    }
}

// ── Position filter & search ──────────────────────────────────

function initFilterTabs() {
    document.querySelectorAll('.db-pos-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.db-pos-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            DB.posFilter = btn.dataset.pos;
            renderAvailable();
        });
    });

    const search = document.getElementById('db-search');
    if (search) {
        search.addEventListener('input', () => {
            DB.searchQuery = search.value;
            renderAvailable();
        });
    }
}

// ── Your team roster panel ────────────────────────────────────

function renderRosterSlots() {
    const container = document.getElementById('db-roster-slots');
    if (!container) return;

    const slotOrder = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DST'];
    const benchN    = DB.rosterSlots.bench || 6;

    // Build slot definitions matching roster config
    const slotDefs = [];
    const addSlots = (pos, n) => { for (let i = 0; i < n; i++) slotDefs.push(pos); };
    addSlots('QB',   DB.rosterSlots.QB   || 1);
    addSlots('RB',   DB.rosterSlots.RB   || 2);
    addSlots('WR',   DB.rosterSlots.WR   || 2);
    addSlots('TE',   DB.rosterSlots.TE   || 1);
    addSlots('FLEX', DB.rosterSlots.FLEX || 1);
    addSlots('K',    DB.rosterSlots.K    || 1);
    addSlots('DST',  DB.rosterSlots.DST  || 1);
    addSlots('BN',   benchN);

    container.innerHTML = '';
    slotDefs.forEach((pos, i) => {
        const div = document.createElement('div');
        div.className = 'db-slot-row';
        div.id = `db-slot-row-${i}`;
        div.innerHTML = `
            <span class="db-slot-label">${pos}</span>
            <span class="db-slot-value" id="db-slot-val-${i}">—</span>
        `;
        container.appendChild(div);
    });
}

function renderRosterSections(container, rosterObj) {
    /**
     * Renders starters / bench / IR / taxi sections into `container` using
     * the structured rosterObj returned by the backend.
     * rosterObj = { starters:[{slot,player}], bench:[], reserve:[], taxi:[] }
     */
    container.innerHTML = '';

    function section(title, rows, emptyMsg) {
        if (!rows || rows.length === 0) return;
        const hdr = document.createElement('div');
        hdr.className = 'db-roster-section-hdr';
        hdr.textContent = title;
        container.appendChild(hdr);
        rows.forEach(row => container.appendChild(row));
    }

    function makeSlotRow(slotLabel, player) {
        const div = document.createElement('div');
        const fmtLabel = formatSlotLabel(slotLabel);
        div.className = 'db-slot-row';
        if (player) {
            div.innerHTML = `
                <span class="db-slot-label">${fmtLabel}</span>
                <span class="db-slot-value filled">${badge(player.position)} <a class="db-profile-link" href="${profileUrl(player.name, player.position, player.team)}">${player.name}</a></span>
            `;
        } else {
            div.innerHTML = `
                <span class="db-slot-label">${fmtLabel}</span>
                <span class="db-slot-value" style="color:var(--medium-gray);font-style:italic">Empty</span>
            `;
        }
        return div;
    }

    function makePlayerRow(player, slotLabel) {
        const div = document.createElement('div');
        div.className = 'db-slot-row';
        div.innerHTML = `
            <span class="db-slot-label">${slotLabel || badge(player.position)}</span>
            <span class="db-slot-value filled"><a class="db-profile-link" href="${profileUrl(player.name, player.position, player.team)}">${shortName(player.name)}</a></span>
            <span class="db-player-nfl" style="font-size:0.7em;color:var(--text-secondary);margin-left:4px">${player.team || ''}</span>
        `;
        return div;
    }

    // STARTERS
    const starterRows = (rosterObj.starters || []).map(s =>
        makeSlotRow(s.slot || '?', s.player)
    );
    section('STARTERS', starterRows);

    // BENCH
    const benchRows = (rosterObj.bench || []).map(p => makePlayerRow(p, 'BN'));
    section('BENCH', benchRows);

    // IR / RESERVE
    const irRows = (rosterObj.reserve || []).map(p => makePlayerRow(p, 'IR'));
    section('IR', irRows);

    // TAXI
    const taxiRows = (rosterObj.taxi || []).map(p => makePlayerRow(p, 'TAXI'));
    section('TAXI', taxiRows);

    if (container.children.length === 0) {
        container.innerHTML = '<div style="padding:10px;font-size:0.8em;color:var(--text-secondary)">No players yet.</div>';
    }
}

function renderYourTeam() {
    // If user's team tab is active in the bottom row, refresh it
    if (DB.activeOtTab === MY_TEAM_TAB || DB.activeOtTab === DB.userSlot - 1) renderOtherTeamBody(DB.userSlot - 1);
    syncDrawerYourTeam();
    const container = document.getElementById('db-roster-slots');
    if (!container) return;

    const userIdx  = DB.userSlot - 1;
    const fullData = DB.fullRosters && DB.fullRosters[userIdx];

    if (fullData) {
        // Use structured Sleeper sections
        renderRosterSections(container, fullData);
        syncDrawerYourTeam();
        return;
    }

    // Fallback: slot-based layout for in-progress manual / pre-roster-load drafts
    container.innerHTML = '';
    const slotDefs = [];
    const addSlots = (pos, n) => { for (let i = 0; i < n; i++) slotDefs.push(pos); };
    addSlots('QB',   DB.rosterSlots.QB   || 1);
    addSlots('RB',   DB.rosterSlots.RB   || 2);
    addSlots('WR',   DB.rosterSlots.WR   || 2);
    addSlots('TE',   DB.rosterSlots.TE   || 1);
    addSlots('FLEX', DB.rosterSlots.FLEX || 1);
    addSlots('K',    DB.rosterSlots.K    || 1);
    addSlots('DST',  DB.rosterSlots.DST  || 1);
    addSlots('BN',   DB.rosterSlots.bench || 6);

    const assigned  = new Array(slotDefs.length).fill(null);
    const remaining = [...DB.userRoster];

    slotDefs.forEach((slot, i) => {
        if (slot === 'BN') return;
        const pos = slot === 'FLEX' ? ['RB', 'WR', 'TE'] : [slot];
        const idx = remaining.findIndex(p => pos.includes((p.position || '').toUpperCase()));
        if (idx >= 0) assigned[i] = remaining.splice(idx, 1)[0];
    });
    slotDefs.forEach((slot, i) => {
        if (slot !== 'BN') return;
        if (remaining.length > 0) assigned[i] = remaining.shift();
    });

    // Re-render slot rows (they were created by renderRosterSlots initially,
    // but fullRosters mode rebuilds the container so we rebuild here too)
    slotDefs.forEach((slotLabel, i) => {
        const pick = assigned[i];
        const div = document.createElement('div');
        div.className = 'db-slot-row';
        div.id = `db-slot-row-${i}`;
        if (pick) {
            div.innerHTML = `
                <span class="db-slot-label">${slotLabel}</span>
                <span class="db-slot-value filled" id="db-slot-val-${i}">${badge(pick.position)} ${shortName(pick.name)}</span>
            `;
        } else {
            div.innerHTML = `
                <span class="db-slot-label">${slotLabel}</span>
                <span class="db-slot-value" id="db-slot-val-${i}">—</span>
            `;
        }
        container.appendChild(div);
    });

    syncDrawerYourTeam();
}

// ── Other teams panel ─────────────────────────────────────────

const MY_TEAM_TAB = -999; // sentinel for "My Team" tab

function renderOtherTeamTabs() {
    const tabs = document.getElementById('db-ot-tabs');
    if (!tabs) return;
    tabs.innerHTML = '';

    // Auto-select user's team by default
    const userIdx = DB.userSlot - 1;
    if (DB.activeOtTab === MY_TEAM_TAB || DB.activeOtTab < 0) {
        DB.activeOtTab = (userIdx >= 0 && userIdx < DB.teamNames.length) ? userIdx : 0;
    }

    // Show ALL teams in their natural order
    DB.teamNames.forEach((_, i) => {
        const btn = document.createElement('button');
        btn.className = `db-ot-tab${DB.activeOtTab === i ? ' active' : ''}`;
        btn.dataset.team = i;
        btn.textContent  = DB.teamNames[i] || `Team ${i + 1}`;
        btn.addEventListener('click', () => {
            document.querySelectorAll('.db-ot-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            DB.activeOtTab = i;
            renderOtherTeamBody(i);
            renderDraftCompleteAnalysis(i);
        });
        tabs.appendChild(btn);
    });

    // Scale tab font size so all tabs fit in one row
    const totalTabs = DB.teamNames.length;
    const tabScale  = totalTabs <= 10 ? 0.78 : totalTabs <= 12 ? 0.68 : totalTabs <= 14 ? 0.60 : 0.54;
    tabs.style.fontSize = tabScale + 'em';

    renderOtherTeamBody(DB.activeOtTab);
}

function renderTwoColRoster(container, fullData) {
    const wrap = document.createElement('div');
    wrap.className = 'db-ot-two-col';

    const leftCol  = document.createElement('div');
    const rightCol = document.createElement('div');
    leftCol.className  = 'db-ot-col';
    rightCol.className = 'db-ot-col';

    function hdr(text) {
        const d = document.createElement('div');
        d.className = 'db-roster-section-hdr';
        d.textContent = text;
        return d;
    }
    function makeSlotRow(slotLabel, player) {
        const div = document.createElement('div');
        div.className = 'db-slot-row';
        const fmtLabel = formatSlotLabel(slotLabel);
        if (player) {
            div.innerHTML = `<span class="db-slot-label">${fmtLabel}</span><span class="db-slot-value filled">${badge(player.position)} <a class="db-profile-link" href="${profileUrl(player.name, player.position, player.team)}">${shortName(player.name)}</a></span>`;
        } else {
            div.innerHTML = `<span class="db-slot-label">${fmtLabel}</span><span class="db-slot-value" style="color:var(--medium-gray);font-style:italic">Empty</span>`;
        }
        return div;
    }
    function makePlayerRow(player, slotLabel) {
        const div = document.createElement('div');
        div.className = 'db-slot-row';
        div.innerHTML = `<span class="db-slot-label">${slotLabel}</span><span class="db-slot-value filled">${badge(player.position)} <a class="db-profile-link" href="${profileUrl(player.name, player.position, player.team)}">${shortName(player.name)}</a></span>`;
        return div;
    }

    if ((fullData.starters || []).length > 0) {
        leftCol.appendChild(hdr('STARTERS'));
        fullData.starters.forEach(s => leftCol.appendChild(makeSlotRow(s.slot || '?', s.player)));
    }

    const hasBench = (fullData.bench   || []).length > 0;
    const hasIR    = (fullData.reserve || []).length > 0;
    const hasTaxi  = (fullData.taxi    || []).length > 0;
    if (hasBench) { rightCol.appendChild(hdr('BENCH')); fullData.bench.forEach(p => rightCol.appendChild(makePlayerRow(p, 'BN'))); }
    if (hasIR)    { rightCol.appendChild(hdr('IR'));    fullData.reserve.forEach(p => rightCol.appendChild(makePlayerRow(p, 'IR'))); }
    if (hasTaxi)  { rightCol.appendChild(hdr('TAXI')); fullData.taxi.forEach(p => rightCol.appendChild(makePlayerRow(p, 'TAXI'))); }
    if (!hasBench && !hasIR && !hasTaxi) {
        rightCol.innerHTML = '<div style="padding:10px;font-size:0.8em;color:var(--text-secondary)">No bench.</div>';
    }

    wrap.appendChild(leftCol);
    wrap.appendChild(rightCol);
    container.appendChild(wrap);

    // Cap right col height to match left col so the panel ends at the last starter row
    requestAnimationFrame(() => {
        const h = leftCol.offsetHeight;
        if (h > 0) rightCol.style.maxHeight = h + 'px';
    });
}

function renderOtherTeamBody(teamIdx) {
    const body = document.getElementById('db-ot-body');
    if (!body) return;
    body.innerHTML = '';

    // My Team tab — render user's roster using the same two-column layout
    if (teamIdx === MY_TEAM_TAB || teamIdx === DB.userSlot - 1) {
        renderTwoColRoster(body, buildRosterData(DB.userSlot - 1));
        return;
    }

    const fullData = buildRosterData(teamIdx);
    if ((fullData.starters || []).length > 0 || (fullData.bench || []).length > 0) {
        renderTwoColRoster(body, fullData);
        return;
    }

    // Fallback: flat pick list for in-progress drafts without roster data
    const picks = DB.otherRosters[teamIdx] || [];
    if (picks.length === 0) {
        body.innerHTML = '<span style="font-size:0.8em;color:var(--text-secondary);padding:8px">No picks yet.</span>';
        return;
    }

    picks.forEach(p => {
        const div = document.createElement('div');
        div.className = 'db-ot-pick';
        div.innerHTML = `${badge(p.position)} <span style="font-size:0.82em;color:var(--white)">${shortName(p.name)}</span>`;
        body.appendChild(div);
    });
}

// ── Current pick indicator ────────────────────────────────────

function updateCurrentPickBar() {
    const bar = document.getElementById('db-current-pick-bar');
    if (!bar) return;

    // Draft explicitly marked complete by Sleeper
    if (DB.draftComplete) {
        bar.textContent = '✓ Draft complete';
        bar.style.color = 'var(--text-secondary)';
        bar.classList.add('visible');
        return;
    }

    const nextPick = DB.currentPickNo + 1;
    if (nextPick > DB.numTeams * DB.numRounds) {
        bar.textContent = '✓ Draft complete';
        bar.style.color = 'var(--text-secondary)';
        bar.classList.add('visible');
        DB.draftComplete = true;
        return;
    }

    const { round, teamIdx } = pickToSlot(nextPick, DB.numTeams);
    const teamName  = DB.teamNames[teamIdx] || `Team ${teamIdx + 1}`;
    const isUser    = teamIdx === DB.userSlot - 1;
    const pickInRnd = nextPick - (round - 1) * DB.numTeams;

    bar.textContent = isUser
        ? `⭐ YOUR PICK — Round ${round}, Pick ${round}.${String(pickInRnd).padStart(2,'0')}`
        : `On the clock: ${teamName} — Round ${round}, Pick ${round}.${String(pickInRnd).padStart(2,'0')}`;
    bar.classList.add('visible');
    bar.style.color = isUser ? 'var(--gold)' : 'var(--text-secondary)';

    const row = document.getElementById(`db-row-${round}`);
    if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ── Player picker modal ───────────────────────────────────────

let _pickerPendingRound   = null;
let _pickerPendingTeamIdx = null;
let _pickerSelectedPlayer = null;

function openPicker(round, teamIdx) {
    // Don't open picker for already-filled cells
    if (DB.board[round - 1][teamIdx]) return;

    _pickerPendingRound   = round;
    _pickerPendingTeamIdx = teamIdx;
    _pickerSelectedPlayer = null;

    const title = document.getElementById('db-picker-title');
    const pickNo = slotToPickNo(round, teamIdx, DB.numTeams);
    const pickInRnd = pickNo - (round - 1) * DB.numTeams;
    const teamName = DB.teamNames[teamIdx] || `Team ${teamIdx + 1}`;
    title.textContent = `Pick ${round}.${String(pickInRnd).padStart(2,'0')} — ${teamName}`;

    // Populate team select
    const sel = document.getElementById('db-picker-team-select');
    sel.innerHTML = '';
    DB.teamNames.forEach((name, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = name + (i === DB.userSlot - 1 ? ' (You)' : '');
        if (i === teamIdx) opt.selected = true;
        sel.appendChild(opt);
    });

    // Populate picker list
    renderPickerList('');

    document.getElementById('db-picker-search').value = '';
    document.getElementById('db-picker-overlay').style.display = '';
    document.getElementById('db-picker-search').focus();
}

function renderPickerList(query) {
    const list = document.getElementById('db-picker-list');
    list.innerHTML = '';
    const q = query.toLowerCase();

    DB.players.forEach(p => {
        const name    = p.Name || '';
        const pos     = (p.Position || '').toUpperCase();
        if (DB.drafted.has(normalizeName(name))) return;
        if (q && !name.toLowerCase().includes(q)) return;

        const row = document.createElement('div');
        row.className = 'db-picker-row';
        row.innerHTML = `
            <span class="db-picker-rank">${p.Rank || ''}</span>
            ${badge(pos)}
            <span class="db-picker-name">${name}</span>
            <span class="db-picker-nfl">${p.Team || ''}</span>
        `;
        row.addEventListener('click', () => {
            _pickerSelectedPlayer = p;
            document.querySelectorAll('.db-picker-row').forEach(r => r.style.background = '');
            row.style.background = 'rgba(212,175,55,0.15)';
        });
        list.appendChild(row);
    });
}

function closePicker() {
    document.getElementById('db-picker-overlay').style.display = 'none';
    _pickerPendingRound   = null;
    _pickerPendingTeamIdx = null;
    _pickerSelectedPlayer = null;
}

function confirmPick() {
    if (!_pickerSelectedPlayer) return;
    const teamIdx = parseInt(document.getElementById('db-picker-team-select').value, 10);
    const round   = _pickerPendingRound;
    if (round == null || teamIdx == null || isNaN(teamIdx)) return;

    applyPick({
        name:     _pickerSelectedPlayer.Name,
        position: _pickerSelectedPlayer.Position,
        nfl_team: _pickerSelectedPlayer.Team,
        round,
        teamIdx,
        pick_no:  slotToPickNo(round, teamIdx, DB.numTeams),
    }, true);

    closePicker();
}

// ── Sleeper live polling ──────────────────────────────────────

const POLL_INTERVAL_MS = 30000;   // 30 seconds
let   _countdownTimer  = null;
let   _secondsLeft     = 0;

function startPolling() {
    if (DB.syncInterval) clearInterval(DB.syncInterval);
    if (_countdownTimer)  clearInterval(_countdownTimer);

    syncFromSleeper();   // immediate first fetch
    DB.syncInterval = setInterval(syncFromSleeper, POLL_INTERVAL_MS);
    _startCountdown();
}

function stopPolling() {
    clearInterval(DB.syncInterval);
    clearInterval(_countdownTimer);
    DB.syncInterval = null;
    _countdownTimer  = null;
}

function _startCountdown() {
    _secondsLeft = POLL_INTERVAL_MS / 1000;
    clearInterval(_countdownTimer);
    _countdownTimer = setInterval(() => {
        _secondsLeft--;
        if (_secondsLeft <= 0) {
            _secondsLeft = POLL_INTERVAL_MS / 1000;
        }
        // Update label if currently live
        if (DB.syncErrorCount === 0 && DB.lastSyncAt) {
            const lbl = document.getElementById('db-sync-label');
            if (lbl) lbl.textContent = `Live · next sync in ${_secondsLeft}s`;
        }
    }, 1000);
}

async function syncFromSleeper() {
    if (!DB.draftId || !DB.leagueId) return;
    try {
        const url = `/draft-board/sleeper/sync?draft_id=${DB.draftId}&league_id=${DB.leagueId}`;
        const res  = await fetch(url);
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'sync error');

        DB.syncErrorCount = 0;
        DB.lastSyncAt     = new Date();
        _secondsLeft      = POLL_INTERVAL_MS / 1000;

        // ── Apply roster changes first ──────────────────────────
        if (data.team_rosters) {
            DB.fullRosters = data.team_rosters;

            // Rebuild drafted set.
            // Primary: flat list of Sleeper-resolved player names (handles suffix mismatches).
            // Fallback: names from structured roster objects.
            DB.drafted = new Set();
            if (data.roster_player_names && data.roster_player_names.length) {
                data.roster_player_names.forEach(n => DB.drafted.add(normalizeName(n)));
            } else {
                DB.fullRosters.forEach(roster => {
                    if (!roster) return;
                    const all = [
                        ...(roster.starters || []).map(s => s.player).filter(Boolean),
                        ...(roster.bench    || []),
                        ...(roster.reserve  || []),
                        ...(roster.taxi     || []),
                    ];
                    all.forEach(p => { if (p && p.name) DB.drafted.add(normalizeName(p.name)); });
                });
            }

            renderYourTeam();
            if (DB.activeOtTab >= 0) renderOtherTeamBody(DB.activeOtTab);
            renderAvailable();
        }

        // ── Apply new draft picks ───────────────────────────────
        const newPicks = (data.picks || []).filter(p => {
            if (!p.name || !p.pick_no) return false;
            const { round, teamIdx } = pickToSlot(p.pick_no, DB.numTeams);
            if (round < 1 || round > DB.numRounds) return false;
            return !DB.board[round - 1]?.[teamIdx];
        });

        for (const pick of newPicks) {
            applyPick(pick, true);
        }

        // ── Draft complete? ─────────────────────────────────────
        if (data.draft_status === 'complete' || DB.currentPickNo >= DB.numTeams * DB.numRounds) {
            stopPolling();
            DB.draftComplete = true;
            setSyncStatus('paused', 'Draft complete');
            updateCurrentPickBar();
            renderDraftCompleteAnalysis();
        } else {
            setSyncStatus('live', `Live · next sync in ${_secondsLeft}s`);
        }

        scheduleSaveState();

    } catch (e) {
        DB.syncErrorCount++;
        const msg = DB.syncErrorCount >= 3 ? '⚠ Sync paused — retrying' : `Retrying… (${DB.syncErrorCount})`;
        setSyncStatus(DB.syncErrorCount >= 3 ? 'error' : 'paused', msg);
    }
}

function setSyncStatus(state, label) {
    const dot = document.getElementById('db-sync-dot');
    const lbl = document.getElementById('db-sync-label');
    if (dot) dot.className = `db-sync-dot ${state}`;
    if (lbl) lbl.textContent = label;
}

function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ── AI suggestions ────────────────────────────────────────────

async function fetchAISuggestions() {
    if (DB.draftComplete) {
        await renderDraftCompleteAnalysis();
        return;
    }

    const available = DB.players
        .filter(p => !DB.drafted.has(normalizeName(p.Name || '')))
        .slice(0, 80);

    const otherTeams = Object.entries(DB.otherRosters)
        .filter(([i]) => parseInt(i) !== DB.userSlot - 1)
        .map(([, picks]) => ({ picks }));

    const payload = {
        user_roster:      DB.userRoster.map(p => ({ name: p.name, position: p.position })),
        roster_slots:     DB.rosterSlots,
        available_players: available,
        other_teams:      otherTeams,
        pick_number:      DB.currentPickNo,
        picks_until_next: picksUntilUser(),
        num_teams:        DB.numTeams,
    };

    try {
        const res  = await fetch('/draft-board/ai-suggest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.ok) renderAISuggestions(data);
    } catch {}
}

// Returns the same {starters, bench, reserve, taxi} object the roster panel renders,
// so the analysis always sees exactly the players shown in the STARTERS section.
const _FLEX_POSITIONS = {
    FLEX:       ['RB', 'WR', 'TE'],
    SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'],
    REC_FLEX:   ['WR', 'TE'],
    WRRB_FLEX:  ['WR', 'RB'],
    IDP_FLEX:   ['QB', 'RB', 'WR', 'TE'],
};

function buildRosterData(actualIdx) {
    // Sleeper / structured mode — use slot assignments IF the lineup has been set.
    // Sleeper often has empty starters[] during/after a draft (owners haven't set lineups yet).
    // Only trust fullRosters if at least one starter slot is actually filled.
    const fullData = DB.fullRosters && DB.fullRosters[actualIdx];
    if (fullData && (fullData.starters || []).some(s => s && s.player && s.player.name)) {
        return fullData;
    }

    // Slot-based inference: replicate the same greedy assignment renderYourTeam uses.
    // Player pool: use fullData.bench (all Sleeper picks) if available, otherwise draft board picks.
    const fallbackPicks = fullData
        ? [...(fullData.bench || []), ...(fullData.reserve || []), ...(fullData.taxi || [])]
              .filter(p => p && p.name)
              .map(p => ({ name: p.name, position: p.position, nfl_team: p.team }))
        : (actualIdx === DB.userSlot - 1 ? DB.userRoster : (DB.otherRosters[actualIdx] || []));
    const rawPicks = fallbackPicks;

    const slots    = DB.rosterSlots || {};
    const slotDefs = [];
    const addSlots = (label, n) => { for (let i = 0; i < n; i++) slotDefs.push(label); };

    // Build slot list in the same order renderYourTeam does
    addSlots('QB',         parseInt(slots.QB         || 0));
    addSlots('RB',         parseInt(slots.RB         || 0));
    addSlots('WR',         parseInt(slots.WR         || 0));
    addSlots('TE',         parseInt(slots.TE         || 0));
    addSlots('FLEX',       parseInt(slots.FLEX        || 0));
    addSlots('SUPER_FLEX', parseInt(slots.SUPER_FLEX  || 0));
    addSlots('REC_FLEX',   parseInt(slots.REC_FLEX    || 0));
    addSlots('WRRB_FLEX',  parseInt(slots.WRRB_FLEX   || 0));
    addSlots('K',          parseInt(slots.K           || 0));
    addSlots('DST',        parseInt(slots.DST         || 0));
    addSlots('BN',         parseInt(slots.bench       || 6));

    const assigned  = new Array(slotDefs.length).fill(null);
    const remaining = [...rawPicks];

    // Fill non-bench slots first (same greedy first-match as renderYourTeam)
    slotDefs.forEach((slot, i) => {
        if (slot === 'BN') return;
        const positions = _FLEX_POSITIONS[slot] || [slot];
        const idx = remaining.findIndex(p => positions.includes((p.position || '').toUpperCase()));
        if (idx >= 0) assigned[i] = remaining.splice(idx, 1)[0];
    });
    // Fill bench with leftovers
    slotDefs.forEach((slot, i) => {
        if (slot !== 'BN') return;
        if (remaining.length > 0) assigned[i] = remaining.shift();
    });

    const starters = [];
    const bench    = [];
    slotDefs.forEach((slot, i) => {
        const pick = assigned[i];
        if (!pick) return;
        const playerObj = { name: pick.name, position: pick.position, team: pick.nfl_team };
        if (slot === 'BN') bench.push(playerObj);
        else starters.push({ slot, player: playerObj });
    });

    return { starters, bench, reserve: [], taxi: [] };
}

async function renderDraftCompleteAnalysis(forTeamTab) {
    // Default to whichever tab is currently active
    if (forTeamTab === undefined) forTeamTab = DB.activeOtTab;
    if (!DB._analysisCache) DB._analysisCache = {};

    // Return cached result immediately
    if (DB._analysisCache[forTeamTab]) {
        _showCompleteAnalysis(DB._analysisCache[forTeamTab]);
        return;
    }

    // Show loading state
    ['db-ai-need-section', 'db-ai-targets-section', 'db-ai-bav-section'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    const placeholder = document.getElementById('db-ai-placeholder');
    if (placeholder) {
        placeholder.style.display = '';
        placeholder.textContent = 'Analyzing roster…';
    }
    const alertsEl = document.getElementById('db-ai-alerts');
    if (alertsEl) alertsEl.innerHTML = '';

    const isMyTeam  = (forTeamTab === MY_TEAM_TAB || forTeamTab === DB.userSlot - 1);
    const actualIdx = isMyTeam ? DB.userSlot - 1 : forTeamTab;
    const teamLabel = isMyTeam ? 'you' : (DB.teamNames[forTeamTab] || `Team ${forTeamTab + 1}`);

    // Use the exact same roster data the panel renders — starters shown on screen
    const rosterData = buildRosterData(actualIdx);

    // Build a rank lookup to enrich players with rank for quality grading
    const rankLookup = {};
    (DB.players || []).forEach(p => {
        if (p.Name) rankLookup[normalizeName(p.Name)] = { rank: p.Rank, adp: p.ADP };
    });
    function enrichPlayer(p) {
        if (!p || !p.name) return p;
        const info = rankLookup[normalizeName(p.name)] || {};
        return { ...p, rank: info.rank, adp: info.adp };
    }

    const actualStarters = (rosterData.starters || [])
        .filter(s => s && s.player && s.player.name)
        .map(s => enrichPlayer(s.player));
    const benchPlayers = [
        ...(rosterData.bench   || []),
        ...(rosterData.reserve || []),
        ...(rosterData.taxi    || []),
    ].filter(p => p && p.name).map(enrichPlayer);

    const enrichedRoster = { starters: actualStarters, bench: benchPlayers };

    try {
        const res  = await fetch('/draft-board/ai-suggest', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                mode:                'complete',
                roster:              enrichedRoster,
                team_label:          teamLabel,
                league_type:         DB.leagueType,
                scoring:             DB.scoringFormat,
                roster_slots:        DB.rosterSlots,
                starter_slot_labels: DB.starterSlotLabels,
            }),
        });
        const data = await res.json();
        if (!res.ok || data.mode !== 'complete') throw new Error('bad response');
        if (data.empty) {
            if (placeholder) { placeholder.style.display = ''; placeholder.textContent = 'No picks recorded for this team yet.'; }
            return; // don't cache — re-check next click
        }
        data._teamLabel = teamLabel; // stash for header display
        DB._analysisCache[forTeamTab] = data;
        _showCompleteAnalysis(data);
    } catch {
        if (placeholder) { placeholder.style.display = ''; placeholder.textContent = 'Could not load analysis.'; }
    }
}

function _showCompleteAnalysis(data) {
    const placeholder = document.getElementById('db-ai-placeholder');
    if (placeholder) placeholder.style.display = 'none';

    const alertsEl = document.getElementById('db-ai-alerts');
    if (!alertsEl) return;
    alertsEl.innerHTML = '';

    const gradeColor = { A: '#50c878', 'A-': '#50c878', 'B+': '#8fbc44', B: '#8fbc44', 'B-': '#c9a227',
                         'C+': '#c9a227', C: '#e07b39', D: '#e15759', F: '#e15759' };

    // ── Header bar ───────────────────────────────────────────────
    const header = document.createElement('div');
    header.className = 'db-analysis-header';
    const ov        = data.overall_grade || 'B';
    const teamLabel = data._teamLabel || 'you';
    const headerTitle = teamLabel === 'you' ? 'Roster Analysis' : `${teamLabel} — Analysis`;
    header.innerHTML = `
        <span class="db-ai-label" style="margin:0">${headerTitle}</span>
        <span class="db-overall-grade" style="color:${gradeColor[ov] || '#d4af37'}">${ov}</span>
        ${data.strengths?.length ? `<span class="db-analysis-tag strength">✓ ${data.strengths.join(', ')}</span>` : ''}
        ${data.needs?.length    ? `<span class="db-analysis-tag need">↑ Need ${data.needs.join(', ')}</span>` : ''}
    `;
    alertsEl.appendChild(header);

    // ── Position group cards ─────────────────────────────────────
    const grid = document.createElement('div');
    grid.className = 'db-pos-group-grid';
    grid.id = 'db-analysis-wrap';

    (data.position_groups || []).forEach(group => {
        const g    = group.grade || 'C';
        const col  = gradeColor[g] || '#888';
        const card = document.createElement('div');
        card.className = 'db-pos-group-card';
        card.style.borderTopColor = col;

        const playerLinks = (group.players || []).map(p =>
            p.name ? `<a class="db-profile-link db-analysis-player" href="${profileUrl(p.name, group.position, p.team)}">${shortName(p.name)}</a>` : ''
        ).filter(Boolean).join('<span class="db-analysis-sep">·</span>');

        card.innerHTML = `
            <div class="db-pos-group-top">
                <span class="db-pos-group-label">${group.position}</span>
                <span class="db-pos-group-grade" style="color:${col}">${g}</span>
                <span class="db-pos-group-count">${group.count}</span>
            </div>
            <div class="db-pos-group-note">${group.note}</div>
            ${playerLinks ? `<div class="db-pos-group-players">${playerLinks}</div>` : ''}
        `;
        grid.appendChild(card);
    });

    alertsEl.appendChild(grid);

    // ── Trade suggestions ─────────────────────────────────────
    if (data.trade_suggestions?.length) {
        const tradeWrap = document.createElement('div');
        tradeWrap.className = 'db-trade-suggestions';
        tradeWrap.innerHTML = `<span class="db-ai-label" style="margin:0;display:block;margin-bottom:6px">Trade Radar</span>` +
            data.trade_suggestions.map(s =>
                `<div class="db-trade-tip">⇄ ${s}</div>`
            ).join('');
        alertsEl.appendChild(tradeWrap);
    }
}

function renderAISuggestions(data) {
    const placeholder = document.getElementById('db-ai-placeholder');
    if (placeholder) placeholder.style.display = 'none';

    // Needs
    const needSection = document.getElementById('db-ai-need-section');
    const needsEl     = document.getElementById('db-ai-needs');
    if (needsEl && data.needs?.length) {
        needsEl.innerHTML = '';
        needSection.style.display = '';
        data.needs.forEach(n => {
            const urgency = n.score > 0.6 ? 'urgent' : n.score > 0.25 ? 'medium' : 'low';
            const pill = document.createElement('div');
            pill.className = `db-need-pill ${urgency}`;
            pill.innerHTML = `
                <span style="font-size:0.76em;color:var(--white)">${n.position}</span>
                <div class="db-need-bar-wrap">
                    <div class="db-need-bar-fill" style="width:${Math.round(n.score * 100)}%"></div>
                </div>
            `;
            needsEl.appendChild(pill);
        });
    }

    // Top targets
    const targetsSection = document.getElementById('db-ai-targets-section');
    const targetsEl      = document.getElementById('db-ai-targets');
    if (targetsEl && data.targets?.length) {
        targetsEl.innerHTML = '';
        targetsSection.style.display = '';
        data.targets.forEach(p => {
            const chip = document.createElement('div');
            chip.className = 'db-target-chip';
            chip.innerHTML = `${badge(p.Position)} <span>${shortName(p.Name)}</span>`;
            targetsEl.appendChild(chip);
        });
    }

    // Best available
    const bavSection = document.getElementById('db-ai-bav-section');
    const bavEl      = document.getElementById('db-ai-bav');
    if (bavEl && data.best_available?.length) {
        bavEl.innerHTML = '';
        bavSection.style.display = '';
        data.best_available.forEach(p => {
            const chip = document.createElement('div');
            chip.className = 'db-target-chip';
            chip.innerHTML = `${badge(p.Position)} <span>${shortName(p.Name)}</span>`;
            bavEl.appendChild(chip);
        });
    }

    // Alerts
    const alertsEl = document.getElementById('db-ai-alerts');
    if (alertsEl) {
        alertsEl.innerHTML = '';
        (data.alerts || []).forEach(a => {
            const pill = document.createElement('div');
            pill.className = `db-alert-pill ${a.urgency || 'medium'}`;
            const teamText = a.teams_needing >= 2 ? ` · ${a.teams_needing} teams need ${a.position}` : '';
            pill.textContent = `⚠ ${a.name} (ADP ${a.adp})${teamText}`;
            alertsEl.appendChild(pill);
        });
    }
}

// ── Session save / load ───────────────────────────────────────

function scheduleSaveState() {
    clearTimeout(DB.saveDebounce);
    DB.saveDebounce = setTimeout(saveState, 2000);
}

async function saveState() {
    const settings = {
        source:        DB.source,
        leagueId:      DB.leagueId,
        draftId:       DB.draftId,
        leagueName:    DB.leagueName,
        numTeams:      DB.numTeams,
        numRounds:     DB.numRounds,
        userSlot:      DB.userSlot,
        teamNames:     DB.teamNames,
        scoringFormat: DB.scoringFormat,
        rosterSlots:   DB.rosterSlots,
        sleeperUserId: DB.sleeperUserId,
        draftComplete:      DB.draftComplete,
        leagueType:         DB.leagueType,
        fullRosters:        DB.fullRosters,
        starterSlotLabels:  DB.starterSlotLabels,
    };

    // Convert board to serialisable form
    const boardFlat = DB.board.map(row => row.map(cell => cell || null));

    const state = {
        board:          boardFlat,
        drafted:        Array.from(DB.drafted),
        userRoster:     DB.userRoster,
        otherRosters:   DB.otherRosters,
        currentPickNo:  DB.currentPickNo,
    };

    try {
        await fetch('/draft-board/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source:    DB.source,
                league_id: DB.leagueId,
                draft_id:  DB.draftId,
                settings,
                state,
                last_pick: DB.currentPickNo,
            }),
        });
    } catch {}
}

async function loadSavedSession() {
    try {
        const res  = await fetch('/draft-board/load');
        const data = await res.json();
        if (!data.found) return false;

        const cfg      = data.settings || {};
        const st       = data.state    || {};

        // Restore settings
        DB.source        = data.source        || 'manual';
        DB.leagueId      = data.league_id;
        DB.draftId       = data.draft_id;
        DB.leagueName    = cfg.leagueName     || 'Draft Board';
        DB.numTeams      = cfg.numTeams       || 12;
        DB.numRounds     = cfg.numRounds      || 15;
        DB.userSlot      = cfg.userSlot       || 1;
        DB.teamNames     = cfg.teamNames      || [];
        DB.scoringFormat = cfg.scoringFormat  || 'ppr';
        DB.rosterSlots   = cfg.rosterSlots    || { QB:1, RB:2, WR:2, TE:1, FLEX:1, K:1, DST:1, bench:6 };
        DB.sleeperUserId = cfg.sleeperUserId  || null;
        DB.draftComplete      = cfg.draftComplete      || false;
        DB.leagueType         = cfg.leagueType         || 'redraft';
        DB.fullRosters        = cfg.fullRosters        || null;
        DB.starterSlotLabels  = cfg.starterSlotLabels  || [];

        // Restore state
        DB.board         = (st.board || []).map(row => row.map(c => c || null));
        DB.drafted       = new Set(st.drafted || []);
        DB.userRoster    = st.userRoster    || [];
        DB.otherRosters  = st.otherRosters  || {};
        DB.currentPickNo = st.currentPickNo || 0;

        // Pad board if necessary
        while (DB.board.length < DB.numRounds)
            DB.board.push(Array(DB.numTeams).fill(null));

        for (let r = 0; r < DB.board.length; r++) {
            while (DB.board[r].length < DB.numTeams) DB.board[r].push(null);
        }

        return true;
    } catch {
        return false;
    }
}

async function resumeSession() {
    // Show board UI
    document.getElementById('db-setup-wrap').style.display  = 'none';
    document.getElementById('db-topbar').style.display      = '';
    const activeEl2 = document.getElementById('db-active');
    activeEl2.style.display = '';
    activeEl2.style.height = '';  // Clear any previous drag-resize height
    document.getElementById('db-bottom-drawer').style.display       = '';
    _syncPanelTop();
    requestAnimationFrame(() => { _autosizeBoardHeight(); _alignPanelHeader(); });
    document.getElementById('db-league-name').textContent    = DB.leagueName;
    document.getElementById('db-topbar-meta').textContent   =
        `${DB.numTeams} teams · ${DB.scoringFormat.toUpperCase()} · ${DB.numRounds} rounds`;

    if (DB.source === 'sleeper' || DB.source === 'espn') {
        document.getElementById('db-sync-badge').style.display   = '';
        document.getElementById('db-sync-now-btn').style.display = '';
    }

    renderBoard();
    renderRosterSlots();
    renderOtherTeamTabs();

    // Re-fill board DOM from saved state
    for (let r = 0; r < DB.numRounds; r++) {
        for (let t = 0; t < DB.numTeams; t++) {
            const pick = DB.board[r][t];
            if (pick) updateBoardCell(r + 1, t, pick, false);
        }
    }

    DB.players = await fetchPlayers(DB.scoringFormat);
    renderLeftPanel();
    renderYourTeam();
    updateCurrentPickBar();

    // If Sleeper: re-sync only if draft is still in progress
    if (DB.source === 'sleeper' && DB.draftId && !DB.draftComplete) {
        setSyncStatus('live', 'Syncing…');
        await syncFromSleeper();
        startPolling();
    } else if (DB.draftComplete) {
        setSyncStatus('paused', 'Draft complete');
        renderDraftCompleteAnalysis();
    }

    if (window.innerWidth <= 768) {
        document.getElementById('db-mobile-fab').style.display = 'flex';
    }
}

// ── Reset ─────────────────────────────────────────────────────

async function resetBoard() {
    stopPolling();
    try {
        await fetch('/draft-board/reset', { method: 'POST' });
    } catch {}

    // Reset all state
    Object.assign(DB, {
        source: 'manual', leagueId: null, draftId: null, leagueName: 'Draft Board',
        numTeams: 12, numRounds: 15, userSlot: 1, teamNames: [], scoringFormat: 'ppr',
        rosterSlots: { QB:1, RB:2, WR:2, TE:1, FLEX:1, K:1, DST:1, bench:6 },
        players: [], drafted: new Set(), board: [], userRoster: [],
        otherRosters: {}, currentPickNo: 0, activeOtTab: -1,
    });

    document.getElementById('db-topbar').style.display             = 'none';
    document.getElementById('db-active').style.display             = 'none';
    document.getElementById('db-active').style.height              = '';
    document.getElementById('db-bottom-drawer').style.display      = 'none';
    document.getElementById('db-setup-wrap').style.display         = '';
    document.getElementById('db-current-pick-bar').classList.remove('visible');
    document.getElementById('db-sync-badge').style.display  = 'none';
    document.getElementById('db-sync-now-btn').style.display = 'none';
    document.getElementById('db-mobile-fab').style.display   = 'none';
    document.getElementById('db-drawer').classList.remove('open');

    // Clear inline styles left by _autosizeBoardHeight so next open starts fresh
    const panel = document.getElementById('db-available-panel');
    const playerList = document.getElementById('db-player-list');
    const boardScroll = document.getElementById('db-board-scroll');
    const layout = document.querySelector('.db-layout');
    if (panel) { panel.style.height = ''; panel.style.maxHeight = ''; }
    if (playerList) { playerList.style.overflow = ''; playerList.style.flex = ''; }
    if (boardScroll) { boardScroll.style.height = ''; boardScroll.style.overflowY = ''; }
    if (layout) { layout.style.height = ''; }

    // Reload saved leagues so "My Leagues" section is visible
    const savedLeagues = await loadSavedLeagues();
    renderSavedLeagues(savedLeagues);

    // Scroll to top so user isn't stranded mid-page
    window.scrollTo(0, 0);
}

// ── Season history selector ──────────────────────────────────

function buildSeasonSelector(currentYear) {
    const sel = document.getElementById('db-season-select');
    if (!sel) return;
    sel.innerHTML = '';

    // Build options from current year down to the league's first season
    const now = new Date().getFullYear();
    const startYear = Math.max(currentYear, now);
    const endYear = (DB.leagueStartYear && DB.leagueStartYear <= startYear) ? DB.leagueStartYear : (startYear - 2);
    for (let y = startYear; y >= endYear; y--) {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        if (y === DB.season) opt.selected = true;
        sel.appendChild(opt);
    }

    // Remove old listener and add new one
    sel.onchange = () => switchSeason(parseInt(sel.value, 10));
}

async function switchSeason(year) {
    if (year === DB.season) return;

    stopPolling();
    const sel = document.getElementById('db-season-select');
    if (sel) sel.disabled = true;

    try {
        let connectUrl, connectBody;

        if (DB.source === 'espn') {
            connectUrl = '/draft-board/espn/connect';
            connectBody = { league_id: DB.leagueId, year };
            if (DB.espnUserTeamId) connectBody.user_team_id = DB.espnUserTeamId;
            if (DB.espnCookies) {
                connectBody.espn_s2 = DB.espnCookies.espn_s2;
                connectBody.swid    = DB.espnCookies.swid;
            }
        } else if (DB.source === 'sleeper') {
            const targetLeagueId = await _resolveSleeperLeagueId(DB.leagueId, DB.season, year);
            if (!targetLeagueId) {
                trimSeasonSelector(year);
                showSeasonError(`No league history found for ${year}`);
                return;
            }
            connectUrl = '/draft-board/sleeper/connect';
            connectBody = { league_id: targetLeagueId, sleeper_user_id: DB.sleeperUserId };
        } else {
            return;
        }

        const res = await fetch(connectUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(connectBody),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            if (res.status === 404) {
                trimSeasonSelector(year);
            }
            showSeasonError(data.error || `Could not load ${year} season`);
            return;
        }

        await initBoard({
            source:             DB.source,
            leagueId:           DB.source === 'espn' ? DB.leagueId : connectBody.league_id,
            draftId:            data.draft_id,
            leagueName:         data.league_name,
            numTeams:           data.num_teams,
            numRounds:          data.num_rounds,
            userSlot:           data.user_slot,
            teamNames:          data.team_names,
            scoringFormat:      data.scoring,
            rosterSlots:        data.roster_slots,
            starterSlotLabels:  data.starter_slot_labels || [],
            existingPicks:      data.picks || [],
            teamRosters:        data.team_rosters || null,
            rosterPlayerNames:  data.roster_player_names || [],
            draftStatus:        data.draft_status || 'complete',
            leagueType:         data.league_type  || 'redraft',
            season:             data.season || year,
            previousLeagueId:   data.previous_league_id || null,
            standings:          data.standings || [],
            leagueStartYear:    data.league_start_year || DB.leagueStartYear || null,
        });
    } catch (e) {
        showSeasonError('Network error loading season');
    } finally {
        if (sel) sel.disabled = false;
    }
}

function trimSeasonSelector(failedYear) {
    const sel = document.getElementById('db-season-select');
    if (!sel) return;
    Array.from(sel.options).forEach(opt => {
        if (parseInt(opt.value, 10) <= failedYear) opt.remove();
    });
    DB.leagueStartYear = failedYear + 1;
}

function showSeasonError(msg) {
    const sel = document.getElementById('db-season-select');
    if (sel) sel.value = DB.season;
    const meta = document.getElementById('db-topbar-meta');
    if (meta) {
        const orig = meta.textContent;
        meta.textContent = msg;
        meta.style.color = 'var(--error, #f44)';
        setTimeout(() => { meta.textContent = orig; meta.style.color = ''; }, 3000);
    }
}

async function _resolveSleeperStartYear(leagueId) {
    let lid = leagueId;
    let earliest = null;
    let hops = 0;
    while (lid && hops < 15) {
        try {
            const resp = await fetch(`https://api.sleeper.app/v1/league/${lid}`);
            if (!resp.ok) break;
            const lg = await resp.json();
            earliest = lg.season ? parseInt(lg.season) : earliest;
            lid = lg.previous_league_id || null;
            hops++;
        } catch { break; }
    }
    return earliest;
}

async function _resolveSleeperLeagueId(currentLeagueId, currentYear, targetYear) {
    const rootId = DB.sleeperRootLeagueId || currentLeagueId;
    const rootYear = DB.sleeperRootSeason || currentYear;

    if (targetYear === rootYear) return rootId;
    if (targetYear > rootYear) return null;

    let lid = rootId;
    let y = rootYear;
    while (y > targetYear && lid) {
        try {
            const resp = await fetch(`https://api.sleeper.app/v1/league/${lid}`);
            if (!resp.ok) return null;
            const lg = await resp.json();
            lid = lg.previous_league_id;
            y = (lg.season ? parseInt(lg.season) : y) - 1;
            if (!lid) return null;
        } catch {
            return null;
        }
    }
    return lid;
}

// ── Mobile drawer ─────────────────────────────────────────────

function initDrawer() {
    const fab    = document.getElementById('db-mobile-fab');
    const drawer = document.getElementById('db-drawer');
    const handle = document.getElementById('db-drawer-handle');

    if (fab) fab.addEventListener('click', () => drawer.classList.toggle('open'));
    if (handle) handle.addEventListener('click', () => drawer.classList.remove('open'));

    document.querySelectorAll('.db-drawer-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.db-drawer-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.dtab;
            const body = document.getElementById('db-drawer-body');
            if (tab === 'available') {
                body.innerHTML = '';
                const panel = document.getElementById('db-available-panel');
                if (panel) body.appendChild(panel.cloneNode(true));
            } else {
                body.innerHTML = '';
                const panel = document.getElementById('db-your-team-panel');
                if (panel) body.appendChild(panel.cloneNode(true));
            }
        });
    });
}

function syncDrawerAvailable() {
    const body = document.getElementById('db-drawer-body');
    if (!body) return;
    const activeTab = document.querySelector('.db-drawer-tab.active');
    if (activeTab?.dataset?.dtab === 'available') {
        body.innerHTML = '';
        const panel = document.getElementById('db-available-panel');
        if (panel) body.appendChild(panel.cloneNode(true));
    }
}

function syncDrawerYourTeam() {
    const body = document.getElementById('db-drawer-body');
    if (!body) return;
    const activeTab = document.querySelector('.db-drawer-tab.active');
    if (activeTab?.dataset?.dtab === 'your-team') {
        body.innerHTML = '';
        const panel = document.getElementById('db-your-team-panel');
        if (panel) body.appendChild(panel.cloneNode(true));
    }
}

// ── Picker modal events ───────────────────────────────────────

function initPicker() {
    document.getElementById('db-picker-close').addEventListener('click', closePicker);
    document.getElementById('db-picker-confirm-btn').addEventListener('click', confirmPick);
    document.getElementById('db-picker-overlay').addEventListener('click', e => {
        if (e.target === document.getElementById('db-picker-overlay')) closePicker();
    });
    document.getElementById('db-picker-search').addEventListener('input', function () {
        renderPickerList(this.value);
    });
}

// ── Bootstrap ─────────────────────────────────────────────────

// ── Saved leagues ─────────────────────────────────────────────

async function loadSavedLeagues() {
    try {
        const res  = await fetch('/draft-board/leagues?_t=' + Date.now());
        const data = await res.json();
        return Array.isArray(data) ? data : [];
    } catch {
        return [];
    }
}

function renderSavedLeagues(leagues) {
    const wrap = document.getElementById('db-saved-leagues-wrap');
    const list = document.getElementById('db-saved-leagues-list');
    if (!wrap || !list) return;

    if (!leagues || leagues.length === 0) {
        wrap.style.display = 'none';
        return;
    }

    wrap.style.display = '';
    list.innerHTML = '';

    leagues.forEach(lg => {
        const typeLabel = lg.league_type === 'dynasty' ? 'Dynasty'
                        : lg.league_type === 'keeper'  ? 'Keeper'
                        : 'Redraft';
        const scoring   = (lg.scoring || 'ppr').toUpperCase().replace('_', ' ');

        const row = document.createElement('div');
        row.className = 'db-saved-league-row';
        row.innerHTML = `
            <div class="db-saved-league-info">
                <span class="db-saved-league-name">${lg.league_name || 'My League'}</span>
                <span class="db-saved-league-meta">${typeLabel} · ${lg.num_teams || '?'} teams · ${scoring}</span>
            </div>
            <div class="db-saved-league-actions">
                <button class="db-topbar-btn db-open-league-btn" data-league-id="${lg.league_id}"
                        data-source="${lg.source || 'sleeper'}"
                        data-sleeper-user-id="${lg.sleeper_user_id || ''}"
                        data-espn-s2="${lg.espn_s2 || ''}"
                        data-espn-swid="${lg.espn_swid || ''}"
                        data-user-slot="${lg.user_slot || 0}"
                        data-scoring="${lg.scoring || 'ppr'}">Open</button>
                <button class="db-topbar-btn danger db-remove-league-btn" data-league-id="${lg.league_id}">✕</button>
            </div>
        `;
        list.appendChild(row);
    });

    // Open button
    list.querySelectorAll('.db-open-league-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const leagueId        = btn.dataset.leagueId;
            const connectSource   = btn.dataset.source || 'sleeper';
            const sleeperUserId   = btn.dataset.sleeperUserId;
            const scoring         = btn.dataset.scoring || 'ppr';
            const espnS2          = btn.dataset.espnS2;
            const espnSwid        = btn.dataset.espnSwid;
            const savedUserSlot   = parseInt(btn.dataset.userSlot) || 0;

            DB.sleeperUserId = sleeperUserId || null;

            btn.disabled = true;
            btn.innerHTML = '<span class="db-spinner"></span>';

            const errEl = document.getElementById('sleeper-error');
            if (errEl) errEl.style.display = 'none';

            try {
                let connectUrl, connectBody;
                if (connectSource === 'espn') {
                    connectUrl = '/draft-board/espn/connect';
                    connectBody = { league_id: leagueId };
                    // For ESPN, sleeper_user_id stores the ESPN team ID
                    if (sleeperUserId) connectBody.user_team_id = sleeperUserId;
                    if (espnS2) connectBody.espn_s2 = espnS2;
                    if (espnSwid) connectBody.swid = espnSwid;
                    DB.espnCookies = (espnS2 && espnSwid) ? { espn_s2: espnS2, swid: espnSwid } : null;
                    DB.espnUserTeamId = sleeperUserId || null;
                } else {
                    connectUrl = '/draft-board/sleeper/connect';
                    connectBody = { league_id: leagueId, sleeper_user_id: sleeperUserId };
                    DB.sleeperRootLeagueId = leagueId;
                }

                const res = await fetch(connectUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(connectBody),
                });
                const data = await res.json();
                if (!res.ok || data.error) {
                    if (errEl) { errEl.textContent = data.error || 'Failed to connect.'; errEl.style.display = ''; }
                    btn.disabled = false;
                    btn.textContent = 'Open';
                    return;
                }

                // Update last_accessed + persist user_slot if we got one
                const resolvedSlot = data.user_slot || savedUserSlot;
                fetch('/draft-board/leagues/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        league_id:   leagueId,
                        league_name: data.league_name,
                        user_slot:   resolvedSlot || undefined,
                    }),
                }).catch(() => {});

                if (connectSource === 'sleeper') {
                    DB.sleeperRootSeason = parseInt(data.season) || new Date().getFullYear();
                }

                // Backend now resolves league_start_year; only fall back to client-side if missing
                const openStartYear = data.league_start_year || null;

                await initBoard({
                    source:             connectSource,
                    leagueId,
                    draftId:            data.draft_id,
                    leagueName:         data.league_name,
                    numTeams:           data.num_teams,
                    numRounds:          data.num_rounds,
                    userSlot:           data.user_slot || savedUserSlot,
                    teamNames:          data.team_names,
                    scoringFormat:      scoring,
                    rosterSlots:        data.roster_slots,
                    starterSlotLabels:  data.starter_slot_labels || [],
                    existingPicks:      data.picks || [],
                    teamRosters:        data.team_rosters || null,
                    rosterPlayerNames:  data.roster_player_names || [],
                    draftStatus:        data.draft_status || 'pre_draft',
                    leagueType:         data.league_type  || 'redraft',
                    season:             data.season || new Date().getFullYear(),
                    previousLeagueId:   data.previous_league_id || null,
                    standings:          data.standings || [],
                    leagueStartYear:    data.league_start_year || openStartYear || null,
                });
            } catch (e) {
                console.error('Open league error:', e);
                if (errEl) { errEl.textContent = 'Network error.'; errEl.style.display = ''; }
            } finally {
                btn.disabled = false;
                btn.textContent = 'Open';
            }
        });
    });

    // Remove button
    list.querySelectorAll('.db-remove-league-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const leagueId = btn.dataset.leagueId;
            await fetch(`/draft-board/leagues/${leagueId}`, { method: 'DELETE' });
            // Re-fetch and re-render
            const updated = await loadSavedLeagues();
            renderSavedLeagues(updated);
        });
    });
}

async function boot() {
    initSetupPanel();
    initFilterTabs();
    initDrawer();
    initPicker();

    document.getElementById('db-reset-btn').addEventListener('click', () => {
        stopPolling();
        window.location.reload();
    });

    // Available-only toggle
    document.getElementById('db-avail-toggle')?.addEventListener('click', function () {
        DB.showAvailOnly = !DB.showAvailOnly;
        this.classList.toggle('active', DB.showAvailOnly);
        renderAvailable();
    });

    // ── Scroll isolation: board & left panel scroll independently ──
    function trapScroll(el) {
        if (!el) return;
        el.addEventListener('wheel', e => {
            const maxScroll = el.scrollHeight - el.clientHeight;
            if (maxScroll <= 0) return;
            const atTop    = el.scrollTop <= 0 && e.deltaY < 0;
            const atBottom = el.scrollTop >= maxScroll && e.deltaY > 0;
            if (!atTop && !atBottom) {
                e.stopPropagation();
                e.preventDefault();
                el.scrollTop += e.deltaY;
            }
        }, { passive: false });
    }
    trapScroll(document.getElementById('db-board-scroll'));
    trapScroll(document.getElementById('db-player-list'));

    // ── Other Teams: collapse / expand toggle ─────────────────
    document.getElementById('db-ot-toggle')?.addEventListener('click', () => {
        const panel = document.getElementById('db-other-teams');
        panel.classList.toggle('ot-collapsed');
    });

    // ── Generic drag-to-resize helper ────────────────────────
    const PANEL_HEIGHT_KEY = 'db_active_panel_height';

    function makeResizeHandle(handleId, targetId, { min = 60, max = 500, direction = 'up', storageKey = null } = {}) {
        const handle = document.getElementById(handleId);
        const target = document.getElementById(targetId);
        if (!handle || !target) return;

        function applyDrag(startY, startH, currentY) {
            const delta = direction === 'up'
                ? startY - currentY
                : currentY - startY;
            target.style.height = Math.max(min, Math.min(max, startH + delta)) + 'px';
        }

        function savePanelHeight() {
            if (storageKey) {
                try { localStorage.setItem(storageKey, target.offsetHeight); } catch {}
            }
        }

        handle.addEventListener('mousedown', e => {
            e.preventDefault();
            const startY = e.clientY;
            const startH = target.offsetHeight;
            handle.classList.add('dragging');
            document.body.style.userSelect = 'none';

            const onMove = e => { e.preventDefault(); applyDrag(startY, startH, e.clientY); };
            const onUp   = () => {
                handle.classList.remove('dragging');
                document.body.style.userSelect = '';
                savePanelHeight();
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });

        handle.addEventListener('touchstart', e => {
            e.preventDefault();
            const startY = e.touches[0].clientY;
            const startH = target.offsetHeight;

            const onMove = e => { e.preventDefault(); applyDrag(startY, startH, e.touches[0].clientY); };
            const onEnd  = () => {
                savePanelHeight();
                handle.removeEventListener('touchmove', onMove);
                handle.removeEventListener('touchend', onEnd);
            };
            handle.addEventListener('touchmove', onMove, { passive: false });
            handle.addEventListener('touchend', onEnd);
        }, { passive: false });
    }

    // Bottom row handle: drag down = grows, drag up = shrinks — persisted in localStorage
    makeResizeHandle('db-bottom-resize-handle', 'db-active', { min: 200, max: 5000, direction: 'down' });

    // Sync Now — show brief spinner then success indicator
    document.getElementById('db-sync-now-btn')?.addEventListener('click', async function () {
        const btn = this;
        const prev = btn.textContent;
        btn.disabled = true;
        btn.textContent = '↻ Syncing…';
        try {
            await syncFromSleeper();
            btn.textContent = '✓ Synced';
            btn.classList.add('db-sync-ok');
        } catch (_) {
            btn.textContent = '⚠ Error';
        } finally {
            setTimeout(() => {
                btn.textContent  = prev;
                btn.disabled     = false;
                btn.classList.remove('db-sync-ok');
            }, 2000);
        }
    });

    // Load + show saved leagues on setup panel
    const savedLeagues = await loadSavedLeagues();
    renderSavedLeagues(savedLeagues);

    // Always show setup/My Leagues page on fresh navigation.
    // User clicks "Open" on a league to enter it.
}

document.addEventListener('DOMContentLoaded', boot);
