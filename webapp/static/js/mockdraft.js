/* ═══════════════════════════════════════════════════════════════
   DARKHORSE MOCK DRAFT — mockdraft.js
═══════════════════════════════════════════════════════════════ */

// ── State ──────────────────────────────────────────────────────
const S = {
  // settings
  scoring: 'ppr',
  draftType: 'snake',
  numTeams: 10,
  userSlot: 'random',  // 1-based index or 'random'
  slots: { QB:1, RB:2, WR:2, TE:1, FLEX:1, Bench:6 },
  pickTimer: 0,        // seconds, 0 = none
  auctionBudget: 200,
  bidTimeLimit: 10,
  rankingSource: 'darkhorse',

  // derived
  totalRounds: 13,
  userTeamIdx: 0,      // 0-based

  // draft state
  players: [],         // all players from server, ranked order
  available: [],       // indices into players[] still available
  board: [],           // board[teamIdx] = array of pick objects
  budgets: [],         // auction budgets per team
  draftOrder: [],      // snake: pick sequence as teamIdx values
  currentPickIdx: 0,   // index into draftOrder
  round: 1,
  isUserTurn: false,
  pickBusy: false,     // prevents runNextPick re-entry
  cpuPickTimeout: null,
  advancePickTimeout: null,
  timerInterval: null,
  timerRemaining: 0,
  drafted: new Set(),  // player indices drafted

  // auction state
  auctionRound: 0,
  nominationOrder: [],  // teamIdx rotation
  nomIdx: 0,
  currentNominee: null, // player index
  currentBid: 0,
  currentBidder: -1,
  bidTimerInterval: null,
  bidTimerRemaining: 0,
  cpuBidPending: false,
  cpuBudgetUsed: [],
  rosterFilled: [],     // bool per team when all slots used
  auctionComplete: false,
};

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
  return `<div class="player-update player-update-${update.tone || 'info'}" title="${escHtml(update.title || text)}">${escHtml(text)}</div>`;
}

// ── Lobby setup ────────────────────────────────────────────────
$(function () {
  updateRoundsPreview();
  updatePositionDropdown();

  // Toggle groups
  $(document).on('click', '.toggle-btn', function () {
    const $group = $(this).closest('.toggle-group');
    $group.find('.toggle-btn').removeClass('active');
    $(this).addClass('active');
    onSettingChange($group.attr('id'), $(this).data('val'));
  });

  // Roster inputs
  $(document).on('input', '.roster-input', updateRoundsPreview);

  // Search + filter
  $('#playerSearch').on('input', renderPlayerList);
  $('#auctionPlayerSearch').on('input', renderAuctionPlayerList);
  $(document).on('click', '#posFilter .pos-btn', function () {
    $('#posFilter .pos-btn').removeClass('active');
    $(this).addClass('active');
    renderPlayerList();
  });
  $(document).on('click', '#auctionPosFilter .pos-btn', function () {
    $('#auctionPosFilter .pos-btn').removeClass('active');
    $(this).addClass('active');
    renderAuctionPlayerList();
  });

  $('#startDraftBtn').on('click', startDraft);
  $('#saveDraftBtn').on('click', saveDraft);
  $('#emailDraftBtn').on('click', emailDraft);
  $('#newDraftBtn').on('click', function () { location.reload(); });

  // Leave draft buttons
  $(document).on('click', '#leaveDraftBtn, #leaveAuctionBtn', function () {
    if (confirm('Leave the draft? Your progress will not be saved.')) {
      cancelAllPickTimeouts();
      clearInterval(S.bidTimerInterval);
      $('#snakeDraft').hide();
      $('#auctionDraft').hide();
      $('#postDraft').hide();
      $('#lobby').show();
      $('#startDraftBtn').prop('disabled', false).text('Start Draft');
    }
  });

  // Auction bid buttons
  $('#bid1').on('click', function () { placeBid(S.currentBid + 1); });
  $('#bid5').on('click', function () { placeBid(S.currentBid + 5); });
  $('#bid10').on('click', function () { placeBid(S.currentBid + 10); });
  $('#customBidBtn').on('click', function () {
    const v = parseInt($('#customBidInput').val());
    if (!isNaN(v) && v > S.currentBid) placeBid(v);
  });
  $('#passBidBtn').on('click', function () { userPassBid(); });
});

function onSettingChange(groupId, val) {
  if (groupId === 'scoringToggle')   S.scoring    = val;
  if (groupId === 'draftTypeToggle') {
    S.draftType = val;
    $('#auctionSettings').toggle(val === 'auction');
  }
  if (groupId === 'numTeamsToggle') {
    S.numTeams = parseInt(val);
    updatePositionDropdown();
  }
  if (groupId === 'timerToggle')       S.pickTimer  = parseInt(val);
  if (groupId === 'bidTimerToggle')    S.bidTimeLimit = parseInt(val);
  if (groupId === 'rankingSourceToggle') {
    S.rankingSource = val;
    const hints = { darkhorse: 'Darkhorse model — custom rankings based on 2025 season', sleeper: 'Community ADP — reflects Sleeper 2025 fantasy points by format', espn: 'ESPN only publicly exposes PPR rankings — Half PPR and Standard are unavailable' };
    // Lock scoring to PPR when ESPN is selected
    if (val === 'espn') {
      $('#scoringToggle .toggle-btn').not('[data-val="ppr"]').prop('disabled', true).css('opacity', '0.35');
      $('#scoringToggle .toggle-btn[data-val="ppr"]').addClass('active');
      $('#scoringToggle .toggle-btn').not('[data-val="ppr"]').removeClass('active');
      S.scoring = 'ppr';
    } else {
      $('#scoringToggle .toggle-btn').prop('disabled', false).css('opacity', '');
    }
    $('#rankingSourceHint').text(hints[val] || '');
  }
}

