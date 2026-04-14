from flask import Blueprint, render_template, url_for, flash, redirect, request, jsonify, current_app as app
from flask_login import login_user, current_user, logout_user, login_required
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from bs4 import BeautifulSoup
from pathlib import Path
from webapp.forms import LoginForm, RegistrationForm
from webapp import db, User, UserRanking, MockDraft
import json

main = Blueprint('main', __name__)

_DB_PATH = Path(__file__).resolve().parent.parent / 'webapp' / 'my_database.db'
engine = create_engine(f'sqlite:///{_DB_PATH}', echo=True)

_BASE_DIR = Path(__file__).parent.parent
_PICKLE_DIR = _BASE_DIR / 'Models' / 'PickleFiles'

_TEAM_ABBR_MAP = {}

_player_details_cache = None
_team_schedule_cache = None


def _normalize_team(team):
    return _TEAM_ABBR_MAP.get(str(team), str(team))


def _get_player_details():
    global _player_details_cache
    if _player_details_cache is not None:
        return _player_details_cache

    details = {}

    # Age from currYearRoster
    roster_path = _PICKLE_DIR / 'currYearRoster.pkl'
    if roster_path.exists():
        roster_df = pd.read_pickle(roster_path)
        for _, row in roster_df.iterrows():
            name = str(row['Player']).strip()
            details[name] = {
                'age': int(row['Age']) if pd.notna(row['Age']) else None,
                'position': str(row['Pos']),
                'stats_year': None,
                'stats': {}
            }

    def _int(val):
        return int(val) if pd.notna(val) else 0

    def _float1(val):
        return round(float(val), 1) if pd.notna(val) else 0.0

    # QB stats (most recent season)
    qb_path = _PICKLE_DIR / 'final_qb_data.pkl'
    if qb_path.exists():
        df = pd.read_pickle(qb_path)
        df = df[df['season'] == df['season'].max()]
        if 'season_type' in df.columns:
            df = df[df['season_type'] == 'REG']
        for _, row in df.iterrows():
            name = str(row['player_display_name']).strip()
            stat = {
                'GP': _int(row['GP']),
                'completions': _int(row['completions']),
                'attempts': _int(row['attempts']),
                'passing_yards': _int(row['passing_yards']),
                'passing_tds': _int(row['passing_tds']),
                'interceptions': _int(row['interceptions']),
                'rushing_yards': _int(row['rushing_yards']),
                'rushing_tds': _int(row['rushing_tds']),
                'fantasy_points': _float1(row['fantasy_points']),
            }
            entry = details.setdefault(name, {'age': _int(row['age']) if pd.notna(row['age']) else None, 'position': 'QB', 'stats_year': None, 'stats': {}})
            entry['stats_year'] = int(row['season'])
            entry['stats'] = stat

    # RB stats
    rb_path = _PICKLE_DIR / 'final_rb_data.pkl'
    if rb_path.exists():
        df = pd.read_pickle(rb_path)
        df = df[df['season'] == df['season'].max()]
        if 'season_type' in df.columns:
            df = df[df['season_type'] == 'REG']
        for _, row in df.iterrows():
            name = str(row['player_display_name']).strip()
            stat = {
                'GP': _int(row['GP']),
                'carries': _int(row['carries']),
                'rushing_yards': _int(row['rushing_yards']),
                'rushing_tds': _int(row['rushing_tds']),
                'receptions': _int(row['receptions']),
                'targets': _int(row['targets']),
                'receiving_yards': _int(row['receiving_yards']),
                'receiving_tds': _int(row['receiving_tds']),
                'fantasy_points': _float1(row['fantasy_points']),
            }
            entry = details.setdefault(name, {'age': _int(row['age']) if pd.notna(row['age']) else None, 'position': 'RB', 'stats_year': None, 'stats': {}})
            entry['stats_year'] = int(row['season'])
            entry['stats'] = stat

    # WR/TE stats
    wrte_path = _PICKLE_DIR / 'final_wrte_data.pkl'
    if wrte_path.exists():
        df = pd.read_pickle(wrte_path)
        df = df[df['season'] == df['season'].max()]
        if 'season_type' in df.columns:
            df = df[df['season_type'] == 'REG']
        for _, row in df.iterrows():
            name = str(row['player_display_name']).strip()
            stat = {
                'GP': _int(row['GP']),
                'receptions': _int(row['receptions']),
                'targets': _int(row['targets']),
                'receiving_yards': _int(row['receiving_yards']),
                'receiving_tds': _int(row['receiving_tds']),
                'carries': _int(row['carries']),
                'rushing_yards': _int(row['rushing_yards']),
                'fantasy_points': _float1(row['fantasy_points']),
            }
            entry = details.setdefault(name, {'age': _int(row['age']) if pd.notna(row['age']) else None, 'position': str(row['position']), 'stats_year': None, 'stats': {}})
            entry['stats_year'] = int(row['season'])
            entry['stats'] = stat

    _player_details_cache = details
    return details


def _get_team_schedule():
    global _team_schedule_cache
    if _team_schedule_cache is not None:
        return _team_schedule_cache

    try:
        import nflreadpy
        schedule_df = nflreadpy.load_schedules([2025]).to_pandas()
        reg_df = schedule_df[schedule_df['game_type'] == 'REG'].sort_values('week')

        team_games = {}
        for _, row in reg_df.iterrows():
            week = int(row['week'])
            home = _normalize_team(row['home_team'])
            away = _normalize_team(row['away_team'])

            team_games.setdefault(home, [])
            if len(team_games[home]) < 5:
                team_games[home].append({'week': week, 'opponent': away, 'home_away': 'home'})

            team_games.setdefault(away, [])
            if len(team_games[away]) < 5:
                team_games[away].append({'week': week, 'opponent': home, 'home_away': 'away'})

        _team_schedule_cache = team_games
    except Exception as e:
        print(f'Warning: Could not load NFL schedule data: {e}')
        _team_schedule_cache = {}

    return _team_schedule_cache


def _ranking_extras(df):
    """Return player_details_json, team_schedule_json, teams, bye_weeks for a ranking df."""
    player_details = _get_player_details()
    team_schedule = _get_team_schedule()
    rows = df.to_dict(orient='records')
    teams = sorted(set(str(r['Team']) for r in rows if r.get('Team')))
    bye_weeks = sorted(set(int(r['Bye Week']) for r in rows if r.get('Bye Week') is not None))
    return (
        json.dumps(player_details),
        json.dumps(team_schedule),
        teams,
        bye_weeks,
    )