function updateRoundsPreview() {
  const total = parseInt($('#slotQB').val()||0) + parseInt($('#slotRB').val()||0) +
    parseInt($('#slotWR').val()||0) + parseInt($('#slotTE').val()||0) +
    parseInt($('#slotFLEX').val()||0) + parseInt($('#slotBench').val()||0);
  S.totalRounds = total;
  $('#roundsPreview').text(total);
  $('#rosterWarning').toggle(total > 20);
}

function updatePositionDropdown() {
  const n = S.numTeams;
  const $sel = $('#draftPositionSelect');
  $sel.empty().append('<option value="random">Random</option>');
  for (let i = 1; i <= n; i++) $sel.append(`<option value="${i}">${i}</option>`);
}

// ── Start Draft ────────────────────────────────────────────────
function startDraft() {
  S.scoring     = $('#scoringToggle .toggle-btn.active').data('val');
  S.draftType   = $('#draftTypeToggle .toggle-btn.active').data('val');
  S.numTeams    = parseInt($('#numTeamsToggle .toggle-btn.active').data('val'));
  S.pickTimer   = parseInt($('#timerToggle .toggle-btn.active').data('val'));
  S.bidTimeLimit= parseInt($('#bidTimerToggle .toggle-btn.active').data('val'));
  S.auctionBudget = parseInt($('#auctionBudget').val()) || 200;
  const posVal  = $('#draftPositionSelect').val();
  S.userSlot    = posVal === 'random' ? Math.ceil(Math.random() * S.numTeams) : parseInt(posVal);
  S.userTeamIdx = S.userSlot - 1;
  S.slots = {
    QB: parseInt($('#slotQB').val()||1),
    RB: parseInt($('#slotRB').val()||2),
    WR: parseInt($('#slotWR').val()||2),
    TE: parseInt($('#slotTE').val()||1),
    FLEX: parseInt($('#slotFLEX').val()||1),
    Bench: parseInt($('#slotBench').val()||6),
  };
  updateRoundsPreview();

  $('#startDraftBtn').prop('disabled', true).text('Loading...');

  S.rankingSource = $('#rankingSourceToggle .toggle-btn.active').data('val') || 'darkhorse';
  $.ajax({ url: '/mockdraft/players', data: { scoring: S.scoring, source: S.rankingSource }, cache: false, success: function (data) {
    // Normalize positions: strip trailing numbers ('WR5' → 'WR', 'RB12' → 'RB')
    data.forEach(p => { p['Position'] = (p['Position'] || '').replace(/\d+$/, '').trim().toUpperCase(); });
    cancelAllPickTimeouts();  // kill any stale timeouts from a previous draft
    S.players  = data;
    S.available = data.map((_, i) => i);
    S.drafted  = new Set();
    S.board    = Array.from({ length: S.numTeams }, () => []);
    S.currentPickIdx = 0;
    S.round = 1;

    if (S.draftType === 'snake') {
      buildSnakeDraftOrder();
      $('#lobby').hide();
      $('#snakeDraft').show();
      buildBoardGrid();
      renderPlayerList();
      buildYourTeamPanel();
      setTimeout(runNextPick, 600);
    } else {
      initAuction();
      $('#lobby').hide();
      $('#auctionDraft').show();
      buildAuctionBoard();
      renderAuctionPlayerList();
      buildAuctionYourTeam();
      setTimeout(runNextNomination, 600);
    }
  }}).fail(function () {
    $('#startDraftBtn').prop('disabled', false).text('Start Draft');
    alert('Failed to load players. Please try again.');
  });
}

// ── Snake Draft ────────────────────────────────────────────────
function buildSnakeDraftOrder() {
  S.draftOrder = [];
  for (let r = 0; r < S.totalRounds; r++) {
    const fwd = Array.from({ length: S.numTeams }, (_, i) => i);
    const row = r % 2 === 0 ? fwd : [...fwd].reverse();
    S.draftOrder.push(...row);
  }
}

function buildBoardGrid() {
  const $head = $('#boardHead');
  const $body = $('#boardBody');
  $head.empty();
  $body.empty();

  // Header row
  let hRow = '<tr><th class="round-label">Rd</th>';
  for (let t = 0; t < S.numTeams; t++) {
    const cls = t === S.userTeamIdx ? 'user-col' : '';
    const label = t === S.userTeamIdx ? 'YOU' : `Team ${t + 1}`;
    hRow += `<th class="${cls}">${label}</th>`;
  }
  hRow += '</tr>';
  $head.html(hRow);

  // Body rows
  for (let r = 0; r < S.totalRounds; r++) {
    let row = `<tr><td class="round-label">${r + 1}</td>`;
    for (let t = 0; t < S.numTeams; t++) {
      const cls = t === S.userTeamIdx ? 'user-col' : '';
      row += `<td class="${cls}" id="cell-${r}-${t}"></td>`;
    }
    row += '</tr>';
    $body.append(row);
  }
}

function buildYourTeamPanel() {
  updateYourTeamPanel();
}

function buildSlotDefs() {
  const defs = [];
  for (let i = 0; i < S.slots.QB; i++)    defs.push({ label:'QB',   pos:['QB'] });
  for (let i = 0; i < S.slots.RB; i++)    defs.push({ label:'RB',   pos:['RB'] });
  for (let i = 0; i < S.slots.WR; i++)    defs.push({ label:'WR',   pos:['WR'] });
  for (let i = 0; i < S.slots.TE; i++)    defs.push({ label:'TE',   pos:['TE'] });
  for (let i = 0; i < S.slots.FLEX; i++)  defs.push({ label:'FLEX', pos:['RB','WR','TE'] });
  for (let i = 0; i < S.slots.Bench; i++) defs.push({ label:`BN`,   pos:['QB','RB','WR','TE'] });
  return defs;
}

function runNextPick() {
  if (S.pickBusy) return;  // prevent re-entry
  if (S.currentPickIdx >= S.draftOrder.length) {
    endSnakeDraft();
    return;
  }

  const teamIdx = S.draftOrder[S.currentPickIdx];
  S.round = Math.floor(S.currentPickIdx / S.numTeams) + 1;
  const pickNum = (S.currentPickIdx % S.numTeams) + 1;

  // Highlight active cell
  $('.draft-board td.active-cell').removeClass('active-cell');
  const $cell = $(`#cell-${S.round - 1}-${teamIdx}`);
  $cell.addClass('active-cell');

  if (teamIdx === S.userTeamIdx) {
    S.pickBusy = false;  // user's turn — not busy, awaiting input
    S.isUserTurn = true;
    const label = `Round ${S.round}, Pick ${pickNum} — YOUR TURN`;
    $('#pickStatus').text(label);
    enableUserPicks();
    renderPlayerList(); // re-render now that isUserTurn=true so pos-full classes apply
    if (S.pickTimer > 0) startPickTimer();
  } else {
    S.pickBusy = true;  // CPU pick in flight
    S.isUserTurn = false;
    $('#pickStatus').text(`Round ${S.round}, Pick ${pickNum} — Team ${teamIdx + 1} picking...`);
    disableUserPicks();
    // CPU pick after short random delay
    const delay = 600 + Math.random() * 900;
    S.cpuPickTimeout = setTimeout(() => { cpuPick(teamIdx); }, delay);
  }
}

function enableUserPicks() {
  $('#playerList').addClass('picks-enabled');
}

function disableUserPicks() {
  $('#playerList').removeClass('picks-enabled');
}

function startPickTimer() {
  clearInterval(S.timerInterval);
  S.timerRemaining = S.pickTimer;
  const $t = $('#pickTimer').show().text(S.timerRemaining).removeClass('urgent');
  S.timerInterval = setInterval(() => {
    S.timerRemaining--;
    $t.text(S.timerRemaining);
    if (S.timerRemaining <= 5) $t.addClass('urgent');
    if (S.timerRemaining <= 0) {
      clearInterval(S.timerInterval);
      // Auto-pick best available
      if (S.available.length > 0) {
        userDraftPlayer(S.available[0]);
      }
    }
  }, 1000);
}

function stopPickTimer() {
  clearInterval(S.timerInterval);
  $('#pickTimer').hide().removeClass('urgent');
}

function cancelAllPickTimeouts() {
  clearTimeout(S.cpuPickTimeout);
  clearTimeout(S.advancePickTimeout);
  stopPickTimer();
  S.pickBusy = false;
  S.cpuPickTimeout = null;
  S.advancePickTimeout = null;
}

function cpuPick(teamIdx) {
  const playerIdx = cpuChoosePlayer(teamIdx);
  if (playerIdx === -1) { advancePick(teamIdx, null); return; }
  advancePick(teamIdx, playerIdx);
}

function cpuChoosePlayer(teamIdx) {
  if (S.available.length === 0) return -1;
  const teamPicks = S.board[teamIdx];
  const posNeeds = computePosNeeds(teamPicks, S.totalRounds - S.round);

  // Weighted probability — stronger position filtering in later rounds
  const lateRound = S.round > S.totalRounds * 0.6;

  // Build candidate pool with weights
  let candidates = [];
  const maxLook = Math.min(S.available.length, Math.max(8, (S.round * 3)));

  for (let i = 0; i < maxLook; i++) {
    const pIdx = S.available[i];
    const p = S.players[pIdx];
    const pos = (p['Position'] || '').toUpperCase();

    // In late rounds, strong bias toward needed positions
    if (lateRound) {
      const stillNeeds = posNeeds[pos] > 0 || (posNeeds['FLEX'] > 0 && ['RB','WR','TE'].includes(pos));
      if (!stillNeeds && posNeeds['Bench'] === 0) continue;
    }

    // distance-based weight: position 0 has highest weight
    const weight = 1 / Math.pow(1 + i, 1.5);
    candidates.push({ pIdx, weight });
  }

  if (candidates.length === 0) {
    // fallback: just pick any available player team still needs
    for (const pIdx of S.available) {
      const pos = (S.players[pIdx]['Position']||'').toUpperCase();
      if (posNeeds[pos] > 0 || posNeeds['Bench'] > 0) return pIdx;
    }
    return S.available[0];
  }

  // Weighted random selection
  const total = candidates.reduce((s, c) => s + c.weight, 0);
  let r = Math.random() * total;
  for (const c of candidates) {
    r -= c.weight;
    if (r <= 0) return c.pIdx;
  }
  return candidates[0].pIdx;
}