# Load stat data once at startup
_data_dir = Path(__file__).parent.parent / 'Models' / 'PickleFiles'

def _load(filename):
    try:
        return pd.read_pickle(_data_dir / filename)
    except Exception:
        return pd.DataFrame()

_rankings = _load('Full PPR Rankings with Weighted VBD.pkl')

# Load live seasonal stats from nflreadpy
_nfl_seasonal  = pd.DataFrame()
_nfl_latest    = pd.DataFrame()   # most-recent season with accurate position + team per player
_nfl_roster_map = {}
try:
    import nflreadpy
    from datetime import date as _date
    _today = _date.today()
    # NFL season Y runs Sep Y – Jan/Feb Y+1; before September the latest complete season is Y-1
    _nfl_end_year = _today.year if _today.month >= 9 else _today.year - 1

    # Try loading up to _nfl_end_year; if nflreadpy doesn't have that year yet, fall back one year
    _stats_raw = pd.DataFrame()
    for _try_year in [_nfl_end_year, _nfl_end_year - 1]:
        try:
            _seasons = list(range(2020, _try_year + 1))
            _stats_raw = nflreadpy.load_player_stats(_seasons, summary_level='reg').to_pandas()
            if not _stats_raw.empty:
                print(f'NFL stats loaded through season {_try_year}')
                break
        except Exception as _ye:
            print(f'NFL data unavailable for seasons through {_try_year}: {_ye}')

    if _stats_raw.empty:
        raise RuntimeError('Could not load NFL seasonal stats for any year')

    # nflreadpy player stats already includes player_name, position, recent_team — no roster merge needed
    _nfl_seasonal = _stats_raw.copy()

    # For grades + roster stats: use the most recent season actually present in the data
    _latest_season = int(_stats_raw['season'].max())
    _nfl_latest = (_stats_raw[_stats_raw['season'] == _latest_season]
                   .assign(_pos=lambda x: x['position'],
                           _team=lambda x: x['recent_team'],
                           _name=lambda x: x['player_display_name'])
                   .copy())
    print(f'NFL data ready: history 2020–{max(_seasons)}, grades/roster from season {_latest_season} ({len(_nfl_latest)} players)')
except Exception as e:
    print(f'Warning: could not load nflreadpy stats: {e}')


# ── Sleeper ADP ───────────────────────────────────────────────────────
import re as _re

def _normalize_name(name):
    n = str(name).lower().strip()
    n = _re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', n)
    n = _re.sub(r'[^a-z\s]', '', n)
    return n.strip()

def _fetch_sleeper_adp():
    try:
        resp = requests.get('https://api.sleeper.app/v1/players/nfl', timeout=15)
        resp.raise_for_status()
        players = resp.json()
        records = []
        for p in players.values():
            pos = p.get('fantasy_positions') or []
            if not any(x in pos for x in ('QB', 'RB', 'WR', 'TE')):
                continue
            rank = p.get('search_rank')
            if rank is None or rank == 9999999:
                continue
            name = p.get('full_name', '')
            if not name:
                continue
            records.append({'player_name': name, 'name_key': _normalize_name(name), 'adp_rank': int(rank)})
        df = pd.DataFrame(records).sort_values('adp_rank').reset_index(drop=True)
        print(f'Sleeper ADP loaded: {len(df)} players')
        return df
    except Exception as e:
        print(f'Warning: could not fetch Sleeper ADP: {e}')
        return pd.DataFrame(columns=['player_name', 'name_key', 'adp_rank'])

_sleeper_adp = _fetch_sleeper_adp()

# ── New model predictions (Phase 3) ──────────────────────────────────
_BASELINES = {'QB': 13, 'RB': 37, 'WR': 37, 'TE': 13}

def _load_model_rankings(scoring='ppr'):
    """
    scoring: 'ppr' | 'half_ppr' | 'standard'
    Half PPR subtracts 0.5 * rec_pg from PPR predicted PPG.
    Standard subtracts 1.0 * rec_pg.
    VBD is recalculated per scoring type.
    """
    try:
        _new_model_dir = _BASE_DIR / 'Models' / 'PickleFiles' / 'NewModel'
        combined = pd.read_pickle(_new_model_dir / 'combined_predictions_ppr.pkl')

        # Build rec_pg lookup from 2025 feature data (RB/WR/TE only; QB gets 0)
        rec_frames = []
        for pos in ('rb', 'wr', 'te'):
            feat = pd.read_pickle(_new_model_dir / f'{pos}_features.pkl')
            feat = feat[feat['season'] == feat['season'].max()][['player_name', 'receptions_pg']].copy()
            rec_frames.append(feat)
        rec_lookup = pd.concat(rec_frames, ignore_index=True).drop_duplicates('player_name')
        combined = combined.merge(rec_lookup, on='player_name', how='left')
        combined['receptions_pg'] = combined['receptions_pg'].fillna(0)

        # Adjust predicted PPG for scoring format
        if scoring == 'half_ppr':
            rec_deduct = 0.5
        elif scoring == 'standard':
            rec_deduct = 1.0
        else:
            rec_deduct = 0.0
        combined['predicted_ppg_2026'] = combined['predicted_ppg_2026'] - rec_deduct * combined['receptions_pg']
        combined['weighted_ppg']       = combined['weighted_ppg']       - rec_deduct * combined['receptions_pg']
        combined['ppg']                = combined['ppg']                - rec_deduct * combined['receptions_pg']

        # Recalculate VBD for this scoring format
        baseline_ppg = {}
        for pos, n in _BASELINES.items():
            pos_df = combined[combined['position'] == pos].sort_values('predicted_ppg_2026', ascending=False).reset_index(drop=True)
            if len(pos_df) >= n:
                baseline_ppg[pos] = pos_df.loc[n - 1, 'predicted_ppg_2026']
            elif not pos_df.empty:
                baseline_ppg[pos] = pos_df.iloc[-1]['predicted_ppg_2026']
            else:
                baseline_ppg[pos] = 0.0
        combined['vbd'] = (combined['predicted_ppg_2026'] - combined['position'].map(baseline_ppg)).round(2)
        combined = combined.sort_values('vbd', ascending=False).reset_index(drop=True)
        combined['rank'] = combined.index + 1

        # Join Sleeper ADP
        if not _sleeper_adp.empty:
            combined['name_key'] = combined['player_name'].apply(_normalize_name)
            adp_slim = _sleeper_adp[['name_key', 'adp_rank']].drop_duplicates('name_key')
            combined = combined.merge(adp_slim, on='name_key', how='left')
        else:
            combined['adp_rank'] = None

        combined = combined.rename(columns={
            'player_name':        'Name',
            'position':           'Position',
            'team':               'Team',
            'predicted_ppg_2026': 'Predicted PPG',
            'weighted_ppg':       'Weighted PPG',
            'ppg':                '2025 PPG',
            'vbd':                'VBD',
            'adp_rank':           'ADP',
        })
        combined['Predicted PPG'] = combined['Predicted PPG'].round(2)
        combined['Weighted PPG']  = combined['Weighted PPG'].round(2)
        combined['2025 PPG']      = combined['2025 PPG'].round(2)
        combined['Age']           = combined['age'].apply(lambda x: int(x) if pd.notna(x) and x != '' else '')
        combined['rank']          = combined['rank'].astype(int)

        # vs ADP: positive = we rank higher than consensus, negative = lower
        def _adp_diff(row):
            try:
                diff = int(row['ADP']) - int(row['rank'])
                return f'+{diff}' if diff > 0 else str(diff)
            except (TypeError, ValueError):
                return 'N/A'
        combined['vs ADP'] = combined.apply(_adp_diff, axis=1)
        combined['ADP'] = combined['ADP'].apply(lambda x: int(x) if pd.notna(x) else 'N/A')

        combined = combined[['rank', 'Name', 'Position', 'Team', 'Age', 'Predicted PPG', 'VBD', 'ADP', 'vs ADP', 'Weighted PPG', '2025 PPG']].copy()
        combined = combined.rename(columns={'rank': 'Rank'})
        print(f'Model rankings ({scoring}) loaded: {len(combined)} players')
        return combined
    except Exception as e:
        import traceback
        print(f'Warning: could not load model predictions ({scoring}): {e}')
        traceback.print_exc()
        return pd.DataFrame()