function computePosNeeds(teamPicks, roundsLeft) {
  const counts = { QB:0, RB:0, WR:0, TE:0, FLEX:0, Bench:0 };
  for (const pick of teamPicks) {
    const pos = (pick.position||'').toUpperCase();
    // Fill primary slots first
    if (pos === 'QB' && counts.QB < S.slots.QB) { counts.QB++; continue; }
    if (pos === 'RB' && counts.RB < S.slots.RB) { counts.RB++; continue; }
    if (pos === 'WR' && counts.WR < S.slots.WR) { counts.WR++; continue; }
    if (pos === 'TE' && counts.TE < S.slots.TE) { counts.TE++; continue; }
    if (['RB','WR','TE'].includes(pos) && counts.FLEX < S.slots.FLEX) { counts.FLEX++; continue; }
    counts.Bench++;
  }
  return {
    QB:   Math.max(0, S.slots.QB   - counts.QB),
    RB:   Math.max(0, S.slots.RB   - counts.RB),
    WR:   Math.max(0, S.slots.WR   - counts.WR),
    TE:   Math.max(0, S.slots.TE   - counts.TE),
    FLEX: Math.max(0, S.slots.FLEX - counts.FLEX),
    Bench:Math.max(0, S.slots.Bench- counts.Bench),
  };
}

function advancePick(teamIdx, playerIdx) {
  stopPickTimer();
  S.pickBusy = false;  // will be re-set by runNextPick if next pick is CPU
  const round = Math.floor(S.currentPickIdx / S.numTeams);

  if (playerIdx !== null) {
    const p = S.players[playerIdx];
    const pos = (p['Position']||'').toUpperCase();
    const name = p['Name'] || p['Player'] || '?';
    const nflTeam = p['Team'] || '';

    const pick = { name, position: pos, nfl_team: nflTeam, rank: p['Rank'], round: round + 1 };
    S.board[teamIdx].push(pick);
    S.drafted.add(playerIdx);
    S.available = S.available.filter(i => i !== playerIdx);

    // Fill board cell
    $(`#cell-${round}-${teamIdx}`).removeClass('active-cell').html(
      `<div class="cell-name">${name}</div><div class="cell-meta"><span class="pos-badge pos-${pos}">${pos}</span> ${nflTeam}</div>`
    );

    // Gray out drafted player immediately for all picks
    renderPlayerList();

    // Update your team panel if it was user's pick
    if (teamIdx === S.userTeamIdx) updateYourTeamPanel();
  } else {
    $(`#cell-${round}-${teamIdx}`).removeClass('active-cell').html('<div class="cell-meta">—</div>');
  }

  S.currentPickIdx++;
  S.advancePickTimeout = setTimeout(runNextPick, 200);
}

// Called when user clicks a player row
function userDraftPlayer(playerIdx) {
  if (!S.isUserTurn) return;
  S.isUserTurn = false;
  stopPickTimer();
  disableUserPicks();
  advancePick(S.userTeamIdx, playerIdx);
}

function updateYourTeamPanel() {
  const panel = document.getElementById('yourTeam');
  if (!panel) return;

  const slotDefs    = buildSlotDefs();
  const picks       = (S.board[S.userTeamIdx] || []).slice();
  const usedPickIdx = new Set();
  let html = '';

  slotDefs.forEach((slot) => {
    const matchIdx = picks.findIndex((p, pi) =>
      !usedPickIdx.has(pi) && slot.pos.includes(p.position)
    );
    if (matchIdx !== -1) {
      usedPickIdx.add(matchIdx);
      const p = picks[matchIdx];
      html += `<div class="roster-slot filled">
        <div class="slot-label">${slot.label}</div>
        <div class="slot-player">${p.name} <span class="pos-badge pos-${p.position}">${p.position}</span></div>
        <div class="slot-meta">${p.nfl_team}</div>
      </div>`;
    } else {
      html += `<div class="roster-slot">
        <div class="slot-label">${slot.label}</div>
        <div class="slot-player">—</div>
      </div>`;
    }
  });

  panel.innerHTML = html;
}

function endSnakeDraft() {
  $('.draft-board td.active-cell').removeClass('active-cell');
  $('#pickStatus').text('Draft Complete!');
  stopPickTimer();

  const userTeam = S.board[S.userTeamIdx].map((p, i) => ({ ...p, round: i + 1 }));
  const boardData = buildBoardExport();

  showPostDraft(boardData, userTeam);
}

// ── Player List Rendering ───────────────────────────────────────

// Returns true if the user's roster still has a slot that can hold this position
function userCanDraftPosition(pos) {
  const needs = computePosNeeds(S.board[S.userTeamIdx], 999);
  if (needs[pos] > 0) return true;
  if (needs['FLEX'] > 0 && ['RB','WR','TE'].includes(pos)) return true;
  if (needs['Bench'] > 0) return true;
  return false;
}

function renderPlayerList() {
  const filterPos = $('#posFilter .pos-btn.active').data('pos') || 'ALL';
  const search    = ($('#playerSearch').val() || '').toLowerCase();
  const $list     = $('#playerList').empty();

  S.players.forEach((p, i) => {
    const pos  = (p['Position'] || '').toUpperCase();
    const name = p['Name'] || p['Player'] || '';
    if (filterPos !== 'ALL' && pos !== filterPos) return;
    if (search && !name.toLowerCase().includes(search)) return;

    const drafted   = S.drafted.has(i);
    // During user's turn, check if their roster has room for this position
    const posFull   = !drafted && S.isUserTurn && !userCanDraftPosition(pos);
    const classes   = ['player-row', drafted ? 'drafted' : '', posFull ? 'pos-full' : ''].filter(Boolean).join(' ');
    const subParts  = [];
    if (p['Team']) subParts.push(p['Team']);
    if (p['Bye Week']) subParts.push('Bye ' + p['Bye Week']);

    const $row = $(`<div class="${classes}" data-idx="${i}">
      <span class="player-rank">${p['Rank'] || i+1}</span>
      <div class="player-name-cell">
        <div class="player-name">${name}</div>
        <div class="player-sub">${subParts.join(' | ')}</div>
        ${buildPlayerUpdateMarkup(p['InjuryNews'])}
      </div>
      <span class="pos-badge pos-${pos}">${pos}</span>
    </div>`);

    if (!drafted && !posFull) {
      $row.on('click', function () {
        if (S.isUserTurn) userDraftPlayer(i);
      });
    }
    $list.append($row);
  });
}

// ── Auction Draft ───────────────────────────────────────────────
function initAuction() {
  S.budgets       = Array(S.numTeams).fill(S.auctionBudget);
  S.cpuBudgetUsed = Array(S.numTeams).fill(0);
  S.rosterFilled  = Array(S.numTeams).fill(false);
  S.auctionRound  = 0;
  S.nomIdx        = 0;
  S.currentNominee= null;
  S.currentBid    = 0;
  S.currentBidder = -1;
  S.auctionComplete = false;

  // Nomination order: random start, then rotate
  const order = Array.from({ length: S.numTeams }, (_, i) => i);
  shuffle(order);
  S.nominationOrder = order;
  // Put user slot at random position (already randomized)
}

function buildAuctionBoard() {
  const $head = $('#auctionTeamHead');
  const $body = $('#auctionTeamBody');
  $head.empty();
  $body.empty();

  let hRow = '<tr>';
  for (let t = 0; t < S.numTeams; t++) {
    const cls = t === S.userTeamIdx ? 'user-col' : '';
    const label = t === S.userTeamIdx ? 'YOU' : `Team ${t+1}`;
    hRow += `<th class="${cls}" id="ahead-${t}">${label}<br><span class="budget-inline" id="budgetHead-${t}">$${S.auctionBudget}</span></th>`;
  }
  hRow += '</tr>';
  $head.html(hRow);

  // One body row that we'll keep filling
  let row = '<tr>';
  for (let t = 0; t < S.numTeams; t++) {
    const cls = t === S.userTeamIdx ? 'user-col' : '';
    row += `<td class="${cls}" id="ateam-${t}" style="vertical-align:top;"></td>`;
  }
  row += '</tr>';
  $body.append(row);
}

function buildAuctionYourTeam() {
  const $panel = $('#auctionYourTeam');
  $panel.empty();
  const slotDefs = buildSlotDefs();
  slotDefs.forEach((s, i) => {
    $panel.append(`<div class="roster-slot" id="aslot-${i}">
      <div class="slot-label">${s.label}</div>
      <div class="slot-player">—</div>
    </div>`);
  });
}

function runNextNomination() {
  if (S.auctionComplete) return;

  // Check if all teams have filled rosters
  checkAuctionComplete();
  if (S.auctionComplete) return;

  // Skip teams whose rosters are full
  let tries = 0;
  while (S.rosterFilled[S.nominationOrder[S.nomIdx % S.numTeams]] && tries < S.numTeams) {
    S.nomIdx++;
    tries++;
  }
  if (tries === S.numTeams) { endAuctionDraft(); return; }

  const nomTeam = S.nominationOrder[S.nomIdx % S.numTeams];
  const teamLabel = nomTeam === S.userTeamIdx ? 'YOU' : `Team ${nomTeam + 1}`;
  $('#nominatingTeam').text(teamLabel);
  $('#biddingBlock').hide();

  if (nomTeam === S.userTeamIdx) {
    // User nominates — click from list
    $('#nominationInfo').show();
    $('#userNominationControls').show();
    $('#userBidControls').hide();
    renderAuctionPlayerList(true); // enable clicking for nomination
  } else {
    $('#userNominationControls').hide();
    renderAuctionPlayerList(false);
    // CPU nominates after short delay
    setTimeout(() => { cpuNominate(nomTeam); }, 800 + Math.random()*700);
  }
}