_model_data = {
    'ppr':      _load_model_rankings('ppr'),
    'half_ppr': _load_model_rankings('half_ppr'),
    'standard': _load_model_rankings('standard'),
}
_model_table = {k: v.to_dict(orient='records') if not v.empty else [] for k, v in _model_data.items()}
for k, v in _model_table.items():
    print(f'Model table ({k}): {len(v)} rows')

# ── Helpers shared by composite grades and roster stats ───────────
import math as _math

def _safe_f(v, digits=1):
    try:
        f = float(v)
        return round(f, digits) if not (_math.isnan(f) or _math.isinf(f)) else None
    except (TypeError, ValueError):
        return None

def _safe_i(v):
    r = _safe_f(v, 0)
    return int(r) if r is not None else None

def _find_team_col(df):
    for c in ['recent_team', 'team', 'Team', 'posteam']:
        if c in df.columns:
            return c
    return None

def _norm_team(t):
    t = str(t).strip().upper()
    return _TEAM_ABBR_MAP.get(t, t)

# ── Composite team grades from starter fantasy performance ─────────
def _compute_composite_grades():
    per_team = {}

    def _minmax_normalize(vals_dict, invert=False):
        if not vals_dict:
            return {}
        mn, mx = min(vals_dict.values()), max(vals_dict.values())
        rng = mx - mn if mx > mn else 1.0
        return {
            t: round(1.0 - (v - mn) / rng if invert else (v - mn) / rng, 2)
            for t, v in vals_dict.items()
        }

    use_live = (not _nfl_latest.empty
                and '_pos' in _nfl_latest.columns
                and '_team' in _nfl_latest.columns)

    if use_live:
        fpc = next((c for c in ['fantasy_points_ppr', 'fantasy_points'] if c in _nfl_latest.columns), None)
        gpc = next((c for c in ['games', 'GP'] if c in _nfl_latest.columns), None)

        if fpc and gpc:
            df = _nfl_latest.dropna(subset=['_pos', '_team']).copy()
            df['_team'] = df['_team'].apply(_norm_team)
            df['fpg']   = df[fpc] / df[gpc].clip(lower=1)

            def _process_live(pos_filter, pos_label, n_starters):
                pos_df = df[df['_pos'].str.upper() == pos_filter].copy()
                pos_df = pos_df.sort_values(fpc, ascending=False)
                top = pos_df.groupby('_team').head(n_starters)
                raw = {}
                for team, val in top.groupby('_team')['fpg'].mean().items():
                    sf = _safe_f(val, 3)
                    if sf is not None:
                        raw[team] = sf
                for team, v in _minmax_normalize(raw).items():
                    per_team.setdefault(team, {})[pos_label] = v

            _process_live('QB', 'QB', 1)
            _process_live('RB', 'RB', 2)
            _process_live('WR', 'WR', 3)
            _process_live('TE', 'TE', 2)

            # OLine proxy: team rushing YPC (top 2 RBs) + inverse sacks-per-game (QB)
            rb_df = df[df['_pos'] == 'RB'].copy()
            if 'rushing_yards' in rb_df.columns and 'carries' in rb_df.columns:
                rb_df = rb_df[rb_df['carries'].fillna(0) > 0]
                rb_df['ypc'] = rb_df['rushing_yards'] / rb_df['carries'].clip(lower=1)
                top_rb = rb_df.sort_values('rushing_yards', ascending=False).groupby('_team').head(2)
                ypc_by_team = top_rb.groupby('_team')['ypc'].mean()
            else:
                ypc_by_team = pd.Series(dtype=float)

            qb_df = df[df['_pos'] == 'QB'].copy()
            sack_col = next((c for c in ['sacks_suffered', 'sacks'] if c in qb_df.columns), None)
            if sack_col and gpc in qb_df.columns:
                qb_df['spg'] = qb_df[sack_col] / qb_df[gpc].clip(lower=1)
                top_qb = qb_df.sort_values(fpc, ascending=False).groupby('_team').head(1)
                spg_by_team = top_qb.groupby('_team')['spg'].mean()
            else:
                spg_by_team = pd.Series(dtype=float)

            all_teams = set(ypc_by_team.index) | set(spg_by_team.index)
            oline_raw = {}
            for team in all_teams:
                ypc_norm = _minmax_normalize(ypc_by_team.to_dict()).get(team, 0.5)
                spg_norm = _minmax_normalize(spg_by_team.to_dict(), invert=True).get(team, 0.5)
                oline_raw[team] = (ypc_norm + spg_norm) / 2.0
            for team, v in oline_raw.items():
                per_team.setdefault(team, {})['OLine'] = round(v, 2)

            # DST proxy: points allowed per game from 2025 schedule
            try:
                sched = nflreadpy.load_schedules([2025]).to_pandas()
                sched = sched.dropna(subset=['home_score', 'away_score', 'home_team', 'away_team'])
                pts_allowed = {}
                games_played = {}
                for _, row in sched.iterrows():
                    ht, at = _norm_team(row['home_team']), _norm_team(row['away_team'])
                    hs, as_ = float(row['home_score']), float(row['away_score'])
                    pts_allowed[ht] = pts_allowed.get(ht, 0) + as_
                    pts_allowed[at] = pts_allowed.get(at, 0) + hs
                    games_played[ht] = games_played.get(ht, 0) + 1
                    games_played[at] = games_played.get(at, 0) + 1
                dst_raw = {t: pts_allowed[t] / max(games_played[t], 1) for t in pts_allowed}
                for team, v in _minmax_normalize(dst_raw, invert=True).items():
                    per_team.setdefault(team, {})['DST'] = v
            except Exception as _de:
                print(f'Warning: could not compute DST grades: {_de}')

    else:
        # Fallback: pickle files
        def _process_pkl(df_raw, pos_label, n_starters, pos_filter=None):
            if df_raw.empty:
                return
            latest = df_raw['season'].max()
            st_col = 'season_type' if 'season_type' in df_raw.columns else None
            mask = df_raw['season'] == latest
            if st_col:
                mask = mask & (df_raw[st_col] == 'REG')
            df = df_raw[mask].copy()
            tc = _find_team_col(df)
            if tc is None or 'fantasy_points' not in df.columns or 'GP' not in df.columns:
                return
            df[tc] = df[tc].apply(_norm_team)
            df['fpg'] = df['fantasy_points'] / df['GP'].clip(lower=1)
            df_sorted = df.sort_values('fantasy_points', ascending=False)
            if pos_filter:
                pc = next((c for c in ['position', 'Position'] if c in df.columns), None)
                if pc:
                    df_sorted = df_sorted[df_sorted[pc].str.upper() == pos_filter]
            top = df_sorted.groupby(tc).head(n_starters)
            raw = {}
            for team, val in top.groupby(tc)['fpg'].mean().items():
                sf = _safe_f(val, 3)
                if sf is not None:
                    raw[team] = sf
            for team, v in _minmax_normalize(raw).items():
                per_team.setdefault(team, {})[pos_label] = v

        _process_pkl(_load('final_qb_data.pkl'), 'QB', 1)
        _process_pkl(_load('final_rb_data.pkl'), 'RB', 2)
        wrte = _load('final_wrte_data.pkl')
        _process_pkl(wrte, 'WR', 3, 'WR')
        _process_pkl(wrte, 'TE', 2, 'TE')

    # Ensure every team that appears in any grade has all 6 keys (fill missing with median)
    all_teams = set(per_team.keys())
    for grade_key in ['QB', 'RB', 'WR', 'TE', 'OLine', 'DST']:
        present = [per_team[t][grade_key] for t in all_teams if grade_key in per_team.get(t, {})]
        median = sorted(present)[len(present) // 2] if present else 0.5
        for team in all_teams:
            if grade_key not in per_team.get(team, {}):
                per_team.setdefault(team, {})[grade_key] = median

    return per_team

# ── Per-player stats for roster list view ─────────────────────────
def _compute_roster_stats():
    stats = {}

    # Prefer live nflreadpy data; fall back to pickle files
    use_live = (not _nfl_latest.empty
                and '_pos' in _nfl_latest.columns
                and '_team' in _nfl_latest.columns)

    if use_live:
        fpc = next((c for c in ['fantasy_points_ppr', 'fantasy_points'] if c in _nfl_latest.columns), None)
        gpc = next((c for c in ['games', 'GP'] if c in _nfl_latest.columns), None)

        if fpc and gpc:
            df = _nfl_latest.dropna(subset=['_pos', '_team', '_name']).copy()
            for _, row in df.iterrows():
                name = str(row.get('_name', '')).strip()
                if not name:
                    continue
                pos = str(row.get('_pos', '')).upper().strip()
                if pos not in ('QB', 'RB', 'WR', 'TE'):
                    continue
                team = _norm_team(row.get('_team', ''))
                gp   = max(_safe_i(row.get(gpc, 1)) or 1, 1)
                fp   = _safe_f(row.get(fpc))

                if pos == 'QB':
                    stats[name] = {
                        'pos': 'QB', 'team': team, 'gp': gp,
                        'fantasy_points': fp,
                        'pass_yds': _safe_i(row.get('passing_yards')),
                        'pass_td':  _safe_i(row.get('passing_tds')),
                        'int':      _safe_i(row.get('passing_interceptions')),
                        'rush_yds': _safe_i(row.get('rushing_yards')),
                    }
                elif pos == 'RB':
                    carries  = _safe_i(row.get('carries', 1)) or 1
                    rush_yds = _safe_i(row.get('rushing_yards', 0)) or 0
                    stats[name] = {
                        'pos': 'RB', 'team': team, 'gp': gp,
                        'fantasy_points': fp,
                        'rush_yds': rush_yds,
                        'ypc':      round(rush_yds / carries, 1) if carries > 0 else None,
                        'rec':      _safe_i(row.get('receptions')),
                        'rec_yds':  _safe_i(row.get('receiving_yards')),
                    }
                else:  # WR / TE
                    tgts = _safe_i(row.get('targets'))
                    rec  = _safe_i(row.get('receptions'))
                    stats[name] = {
                        'pos': pos, 'team': team, 'gp': gp,
                        'fantasy_points': fp,
                        'targets':    tgts,
                        'receptions': rec,
                        'catch_pct':  round(rec / tgts * 100, 1) if tgts and tgts > 0 and rec is not None else None,
                        'rec_yds':    _safe_i(row.get('receiving_yards')),
                    }

    else:
        # Fallback: pickle files (2023 data)
        def _team_pkl(row, tc):
            return _norm_team(row.get(tc, '')) if tc else ''

        qb_df = _load('final_qb_data.pkl')
        if not qb_df.empty:
            df = qb_df[qb_df['season'] == qb_df['season'].max()]
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            tc = _find_team_col(df)
            for _, row in df.iterrows():
                name = str(row.get('player_display_name', '')).strip()
                if not name:
                    continue
                rush_yds = _safe_i(row.get('rushing_yards', 0)) or 0
                stats[name] = {
                    'pos': 'QB', 'team': _team_pkl(row, tc),
                    'gp': _safe_i(row.get('GP', 1)) or 1,
                    'fantasy_points': _safe_f(row.get('fantasy_points')),
                    'pass_yds': _safe_i(row.get('passing_yards')),
                    'pass_td':  _safe_i(row.get('passing_tds')),
                    'int':      _safe_i(row.get('interceptions')),
                    'rush_yds': rush_yds,
                }

        rb_df = _load('final_rb_data.pkl')
        if not rb_df.empty:
            df = rb_df[rb_df['season'] == rb_df['season'].max()]
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            tc = _find_team_col(df)
            for _, row in df.iterrows():
                name = str(row.get('player_display_name', '')).strip()
                if not name:
                    continue
                carries  = _safe_i(row.get('carries', 1)) or 1
                rush_yds = _safe_i(row.get('rushing_yards', 0)) or 0
                stats[name] = {
                    'pos': 'RB', 'team': _team_pkl(row, tc),
                    'gp': _safe_i(row.get('GP', 1)) or 1,
                    'fantasy_points': _safe_f(row.get('fantasy_points')),
                    'rush_yds': rush_yds,
                    'ypc':      round(rush_yds / carries, 1) if carries > 0 else None,
                    'rec':      _safe_i(row.get('receptions')),
                    'rec_yds':  _safe_i(row.get('receiving_yards')),
                }

        wrte_df = _load('final_wrte_data.pkl')
        if not wrte_df.empty:
            df = wrte_df[wrte_df['season'] == wrte_df['season'].max()]
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            tc = _find_team_col(df)
            pc = next((c for c in ['position', 'Position'] if c in df.columns), None)
            for _, row in df.iterrows():
                name = str(row.get('player_display_name', '')).strip()
                if not name:
                    continue
                pos  = str(row.get(pc, 'WR')).upper() if pc else 'WR'
                tgts = _safe_i(row.get('targets'))
                rec  = _safe_i(row.get('receptions'))
                stats[name] = {
                    'pos': pos, 'team': _team_pkl(row, tc),
                    'gp': _safe_i(row.get('GP', 1)) or 1,
                    'fantasy_points': _safe_f(row.get('fantasy_points')),
                    'targets':    tgts,
                    'receptions': rec,
                    'catch_pct':  round(rec / tgts * 100, 1) if tgts and tgts > 0 and rec is not None else None,
                    'rec_yds':    _safe_i(row.get('receiving_yards')),
                }

    # Fantasy-point thresholds per position for color coding
    fp_thresholds = {}
    for pos in ['QB', 'RB', 'WR', 'TE']:
        fps = sorted(v['fantasy_points'] for v in stats.values()
                     if v.get('pos') == pos and v.get('fantasy_points') is not None)
        if fps:
            n = len(fps)
            fp_thresholds[pos] = {'p25': fps[n // 4], 'p75': fps[3 * n // 4]}

    return stats, fp_thresholds

_composite_grades  = _compute_composite_grades()
_roster_stats, _fp_thresholds = _compute_roster_stats()

# Load stat data once at startup
_data_dir = Path(__file__).parent.parent / 'Models' / 'PickleFiles'

def _load(filename):
    try:
        return pd.read_pickle(_data_dir / filename)
    except Exception:
        return pd.DataFrame()

_qb_stats    = _load('final_qb_data.pkl')
_rb_stats    = _load('final_rb_data.pkl')
_wrte_stats  = _load('final_wrte_data.pkl')
_qb_model    = _load('QBDFForModelPPR.pkl')
_rb_model    = _load('RBDFForModelPPR.pkl')
_wrte_model  = _load('WRTEDFForModelPPR.pkl')
_rankings    = _load('Full PPR Rankings with Weighted VBD.pkl')

@main.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(id=form.username.data).first()
        if user and user.password == form.password.data:
            login_user(user)
            return redirect(url_for('main.home'))
        else:
            flash('Invalid username or password')
    return render_template('login.html', form=form)

@main.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('main.login'))

@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('An account with that email already exists.')
            return render_template('register.html', form=form)
        if User.query.filter_by(id=form.username.data).first():
            flash('That username is already taken.')
            return render_template('register.html', form=form)
        user = User(id=form.username.data, email=form.email.data, password=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Thanks for registering! Please log in.')
        return redirect(url_for('main.login'))
    return render_template('register.html', form=form)

@main.route('/home')
@login_required
def home():
    return render_template('home.html')

@main.route('/about')
def about():
    return render_template('about.html')

@main.route('/contact')
def contact():
    return render_template('contact.html')

@main.route('/rankings', methods=['GET', 'POST'])
@login_required
def rankings():
    return redirect(url_for('main.get_ppr_rankings'))

@main.route('/rankings/ppr')
@login_required
def get_ppr_rankings():
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_model_table['ppr'], table_type='PPR',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/rankings/half-ppr')
@login_required
def get_half_ppr_rankings():
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_model_table['half_ppr'], table_type='Half PPR',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/rankings/standard')
@login_required
def get_standard_rankings():
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_model_table['standard'], table_type='Standard',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/rankings/new-model')
@login_required
def get_new_model_rankings():
    return redirect(url_for('main.get_ppr_rankings'))

@main.route('/save_rankings', methods=['POST'])
@login_required
def save_rankings():
    data = request.get_json()
    ranking_data = data.get('ranking', [])
    ranking_type = data.get('ranking_type', 'Custom')
    name = data.get('name', 'Untitled')

    # Check for duplicate name
    existing = UserRanking.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        return jsonify({'error': 'A ranking with that name already exists. Please choose a different name.'}), 400

    # Convert ranking data to JSON format
    ranking_json = json.dumps(ranking_data)

    # Save the ranking to the database
    user_ranking = UserRanking(user_id=current_user.id, name=name, ranking_type=ranking_type, ranking_data=ranking_json)
    db.session.add(user_ranking)
    db.session.commit()

    return jsonify({'message': 'Rankings saved successfully!', 'ranking_id': user_ranking.id})

@main.route('/update_ranking/<int:ranking_id>', methods=['PUT'])
@login_required
def update_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    ranking_data = data.get('ranking', [])
    ranking.ranking_data = json.dumps(ranking_data)
    db.session.commit()
    return jsonify({'message': 'Ranking updated successfully!'})

@main.route('/rankings/saved/<int:ranking_id>')
@login_required
def view_saved_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != current_user.id:
        flash('Access denied.')
        return redirect(url_for('main.rankings'))
    # Parse the saved JSON data back into table format
    rows = json.loads(ranking.ranking_data)
    # Get column headers from the ranking type's original table
    header_map = {'PPR': 'Full_PPR', 'Half PPR': 'Half_PPR', 'Standard': 'Non_PPR'}
    table_name = header_map.get(ranking.ranking_type, 'Full_PPR')
    with engine.connect() as connection:
        df = pd.read_sql(text(f'SELECT * FROM {table_name} LIMIT 1'), con=connection)
    headers = list(df.columns)
    # Convert rows back to list of dicts
    table_data = []
    for row in rows:
        row_dict = {}
        for i, header in enumerate(headers):
            row_dict[header] = row[i] if i < len(row) else ''
        table_data.append(row_dict)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    player_details = _get_player_details()
    team_schedule = _get_team_schedule()
    teams = sorted(set(str(r.get('Team', '')) for r in table_data if r.get('Team')))
    bye_weeks = sorted(set(int(r['Bye Week']) for r in table_data if r.get('Bye Week') is not None))
    return render_template('rankings.html', table_data=table_data, table_type=ranking.name,
                           user_rankings=saved, saved_ranking_id=ranking.id, saved_ranking_name=ranking.name,
                           player_details_json=json.dumps(player_details),
                           team_schedule_json=json.dumps(team_schedule),
                           teams=teams, bye_weeks=bye_weeks)

@main.route('/user_rankings')
@login_required
def user_rankings():
    # Retrieve all rankings for the current user
    user_rankings = UserRanking.query.filter_by(user_id=current_user.id).all()
    return render_template('user_rankings.html', user_rankings=user_rankings)

@main.route('/delete_ranking/<int:ranking_id>', methods=['DELETE'])
@login_required
def delete_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    db.session.delete(ranking)
    db.session.commit()
    return jsonify({'message': 'Ranking deleted successfully!'})

@main.route('/player_stats')
@login_required
def player_stats():
    name = request.args.get('name', '').strip()
    pos  = request.args.get('pos', '').strip().upper()
    team = request.args.get('team', '').strip().upper()

    if not name:
        return jsonify({})

    # --- Historical stats from nflreadpy (2020–2025) ---
    import math as _m

    def _clean_hist(df):
        return [
            {k: (None if isinstance(v, float) and _m.isnan(v) else v) for k, v in row.items()}
            for row in df.to_dict(orient='records')
        ]

    history = []
    if not _nfl_seasonal.empty:
        player_rows = _nfl_seasonal[_nfl_seasonal['player_display_name'] == name].sort_values('season')
        if pos == 'QB':
            cols = ['season', 'games', 'completions', 'attempts', 'passing_yards',
                    'passing_tds', 'passing_interceptions', 'rushing_yards', 'rushing_tds', 'fantasy_points_ppr']
        elif pos == 'RB':
            cols = ['season', 'games', 'carries', 'rushing_yards', 'rushing_tds',
                    'receptions', 'targets', 'receiving_yards', 'receiving_tds', 'fantasy_points_ppr']
        else:  # WR / TE
            cols = ['season', 'games', 'receptions', 'targets', 'receiving_yards',
                    'receiving_tds', 'target_share', 'air_yards_share', 'fantasy_points_ppr']

        available = [c for c in cols if c in player_rows.columns]
        hist = player_rows[available].tail(5).round(1)
        hist = hist.rename(columns={'games': 'GP', 'fantasy_points_ppr': 'fantasy_points'})
        history = _clean_hist(hist)

    # Fallback: build history from pkl files when nflreadpy is unavailable
    if not history:
        pkl_map = {'QB': 'final_qb_data.pkl', 'RB': 'final_rb_data.pkl',
                   'WR': 'final_wrte_data.pkl', 'TE': 'final_wrte_data.pkl'}
        pkl_file = pkl_map.get(pos)
        if pkl_file:
            pkl_path = _PICKLE_DIR / pkl_file
            if pkl_path.exists():
                pkl_df = pd.read_pickle(pkl_path)
                player_rows = pkl_df[pkl_df['player_display_name'] == name].sort_values('season')
                if pos == 'QB':
                    cols = ['season', 'GP', 'completions', 'attempts', 'passing_yards',
                            'passing_tds', 'interceptions', 'rushing_yards', 'rushing_tds', 'fantasy_points']
                elif pos == 'RB':
                    cols = ['season', 'GP', 'carries', 'rushing_yards', 'rushing_tds',
                            'receptions', 'targets', 'receiving_yards', 'receiving_tds', 'fantasy_points']
                else:
                    cols = ['season', 'GP', 'receptions', 'targets', 'receiving_yards',
                            'receiving_tds', 'fantasy_points']
                available = [c for c in cols if c in player_rows.columns]
                hist = player_rows[available].tail(5).round(1)
                history = _clean_hist(hist)

    # --- Rankings info ---
    rank_row = _rankings[_rankings['Name'] == name]
    ranking = {}
    if not rank_row.empty:
        r = rank_row.iloc[0]
        ranking = {
            'Rank': int(r['Rank']),
            'Final PPG': round(float(r['Final PPG']), 2) if pd.notna(r['Final PPG']) else None,
            'ESPN ADP': round(float(r['ESPN ADP']), 1) if pd.notna(r['ESPN ADP']) else None,
            'VBD': round(float(r['VBD']), 2) if pd.notna(r['VBD']) else None,
            'Bye Week': int(r['Bye Week']) if pd.notna(r['Bye Week']) else None,
        }

    # --- Team grade (composite from starter fantasy performance) ---
    team_grade = {}
    if team and team in _composite_grades:
        cg = _composite_grades[team]
        team_grade = {
            'OLine': cg.get('OLine'),
            'QB':    cg.get('QB'),
            'RB':    cg.get('RB'),
            'WR':    cg.get('WR'),
            'TE':    cg.get('TE'),
            'DST':   cg.get('DST'),
        }

    return jsonify({
        'history': history,
        'ranking': ranking,
        'team_grade': team_grade,
    })


@main.route('/player_quick_stats')
@login_required
def player_quick_stats():
    name = request.args.get('name', '').strip()
    pos  = request.args.get('pos', '').strip().upper()
    team = request.args.get('team', '').strip().upper()

    if not name:
        return jsonify({})

    # Look up espn_id and bio from teamsPastRoster.pkl
    espn_id = None
    bio = {}
    try:
        roster_path = Path(app.root_path) / 'data' / 'teamsPastRoster.pkl'
        if roster_path.exists():
            roster_df = pd.read_pickle(roster_path)
            match = roster_df[roster_df['Player'] == name]
            if not match.empty:
                _r = match.iloc[0]
                raw_id = _r['espn_id']
                if raw_id is not None and str(raw_id) not in ('', 'nan', 'None'):
                    espn_id = str(raw_id)
                def _sv(v):
                    return str(v) if pd.notna(v) and str(v) not in ('nan', 'None', '') else '—'
                bio = {
                    'Team':             _sv(_r.get('Team')),
                    'Position':         _sv(_r.get('Pos')),
                    'Height':           _sv(_r.get('height')),
                    'Weight':           _sv(_r.get('weight')),
                    'Birth Date':       _sv(_r.get('BirthDate')),
                    'College':          _sv(_r.get('College')),
                    'Rookie Season':    _sv(_r.get('RookieSeason')),
                    'Experience (yrs)': _sv(_r.get('ExperienceYears')),
                    'Jersey #':         _sv(_r.get('Jersey')),
                    'Draft Year':       _sv(_r.get('DraftYear')),
                    'Round':            _sv(_r.get('DraftRound')),
                    'Pick':             _sv(_r.get('DraftPick')),
                    'Draft Team':       _sv(_r.get('DraftTeam')),
                }
    except Exception as _e:
        print(f'Warning: could not look up espn_id: {_e}')

    # Get 2025 stats from _nfl_seasonal
    stats = {}
    fantasy_points = None
    games = None
    if not _nfl_seasonal.empty:
        player_rows = _nfl_seasonal[
            (_nfl_seasonal['player_display_name'] == name) &
            (_nfl_seasonal['season'] == 2025)
        ]
        if not player_rows.empty:
            row = player_rows.iloc[0]
            def _gs(col):
                v = row.get(col)
                if v is None:
                    return None
                try:
                    import math as _m
                    f = float(v)
                    return None if _m.isnan(f) or _m.isinf(f) else (int(f) if f == int(f) else round(f, 1))
                except (TypeError, ValueError):
                    return None

            games = _gs('games')
            fpp = _gs('fantasy_points_ppr')
            fantasy_points = fpp

            if pos == 'QB':
                stats = {
                    'completions': _gs('completions'),
                    'attempts': _gs('attempts'),
                    'passing_yards': _gs('passing_yards'),
                    'passing_tds': _gs('passing_tds'),
                    'passing_interceptions': _gs('passing_interceptions'),
                    'rushing_yards': _gs('rushing_yards'),
                    'rushing_tds': _gs('rushing_tds'),
                    'games': games,
                }
            elif pos == 'RB':
                stats = {
                    'carries': _gs('carries'),
                    'rushing_yards': _gs('rushing_yards'),
                    'rushing_tds': _gs('rushing_tds'),
                    'receptions': _gs('receptions'),
                    'targets': _gs('targets'),
                    'receiving_yards': _gs('receiving_yards'),
                    'receiving_tds': _gs('receiving_tds'),
                    'games': games,
                }
            else:  # WR / TE
                stats = {
                    'receptions': _gs('receptions'),
                    'targets': _gs('targets'),
                    'receiving_yards': _gs('receiving_yards'),
                    'receiving_tds': _gs('receiving_tds'),
                    'games': games,
                }

    # Get ranking info from _model_table['ppr']
    ranking = {}
    for row in _model_table.get('ppr', []):
        if row.get('Name') == name:
            ranking = {
                'predicted_ppg': row.get('Predicted PPG'),
                'vbd': row.get('VBD'),
                'adp': row.get('ADP'),
            }
            break

    return jsonify({
        'espn_id': espn_id,
        'bio': bio,
        'stats': stats,
        'fantasy_points': fantasy_points,
        'ranking': ranking,
    })


@main.route('/player/<path:name>')
@login_required
def player_profile(name):
    pos     = request.args.get('pos', '').strip().upper()
    team    = request.args.get('team', '').strip().upper()
    compare = request.args.get('compare', 'false').lower() == 'true'
    back_url = request.args.get('back', '/rankings/ppr')

    # Look up player bio from teamsPastRoster.pkl
    espn_id = None
    player_bio = {}
    try:
        roster_path = Path(app.root_path) / 'data' / 'teamsPastRoster.pkl'
        if roster_path.exists():
            roster_df = pd.read_pickle(roster_path)
            match = roster_df[roster_df['Player'] == name]
            if not match.empty:
                row = match.iloc[0]
                raw_id = row.get('espn_id')
                if raw_id is not None and str(raw_id) not in ('', 'nan', 'None'):
                    espn_id = str(raw_id)
                def _sv(v):
                    return str(v) if pd.notna(v) and str(v) not in ('nan', 'None', '') else '—'
                player_bio = {
                    'Team':         _sv(row.get('Team')),
                    'Position':     _sv(row.get('Pos')),
                    'Height':       _sv(row.get('height')),
                    'Weight':       _sv(row.get('weight')),
                    'Birth Date':   _sv(row.get('BirthDate')),
                    'College':      _sv(row.get('College')),
                    'Rookie Season':_sv(row.get('RookieSeason')),
                    'Experience (yrs)': _sv(row.get('ExperienceYears')),
                    'Jersey #':     _sv(row.get('Jersey')),
                    'Draft Year':   _sv(row.get('DraftYear')),
                    'Round':        _sv(row.get('DraftRound')),
                    'Pick':         _sv(row.get('DraftPick')),
                    'Draft Team':   _sv(row.get('DraftTeam')),
                }
    except Exception as _e:
        print(f'Warning: could not look up player bio: {_e}')

    return render_template(
        'player_profile.html',
        player_name=name,
        pos=pos,
        team=team,
        espn_id=espn_id or '',
        player_bio=player_bio,
        roster_stats_json=json.dumps(_roster_stats),
        fp_thresholds_json=json.dumps(_fp_thresholds),
        back_url=back_url,
        compare=compare,
    )


@main.route('/mockdraft')
@login_required
def mock_draft():
    return render_template('mockdraft.html')


@main.route('/mockdraft/players')
@login_required
def mockdraft_players():
    import math
    scoring = request.args.get('scoring', 'ppr')
    records = _model_table.get(scoring) or _model_table.get('ppr') or []
    if not records:
        return jsonify([])
    players = []
    for row in records:
        pos = (row.get('Position') or '').replace(r'\d+$', '').strip().upper()
        import re
        pos = re.sub(r'\d+$', '', pos).strip()
        if pos in ('K', 'DEF', 'DST'):
            continue
        players.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()})
    return jsonify(players)


@main.route('/mockdraft/save', methods=['POST'])
@login_required
def mockdraft_save():
    data = request.get_json()
    draft = MockDraft(
        user_id=current_user.id,
        draft_type=data.get('draft_type', 'snake'),
        scoring=data.get('scoring', 'ppr'),
        settings=json.dumps(data.get('settings', {})),
        board=json.dumps(data.get('board', [])),
        user_team=json.dumps(data.get('user_team', [])),
    )
    db.session.add(draft)
    db.session.commit()
    return jsonify({'message': 'Draft saved!', 'id': draft.id})


@main.route('/mockdraft/email', methods=['POST'])
@login_required
def mockdraft_email():
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    data = request.get_json()
    send_full = data.get('send_full', False)
    board = data.get('board', [])
    user_team = data.get('user_team', [])
    scoring = data.get('scoring', 'ppr')
    draft_type = data.get('draft_type', 'snake')
    settings = data.get('settings', {})

    # Build HTML email
    from datetime import date
    subject = f"Darkhorse Mock Draft — {date.today().strftime('%Y-%m-%d')} — {scoring.upper()} {draft_type.capitalize()}"

    if send_full:
        content = _build_board_html(board, settings)
    else:
        content = _build_team_html(user_team, scoring)

    html_body = f"""
    <html><body style="background:#1a2332;color:#f1faee;font-family:Arial,sans-serif;padding:20px;">
    <h2 style="color:#2d8b8b;">Darkhorse Mock Draft Results</h2>
    <p style="color:#a8dadc;">{scoring.upper()} | {draft_type.capitalize()} | {date.today().strftime('%B %d, %Y')}</p>
    {content}
    </body></html>
    """

    try:
        smtp_host = app.config.get('MAIL_SERVER', '')
        smtp_port = int(app.config.get('MAIL_PORT', 587))
        smtp_user = app.config.get('MAIL_USERNAME', '')
        smtp_pass = app.config.get('MAIL_PASSWORD', '')

        if not smtp_host or not smtp_user:
            return jsonify({'message': 'Email sent (email server not configured — draft saved instead).'}), 200

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = current_user.email
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, current_user.email, msg.as_string())

        return jsonify({'message': f'Draft emailed to {current_user.email}!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_board_html(board, settings):
    if not board:
        return '<p>No draft data.</p>'
    num_teams = settings.get('num_teams', len(board))
    team_names = [f'Team {i+1}' for i in range(num_teams)]
    html = '<table style="border-collapse:collapse;width:100%;">'
    html += '<tr><th style="padding:6px;border:1px solid #2d8b8b;">Round</th>'
    for t in team_names:
        html += f'<th style="padding:6px;border:1px solid #2d8b8b;color:#a8dadc;">{t}</th>'
    html += '</tr>'
    for round_picks in board:
        html += '<tr>'
        html += f'<td style="padding:6px;border:1px solid #2d8b8b;color:#a8dadc;">{round_picks.get("round","")}</td>'
        for pick in round_picks.get('picks', []):
            html += f'<td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("name","—")} <span style="color:#a8dadc;">({pick.get("position","")})</span></td>'
        html += '</tr>'
    html += '</table>'
    return html


def _build_team_html(user_team, scoring):
    if not user_team:
        return '<p>No picks.</p>'
    html = '<table style="border-collapse:collapse;width:60%;">'
    html += '<tr><th style="padding:6px;border:1px solid #2d8b8b;">Round</th><th style="padding:6px;border:1px solid #2d8b8b;">Player</th><th style="padding:6px;border:1px solid #2d8b8b;">Position</th><th style="padding:6px;border:1px solid #2d8b8b;">Team</th></tr>'
    for pick in user_team:
        html += f'<tr><td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("round","")}</td><td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("name","")}</td><td style="padding:6px;border:1px solid #2d8b8b;color:#a8dadc;">{pick.get("position","")}</td><td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("nfl_team","")}</td></tr>'
    html += '</table>'
    return html


@main.route('/my_drafts')
@login_required
def my_drafts():
    drafts = MockDraft.query.filter_by(user_id=current_user.id).order_by(MockDraft.created_at.desc()).all()
    draft_list = []
    for d in drafts:
        settings = json.loads(d.settings)
        draft_list.append({
            'id': d.id,
            'draft_type': d.draft_type,
            'scoring': d.scoring,
            'created_at': d.created_at.strftime('%Y-%m-%d %H:%M'),
            'num_teams': settings.get('num_teams', '?'),
        })
    return render_template('my_drafts.html', drafts=draft_list)


@main.route('/my_drafts/<int:draft_id>')
@login_required
def view_draft(draft_id):
    draft = MockDraft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        flash('Access denied.')
        return redirect(url_for('main.my_drafts'))
    return render_template('view_draft.html',
        draft=draft,
        board=json.loads(draft.board),
        user_team=json.loads(draft.user_team),
        settings=json.loads(draft.settings),
    )


@main.route('/my_drafts/<int:draft_id>/delete', methods=['DELETE'])
@login_required
def delete_draft(draft_id):
    draft = MockDraft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    db.session.delete(draft)
    db.session.commit()
    return jsonify({'message': 'Draft deleted.'})


@main.route('/rosters')
@login_required
def rosters():
    data_path = Path(app.root_path) / 'data' / 'teamsPastRoster.pkl'

    if not data_path.exists():
        flash('Roster file not found. Please generate teamsPastRoster.pkl first.')
        return redirect(url_for('main.home'))

    df = pd.read_pickle(data_path)

    return render_template(
        'rosters.html',
        table_data=df.to_dict(orient='records'),
        columns=df.columns.tolist(),
        roster_stats_json=json.dumps(_roster_stats),
        fp_thresholds_json=json.dumps(_fp_thresholds),
    )

def fetch_player_data():
    url = 'https://www.footballguys.com/adp'
    response = requests.get(url)
    player_data = []
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            name_td = row.find('td', class_='name sticky-col text-start text-nowrap')
            if name_td:
                name_a = name_td.find('a')
                if name_a:
                    player_name = name_a.get_text().strip()
                    tds = row.find_all('td')
                    if len(tds) >= 15:
                        adp_value = tds[14].get_text().strip()
                        if adp_value != '-':
                            player_data.append((player_name, adp_value))
        player_data_sorted = sorted(player_data, key=lambda x: int(x[1]) if x[1].isdigit() else float('inf'))
        return player_data_sorted
    else:
        return []