function cpuNominate(teamIdx) {
  if (S.available.length === 0) { endAuctionDraft(); return; }
  const needs = computePosNeeds(S.board[teamIdx], 999);
  // Nominate top available player they most need
  for (const pIdx of S.available) {
    const pos = (S.players[pIdx]['Position']||'').toUpperCase();
    if (needs[pos] > 0 || needs['FLEX'] > 0) {
      openBidding(pIdx, teamIdx);
      return;
    }
  }
  openBidding(S.available[0], teamIdx);
}

function openBidding(playerIdx, nominatingTeam) {
  S.currentNominee = playerIdx;
  S.currentBid     = 1;
  S.currentBidder  = nominatingTeam;

  const p    = S.players[playerIdx];
  const name = p['Name'] || p['Player'] || '?';
  const pos  = (p['Position']||'').toUpperCase();

  $('#bidPlayerName').text(name);
  $('#bidPlayerMeta').html(`<span class="pos-badge pos-${pos}">${pos}</span> ${p['Team']||''} · Rank #${p['Rank']||'?'}`);
  $('#currentBidAmount').text('$1');
  $('#currentBidLeader').text(`(${nominatingTeam === S.userTeamIdx ? 'YOU' : 'Team '+(nominatingTeam+1)})`);
  $('#nominationInfo').show();
  $('#biddingBlock').show();

  // Show user bid controls only if user can still bid
  const userCanBid = S.budgets[S.userTeamIdx] > 1 &&
    !S.rosterFilled[S.userTeamIdx] &&
    S.currentBidder !== S.userTeamIdx;
  $('#userBidControls').toggle(userCanBid);
  $('#userNominationControls').hide();

  resetBidTimer();
  scheduleCpuBids();
}

function resetBidTimer() {
  clearInterval(S.bidTimerInterval);
  S.bidTimerRemaining = S.bidTimeLimit;
  updateBidTimerUI();

  S.bidTimerInterval = setInterval(() => {
    S.bidTimerRemaining -= 0.1;
    updateBidTimerUI();
    if (S.bidTimerRemaining <= 0) {
      clearInterval(S.bidTimerInterval);
      awardPlayer();
    }
  }, 100);
}

function updateBidTimerUI() {
  const pct = Math.max(0, S.bidTimerRemaining / S.bidTimeLimit * 100);
  const urgent = S.bidTimerRemaining < S.bidTimeLimit * 0.3;
  $('#bidTimerFill').css('width', pct+'%').toggleClass('urgent', urgent);
  $('#bidTimerText').text(`${Math.ceil(Math.max(0, S.bidTimerRemaining))}s remaining`);
}

function scheduleCpuBids() {
  // Each CPU team independently decides whether to bid
  for (let t = 0; t < S.numTeams; t++) {
    if (t === S.userTeamIdx) continue;
    if (S.rosterFilled[t]) continue;
    if (t === S.currentBidder) continue;

    const delay = 1000 + Math.random() * (S.bidTimeLimit * 700);
    setTimeout(() => { cpuConsiderBid(t); }, delay);
  }
}

function cpuConsiderBid(teamIdx) {
  if (S.currentNominee === null) return;
  if (S.rosterFilled[teamIdx]) return;
  if (teamIdx === S.currentBidder) return; // already winning

  const p   = S.players[S.currentNominee];
  const pos = (p['Position']||'').toUpperCase();
  const playerVal = cpuPlayerValue(teamIdx, S.currentNominee);

  // Must keep $1 per remaining roster spot
  const filled = S.board[teamIdx].length;
  const totalSlots = S.totalRounds;
  const slotsLeft = totalSlots - filled - 1; // -1 for this pick
  const minReserve = Math.max(0, slotsLeft);
  const maxCanBid = S.budgets[teamIdx] - minReserve;

  const nextBid = S.currentBid + 1;
  if (nextBid > maxCanBid) return; // can't afford
  if (nextBid > playerVal) return; // not worth it

  // Random chance they pass even if they value it (simulate real draft)
  if (Math.random() < 0.2) return;

  // Place CPU bid
  placeBidFrom(nextBid, teamIdx);
}

function cpuPlayerValue(teamIdx, playerIdx) {
  const p = S.players[playerIdx];
  const rank = p['Rank'] || playerIdx + 1;
  const total = S.players.length;
  // Base value as fraction of budget, scaled by rank
  const baseVal = ((total - rank + 1) / total) * S.budgets[teamIdx] * 0.8;
  // Position weight randomized per team (simulate tendencies)
  const posWeights = { QB:0.9, RB:1.1, WR:1.0, TE:0.85 };
  const pos = (p['Position']||'QB').toUpperCase();
  const pw = (posWeights[pos] || 1.0) + (Math.random() * 0.3 - 0.15);
  return Math.floor(baseVal * pw);
}

function placeBid(amount) {
  // User places bid
  if (amount <= S.currentBid) return;
  const slotsLeft = S.totalRounds - S.board[S.userTeamIdx].length - 1;
  const minReserve = Math.max(0, slotsLeft);
  if (amount > S.budgets[S.userTeamIdx] - minReserve) {
    alert(`You need to keep $${minReserve} for remaining roster spots.`);
    return;
  }
  placeBidFrom(amount, S.userTeamIdx);
}

function placeBidFrom(amount, teamIdx) {
  S.currentBid = amount;
  S.currentBidder = teamIdx;
  const label = teamIdx === S.userTeamIdx ? 'YOU' : `Team ${teamIdx+1}`;
  $('#currentBidAmount').text(`$${amount}`);
  $('#currentBidLeader').text(`(${label})`);

  // Show/hide user bid controls
  const userCanBid = S.budgets[S.userTeamIdx] > S.currentBid &&
    !S.rosterFilled[S.userTeamIdx] &&
    S.currentBidder !== S.userTeamIdx;
  $('#userBidControls').toggle(userCanBid);

  resetBidTimer();
  scheduleCpuBids();
}

function userPassBid() {
  $('#userBidControls').hide();
}

function awardPlayer() {
  if (S.currentNominee === null) return;
  clearInterval(S.bidTimerInterval);

  const winner = S.currentBidder;
  const pIdx   = S.currentNominee;
  const p      = S.players[pIdx];
  const name   = p['Name'] || p['Player'] || '?';
  const pos    = (p['Position']||'').toUpperCase();
  const cost   = S.currentBid;

  S.budgets[winner] -= cost;
  S.board[winner].push({ name, position: pos, nfl_team: p['Team']||'', rank: p['Rank'], cost, round: S.auctionRound+1 });
  S.drafted.add(pIdx);
  S.available = S.available.filter(i => i !== pIdx);

  // Update budget display
  $(`#budgetHead-${winner}`).text(`$${S.budgets[winner]}`);

  // Update team cell in board
  const existing = $(`#ateam-${winner}`).html();
  $(`#ateam-${winner}`).append(
    `<div style="font-size:0.72rem;padding:2px 0;border-bottom:1px solid #2d3d4d;">
      ${name} <span class="pos-badge pos-${pos}">${pos}</span> <span style="color:#2d8b8b;">$${cost}</span>
    </div>`
  );

  // Check if winner's roster is full
  if (S.board[winner].length >= S.totalRounds) {
    S.rosterFilled[winner] = true;
  }

  // Update your team if winner is user
  if (winner === S.userTeamIdx) {
    $('#userBudgetDisplay').text(`$${S.budgets[S.userTeamIdx]}`);
    updateAuctionYourTeam();
  }

  renderAuctionPlayerList(false);

  // Reset and move to next nomination
  S.currentNominee = null;
  S.currentBid = 0;
  S.currentBidder = -1;
  S.nomIdx++;
  S.auctionRound++;

  $('#biddingBlock').hide();
  $('#userBidControls').hide();

  checkAuctionComplete();
  if (!S.auctionComplete) {
    setTimeout(runNextNomination, 700);
  }
}

function checkAuctionComplete() {
  const allFull = S.rosterFilled.every(Boolean);
  const noPlayers = S.available.length === 0;
  if (allFull || noPlayers) {
    S.auctionComplete = true;
    endAuctionDraft();
  }
}

function updateAuctionYourTeam() {
  const slotDefs = buildSlotDefs();
  const picks = [...S.board[S.userTeamIdx]];
  const usedPickIdx = new Set();

  slotDefs.forEach((slot, i) => {
    const matchIdx = picks.findIndex((p, pi) =>
      !usedPickIdx.has(pi) && slot.pos.includes(p.position)
    );
    const $slot = $(`#aslot-${i}`);
    if (matchIdx !== -1) {
      usedPickIdx.add(matchIdx);
      const p = picks[matchIdx];
      $slot.addClass('filled').find('.slot-player').html(
        `${p.name} <span class="pos-badge pos-${p.position}">${p.position}</span>`
      );
      $slot.find('.slot-amount').remove();
      $slot.find('.slot-meta').remove();
      $slot.append(`<div class="slot-meta">${p.nfl_team}</div>`);
      $slot.append(`<div class="slot-amount">$${p.cost}</div>`);
    }
  });
}

function renderAuctionPlayerList(nominationMode) {
  const filterPos = $('#auctionPosFilter .pos-btn.active').data('pos') || 'ALL';
  const search    = ($('#auctionPlayerSearch').val() || '').toLowerCase();
  const $list     = $('#auctionPlayerList').empty();

  S.players.forEach((p, i) => {
    const pos  = (p['Position']||'').toUpperCase();
    const name = p['Name'] || p['Player'] || '';
    if (filterPos !== 'ALL' && pos !== filterPos) return;
    if (search && !name.toLowerCase().includes(search)) return;

    const drafted = S.drafted.has(i);
    const $row = $(`<div class="player-row${drafted ? ' drafted' : ''}" data-idx="${i}">
      <span class="player-rank">${p['Rank'] || i+1}</span>
      <div class="player-name-cell">
        <div class="player-name">${name}</div>
        <div class="player-sub">${p['Team']||''} · Rank #${p['Rank']||'?'}</div>
        ${buildPlayerUpdateMarkup(p['InjuryNews'])}
      </div>
      <span class="pos-badge pos-${pos}">${pos}</span>
    </div>`);

    if (!drafted && nominationMode) {
      $row.on('click', function () { userNominate(i); });
    }
    $list.append($row);
  });
}

function userNominate(playerIdx) {
  $('#userNominationControls').hide();
  openBidding(playerIdx, S.userTeamIdx);
  renderAuctionPlayerList(false);
}

function endAuctionDraft() {
  clearInterval(S.bidTimerInterval);
  S.auctionComplete = true;
  const boardData = buildAuctionBoardExport();
  const userTeam  = S.board[S.userTeamIdx];
  showPostDraft(boardData, userTeam);
}

// ── Post Draft ─────────────────────────────────────────────────
function buildBoardExport() {
  // Returns array of round objects for storage/email
  const rounds = [];
  for (let r = 0; r < S.totalRounds; r++) {
    const fwd = r % 2 === 0;
    const order = fwd
      ? Array.from({ length: S.numTeams }, (_, i) => i)
      : Array.from({ length: S.numTeams }, (_, i) => S.numTeams - 1 - i);
    const picks = order.map(t => S.board[t][r] || { name:'—', position:'', nfl_team:'' });
    rounds.push({ round: r + 1, picks });
  }
  return rounds;
}

function buildAuctionBoardExport() {
  return [{ round: 'Auction', picks: S.board.map(team => team) }];
}

function showPostDraft(boardData, userTeam) {
  $('#snakeDraft').hide();
  $('#auctionDraft').hide();
  $('#postDraft').show();

  // Store for save/email
  window._draftResult = {
    draft_type: S.draftType,
    scoring: S.scoring,
    settings: {
      num_teams: S.numTeams,
      slots: S.slots,
      pick_timer: S.pickTimer,
      auction_budget: S.auctionBudget,
      bid_time_limit: S.bidTimeLimit,
      user_slot: S.userSlot,
    },
    board: boardData,
    user_team: userTeam,
  };

  // Render final board summary
  renderFinalBoard(boardData);
}

function renderFinalBoard(boardData) {
  const $wrap = $('#finalBoardWrap');
  if (S.draftType === 'snake') {
    let html = '<table class="draft-board" style="margin-top:16px;font-size:0.72rem;">';
    html += '<thead><tr><th>Rd</th>';
    for (let t = 0; t < S.numTeams; t++) {
      const cls = t === S.userTeamIdx ? 'user-col' : '';
      html += `<th class="${cls}">${t === S.userTeamIdx ? 'YOU' : 'Team '+(t+1)}</th>`;
    }
    html += '</tr></thead><tbody>';
    for (const rd of boardData) {
      html += `<tr><td class="round-label">${rd.round}</td>`;
      for (const pick of rd.picks) {
        html += `<td><div class="cell-name">${pick.name||'—'}</div><div class="cell-meta"><span class="pos-badge pos-${pick.position||''}">${pick.position||''}</span></div></td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    $wrap.html(html);
  } else {
    let html = '<table class="auction-team-table" style="margin-top:16px;">';
    html += '<thead><tr>';
    for (let t = 0; t < S.numTeams; t++) {
      const cls = t === S.userTeamIdx ? 'user-col' : '';
      html += `<th class="${cls}">${t === S.userTeamIdx ? 'YOU' : 'Team '+(t+1)}</th>`;
    }
    html += '</tr></thead><tbody><tr>';
    for (let t = 0; t < S.numTeams; t++) {
      const cls = t === S.userTeamIdx ? 'user-col' : '';
      const picks = S.board[t];
      html += `<td class="${cls}" style="vertical-align:top;">`;
      for (const p of picks) {
        html += `<div style="font-size:0.72rem;padding:2px 0;border-bottom:1px solid #2d3d4d;">${p.name} <span class="pos-badge pos-${p.position}">${p.position}</span> <span style="color:#2d8b8b;">$${p.cost||0}</span></div>`;
      }
      html += '</td>';
    }
    html += '</tr></tbody></table>';
    $wrap.html(html);
  }
}

function saveDraft() {
  const scope = $('input[name="saveScope"]:checked').val();
  const data  = { ...window._draftResult };
  if (scope === 'team') data.board = [];

  $.ajax({
    url: '/mockdraft/save',
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify(data),
    success: function (res) {
      $('#postMessage').text(res.message || 'Saved!');
    },
    error: function () {
      $('#postMessage').text('Error saving draft.');
    }
  });
}

function emailDraft() {
  const scope = $('input[name="emailScope"]:checked').val();
  const data  = {
    ...window._draftResult,
    send_full: scope === 'full',
  };

  $.ajax({
    url: '/mockdraft/email',
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify(data),
    success: function (res) {
      $('#postMessage').text(res.message || 'Email sent!');
    },
    error: function (xhr) {
      const err = xhr.responseJSON && xhr.responseJSON.error ? xhr.responseJSON.error : 'Error sending email.';
      $('#postMessage').text(err);
    }
  });
}

// ── Utilities ───────────────────────────────────────────────────
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
