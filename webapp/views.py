from flask import Blueprint, render_template, url_for, flash, redirect, request, jsonify, current_app as app, g, abort
from webapp import supabase_auth
from webapp.supabase_auth import login_required
import os
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from bs4 import BeautifulSoup
from pathlib import Path
from webapp.forms import LoginForm, RegistrationForm
from webapp import db, User, UserRanking, MockDraft, DraftBoardSession, SavedLeague, _csrf as csrf
import json
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET


def _enable_numpy_pickle_compat():
    """Allow loading pickles created with numpy 2.x on numpy 1.x runtimes."""
    try:
        import numpy.core as _np_core  # type: ignore
        import numpy.core.numeric as _np_core_numeric  # type: ignore

        # Older pickles can reference numpy._core.* modules.
        sys.modules.setdefault('numpy._core', _np_core)
        sys.modules.setdefault('numpy._core.numeric', _np_core_numeric)
    except Exception:
        # Best effort only; failures should not block app startup.
        pass


_enable_numpy_pickle_compat()

main = Blueprint('main', __name__)


_DB_PATH = Path(__file__).resolve().parent.parent / 'webapp' / 'my_database.db'
engine = create_engine(f'sqlite:///{_DB_PATH}', echo=True)

_BASE_DIR = Path(__file__).parent.parent
_PICKLE_DIR = _BASE_DIR / 'Models' / 'PickleFiles'

_TEAM_ABBR_MAP = {
    'LA': 'LAR',  # Los Angeles Rams
    'LV': 'LV',   # Las Vegas Raiders (already correct)
    'ARZ': 'ARI', # Arizona Cardinals
    'BLT': 'BAL', # Baltimore Ravens
    'CLV': 'CLE', # Cleveland Browns
    'HST': 'HOU', # Houston Texans
}

_TEAM_NAME_MAP = {
    'ARI': 'Arizona Cardinals',
    'ATL': 'Atlanta Falcons',
    'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers',
    'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals',
    'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions',
    'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans',
    'IND': 'Indianapolis Colts',
    'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs',
    'LAC': 'Los Angeles Chargers',
    'LAR': 'Los Angeles Rams',
    'LV': 'Las Vegas Raiders',
    'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings',
    'NE': 'New England Patriots',
    'NO': 'New Orleans Saints',
    'NYG': 'New York Giants',
    'NYJ': 'New York Jets',
    'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers',
    'SEA': 'Seattle Seahawks',
    'SF': 'San Francisco 49ers',
    'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders',
}

_player_details_cache = None
_team_schedule_cache = None


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
            home = _norm_team(row['home_team'])
            away = _norm_team(row['away_team'])

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

    # Try loading full history back to 1999 (earliest nflreadpy year); fall back one year at a time if needed
    _stats_raw = pd.DataFrame()
    _history_start = 1999
    for _try_year in [_nfl_end_year, _nfl_end_year - 1]:
        try:
            _seasons = list(range(_history_start, _try_year + 1))
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
    print(f'NFL data ready: history {_history_start}–{max(_seasons)}, grades/roster from season {_latest_season} ({len(_nfl_latest)} players)')
except Exception as e:
    print(f'Warning: could not load nflreadpy stats: {e}')

# Load name→espn_id and name→bio maps from pre-generated JSON cache
_espn_id_map = {}
_bio_map = {}
try:
    import json as _json
    _cache_dir = _BASE_DIR / 'Models' / 'PickleFiles'
    with open(_cache_dir / 'espn_id_map.json') as _f:
        _espn_id_map = _json.load(_f)
    with open(_cache_dir / 'bio_map.json') as _f:
        _bio_map = _json.load(_f)
    print(f'ESPN ID map: {len(_espn_id_map)} players | Bio map: {len(_bio_map)} players')
except Exception as _e:
    print(f'ESPN ID map unavailable: {_e}')


# ── ADP helpers ───────────────────────────────────────────────────────
import re as _re

def _normalize_name(name):
    n = str(name).lower().strip()
    n = _re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', n)
    n = _re.sub(r'[^a-z\s]', '', n)
    return n.strip()


def _clean_text(value):
    try:
        if pd.isna(value):
            return ''
    except TypeError:
        pass
    text = str(value).strip() if value is not None else ''
    return '' if text.lower() in ('', 'none', 'nan', 'null', 'na') else text


def _format_depth_chart_label(position, order):
    pos = _clean_text(position).upper()
    if not pos:
        return ''

    base_pos = pos
    if pos.endswith('WR'):
        base_pos = 'WR'
    elif pos in ('HB', 'FB'):
        base_pos = 'RB'
    elif pos in ('PK',):
        base_pos = 'K'

    try:
        if order not in (None, ''):
            return f'{base_pos}{int(order)}'
    except (TypeError, ValueError):
        pass
    return base_pos


def _format_sleeper_injury_news(player):
    status = _clean_text(player.get('status'))
    injury_status = _clean_text(player.get('injury_status'))
    injury_body_part = _clean_text(player.get('injury_body_part'))
    injury_notes = _clean_text(player.get('injury_notes'))
    depth_chart_position = _clean_text(player.get('depth_chart_position'))
    depth_chart_order = player.get('depth_chart_order')

    updated_label = ''
    raw_updated = player.get('news_updated')
    if raw_updated not in (None, ''):
        try:
            updated_label = datetime.utcfromtimestamp(float(raw_updated) / 1000).strftime('%b %d')
        except (TypeError, ValueError, OSError):
            updated_label = ''

    summary = ''
    if injury_status:
        summary = injury_status
        if injury_body_part:
            summary = f'{summary} - {injury_body_part}'
    elif status and status.upper() not in ('ACTIVE', 'UNKNOWN'):
        summary = status
    elif injury_notes:
        summary = injury_notes

    detail = injury_notes if injury_notes and injury_notes != summary else ''
    status_key = (injury_status or status).upper()
    tone = 'info'
    if any(token in status_key for token in ('OUT', 'DOUBTFUL', 'IR', 'PUP', 'SUSP', 'INACTIVE')):
        tone = 'danger'
    elif status_key in ('QUESTIONABLE', 'PROBABLE') or summary:
        tone = 'warning'

    depth_chart_label = _format_depth_chart_label(depth_chart_position, depth_chart_order)

    title_parts = [summary]
    if detail:
        title_parts.append(detail)
    if updated_label:
        title_parts.append(f'Updated {updated_label}')

    return {
        'status': status,
        'injury_status': injury_status,
        'injury_body_part': injury_body_part,
        'injury_notes': injury_notes,
        'updated_label': updated_label,
        'summary': summary,
        'detail': detail,
        'tone': tone,
        'has_update': bool(summary),
        'title': ' | '.join(p for p in title_parts if p),
        'depth_chart_position': depth_chart_position,
        'depth_chart_order': depth_chart_order,
        'depth_chart_label': depth_chart_label,
    }


_sleeper_player_cache = {'ts': 0, 'by_id': {}, 'by_name': {}}
_SLEEPER_PLAYER_CACHE_TTL = 3600  # 1 hour
_player_move_news_cache = {'ts': 0, 'data': {}}
_PLAYER_MOVE_NEWS_CACHE_TTL = 21600  # 6 hours
_player_watch_news_cache = {'ts': 0, 'data': {}}
_PLAYER_WATCH_NEWS_CACHE_TTL = 3600  # 1 hour


def _refresh_sleeper_player_cache():
    import time
    now = time.time()
    if now - _sleeper_player_cache['ts'] < _SLEEPER_PLAYER_CACHE_TTL and _sleeper_player_cache['by_id']:
        return
    try:
        resp = requests.get('https://api.sleeper.app/v1/players/nfl', timeout=8)
        if resp.status_code == 200:
            by_id = {}
            by_name = defaultdict(list)
            for pid, p in (resp.json() or {}).items():
                first = p.get('first_name') or ''
                last = p.get('last_name') or ''
                name = (p.get('full_name') or f'{first} {last}').strip()
                if not name:
                    continue
                slim = {
                    'name': name,
                    'position': (p.get('position') or '').upper(),
                    'team': _norm_team(p.get('team') or ''),
                    'update': _format_sleeper_injury_news(p),
                    'espn_id': str(p['espn_id']) if p.get('espn_id') else None,
                    'college': (p.get('college') or '').strip() or None,
                }
                by_id[str(pid)] = slim
                by_name[_normalize_name(name)].append(slim)
            _sleeper_player_cache['ts'] = now
            _sleeper_player_cache['by_id'] = by_id
            _sleeper_player_cache['by_name'] = by_name
    except Exception:
        pass


def _get_sleeper_player_map():
    """Fetch + cache the Sleeper NFL player dict. Returns {player_id: {name, position, team}}."""
    if _sleeper_player_cache['by_id']:
        _refresh_sleeper_player_cache()  # no-op if still within TTL
    return _sleeper_player_cache['by_id']  # return stale on failure


def _get_sleeper_player_update(name, team='', pos=''):
    if _sleeper_player_cache['by_id']:
        _refresh_sleeper_player_cache()  # no-op if still within TTL
    candidates = _sleeper_player_cache['by_name'].get(_normalize_name(name), [])
    if not candidates:
        return {}

    team = _norm_team(team)
    pos = str(pos).strip().upper()

    for candidate in candidates:
        if team and candidate.get('team') == team and (not pos or candidate.get('position') == pos):
            return candidate.get('update', {})
    for candidate in candidates:
        if team and candidate.get('team') == team:
            return candidate.get('update', {})
    for candidate in candidates:
        if pos and candidate.get('position') == pos:
            return candidate.get('update', {})
    return candidates[0].get('update', {})


def _fetch_player_move_news(name, team='', prior_team=''):
    import time

    cache_key = (_normalize_name(name), _norm_team(team), _norm_team(prior_team))
    now = time.time()
    if now - _player_move_news_cache['ts'] >= _PLAYER_MOVE_NEWS_CACHE_TTL:
        _player_move_news_cache['ts'] = now
        _player_move_news_cache['data'] = {}
    if cache_key in _player_move_news_cache['data']:
        return _player_move_news_cache['data'][cache_key]

    team_name = _TEAM_NAME_MAP.get(_norm_team(team), _norm_team(team))
    prior_team_name = _TEAM_NAME_MAP.get(_norm_team(prior_team), _norm_team(prior_team))
    query_parts = [f'"{name}"', '"NFL"']
    if team_name:
        query_parts.append(f'"{team_name}"')
    if prior_team_name:
        query_parts.append(f'"{prior_team_name}"')
    query_parts.append('(trade OR signs OR signed OR acquired)')
    query = ' '.join(part for part in query_parts if part)
    url = f'https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en'

    article = {}
    try:
        resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        for item in root.findall('./channel/item'):
            title = _clean_text(item.findtext('title'))
            if not title:
                continue
            title_lower = title.lower()
            if _normalize_name(name) not in _normalize_name(title):
                continue
            source = _clean_text(item.findtext('source'))
            published = _clean_text(item.findtext('pubDate'))
            published_label = ''
            if published:
                try:
                    published_dt = datetime.strptime(published, '%a, %d %b %Y %H:%M:%S %Z')
                    published_label = published_dt.strftime('%b %d')
                except ValueError:
                    published_label = ''
            article = {
                'headline': title,
                'source': source,
                'published_label': published_label,
            }
            break
    except Exception:
        article = {}

    _player_move_news_cache['data'][cache_key] = article
    return article


def _extract_expected_time_missed(text):
    body = _clean_text(text)
    if not body:
        return 'Unknown'

    lower = body.lower()
    if 'no suspension' in lower or 'not suspended' in lower:
        return 'None announced'
    if 'indefinite' in lower or 'indefinitely' in lower:
        return 'Indefinite'
    if 'commissioner exempt' in lower or 'exempt list' in lower:
        return 'Until league review ends'

    word_to_num = {
        'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
        'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
    }

    patterns = [
        (r'(\d+)\s*-\s*game suspension', '{0} games'),
        (r'suspended\s+for\s+(\d+)\s+games?', '{0} games'),
        (r'(\d+)\s+games?\s+suspension', '{0} games'),
        (r'suspended\s+(\d+)\s+games?', '{0} games'),
        (r'(\d+)\s*-\s*week', '{0} weeks'),
        (r'(\d+)\s+weeks?', '{0} weeks'),
    ]
    for pattern, fmt in patterns:
        match = _re.search(pattern, lower)
        if match:
            return fmt.format(match.group(1))
    for word, num in word_to_num.items():
        word_patterns = [
            rf'suspended\s+{word}\s+games?',
            rf'{word}\s+games?\s+suspension',
            rf'{word}\s+weeks?',
        ]
        for pattern in word_patterns:
            if _re.search(pattern, lower):
                unit = 'games' if 'game' in pattern else 'weeks'
                return f'{num} {unit}'
    return 'Unknown'


def _compose_flag_tooltip(tag, description, expected_time):
    parts = [tag]
    if description:
        parts.append(f'Description: {description}')
    if expected_time:
        parts.append(f'Expected time missed: {expected_time}')
    return ' | '.join(parts)


def _fetch_player_watch_news(player_names):
    import time

    now = time.time()
    if now - _player_watch_news_cache['ts'] < _PLAYER_WATCH_NEWS_CACHE_TTL and _player_watch_news_cache['data']:
        return _player_watch_news_cache['data']

    name_map = {_normalize_name(name): name for name in player_names if _clean_text(name)}
    if not name_map:
        return {}

    queries = [
        '"NFL" (suspension OR suspended OR "commissioner exempt" OR "exempt list")',
        '"NFL" (arrest OR arrested OR charges OR charged OR jail OR lawsuit OR investigation OR "domestic violence")',
    ]

    watch_map = {}
    for query in queries:
        url = f'https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en'
        try:
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except Exception:
            continue

        for item in root.findall('./channel/item'):
            title = _clean_text(item.findtext('title'))
            raw_description = _clean_text(item.findtext('description'))
            description = BeautifulSoup(raw_description, 'html.parser').get_text(' ', strip=True) if raw_description else ''
            article_text = ' '.join(part for part in [title, description] if part)
            normalized_text = _normalize_name(article_text)
            normalized_title = _normalize_name(title)
            lower_title = title.lower()
            if not normalized_text:
                continue

            matched_name = None
            for name_key, original_name in name_map.items():
                if name_key and name_key in normalized_title:
                    matched_name = (name_key, original_name)
                    break
            if not matched_name or matched_name[0] in watch_map:
                continue

            lower_text = article_text.lower()
            name_index = normalized_title.find(matched_name[0])
            suspension_index = min(
                [idx for idx in [lower_title.find(token) for token in ('suspension', 'suspended', 'commissioner exempt', 'exempt list')] if idx >= 0] or [-1]
            )
            is_suspension = suspension_index >= 0 and name_index >= 0 and name_index <= suspension_index
            is_offfield = any(token in lower_text for token in ('arrest', 'arrested', 'charges', 'charged', 'jail', 'lawsuit', 'investigation', 'domestic violence'))
            if not (is_suspension or is_offfield):
                continue

            published = _clean_text(item.findtext('pubDate'))
            published_label = ''
            if published:
                try:
                    published_dt = datetime.strptime(published, '%a, %d %b %Y %H:%M:%S %Z')
                    published_label = published_dt.strftime('%b %d')
                except ValueError:
                    published_label = ''

            source = _clean_text(item.findtext('source'))
            desc = description or title
            expected_time = _extract_expected_time_missed(article_text)
            label = 'Suspension' if is_suspension else 'Off-field'
            watch_map[matched_name[0]] = {
                'label': label,
                'tone': 'danger' if is_suspension else 'warning',
                'description': desc,
                'expected_time_missed': expected_time,
                'headline': title,
                'source': source,
                'published_label': published_label,
                'title': _compose_flag_tooltip(label, desc, expected_time),
            }

    _player_watch_news_cache['ts'] = now
    _player_watch_news_cache['data'] = watch_map
    return watch_map

# ── Sleeper ADP (scoring-format-specific) ─────────────────────────────
# Sleeper projections endpoint returns per-scoring-type projected points
# which we use to derive format-specific rank ordering.
_SLEEPER_SCORING_KEY = {
    'ppr':      'pts_ppr',
    'half_ppr': 'pts_half_ppr',
    'standard': 'pts_std',
}

def _fetch_sleeper_adp_all():
    """
    Fetch Sleeper format-specific rankings using 2025 actual seasonal totals.
    /v1/stats/nfl/regular/2025 returns pts_ppr, pts_half_ppr, pts_std per player.
    Sort descending by each scoring type to produce format-aware rankings.
    Falls back to search_rank if stats unavailable.
    """
    empty = pd.DataFrame(columns=['player_name', 'name_key', 'adp_rank', 'team', 'position'])
    out   = {'ppr': empty, 'half_ppr': empty, 'standard': empty}
    try:
        meta_resp  = requests.get('https://api.sleeper.app/v1/players/nfl', timeout=15)
        stats_resp = requests.get('https://api.sleeper.app/v1/stats/nfl/regular/2025', timeout=15)
        meta_resp.raise_for_status()
        stats_resp.raise_for_status()
        meta  = meta_resp.json()
        stats = stats_resp.json()

        scoring_keys = {
            'ppr':      'pts_ppr',
            'half_ppr': 'pts_half_ppr',
            'standard': 'pts_std',
        }

        for scoring, pts_key in scoring_keys.items():
            entries = []
            for player_id, pstats in stats.items():
                pts = pstats.get(pts_key)
                if pts is None or pts == 0:
                    continue
                pmeta    = meta.get(str(player_id), {})
                pos_list = pmeta.get('fantasy_positions') or []
                if not any(x in pos_list for x in ('QB', 'RB', 'WR', 'TE')):
                    continue
                name = pmeta.get('full_name', '')
                if not name:
                    continue
                pos = pmeta.get('position', '')
                # Normalize points by position so QBs don't dominate —
                # QBs score ~2.5x more raw points but are drafted much later in real drafts
                pos_weight = {'QB': 0.42}.get(pos, 1.0)
                entries.append((pts * pos_weight, name, pmeta.get('team', ''), pos))

            entries.sort(key=lambda x: x[0], reverse=True)
            records = [
                {'player_name': name, 'name_key': _normalize_name(name),
                 'adp_rank': rank, 'team': team, 'position': pos}
                for rank, (pts, name, team, pos) in enumerate(entries, 1)
            ]
            out[scoring] = pd.DataFrame(records)
            print(f'Sleeper ADP ({scoring}) from 2025 stats: {len(records)} players')

        # Supplement with players not in 2025 stats (rookies) using search_rank from meta
        covered_ids = set(stats.keys())
        rookie_records = []
        for player_id, pmeta in meta.items():
            if player_id in covered_ids:
                continue
            sr = pmeta.get('search_rank')
            if sr is None or sr == 9999999:
                continue
            pos_list = pmeta.get('fantasy_positions') or []
            if not any(x in pos_list for x in ('QB', 'RB', 'WR', 'TE')):
                continue
            name = pmeta.get('full_name', '')
            if not name:
                continue
            rookie_records.append({
                'player_name': name,
                'name_key':    _normalize_name(name),
                'adp_rank':    int(sr),
                'team':        pmeta.get('team', ''),
                'position':    pmeta.get('position', ''),
            })
        if rookie_records:
            rookie_df = pd.DataFrame(rookie_records)
            for scoring in scoring_keys:
                out[scoring] = pd.concat([out[scoring], rookie_df], ignore_index=True)
            print(f'Supplemented ADP with {len(rookie_records)} rookies from search_rank')

        return out

    except Exception as e:
        print(f'Sleeper stats unavailable: {e} — falling back to search_rank')

    # Fallback: search_rank (not format-specific, same for all three)
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
            records.append({
                'player_name': name, 'name_key': _normalize_name(name),
                'adp_rank': int(rank), 'team': p.get('team', ''), 'position': p.get('position', ''),
            })
        df = pd.DataFrame(records).sort_values('adp_rank').reset_index(drop=True)
        print(f'Sleeper ADP (all formats) from search_rank fallback: {len(df)} players')
        return {'ppr': df, 'half_ppr': df, 'standard': df}
    except Exception as e2:
        print(f'Warning: could not fetch Sleeper ADP: {e2}')
        return out

# Fetch all three formats at startup (one call for all)
_sleeper_adp = _fetch_sleeper_adp_all()

# ── ESPN ADP ───────────────────────────────────────────────────────────
_ESPN_SCORING_TYPE = {'ppr': 'PPR', 'half_ppr': 'HALF', 'standard': 'STANDARD'}

def _fetch_espn_adp():
    """
    Fetch ESPN ADP from the public ESPN fantasy API (PPR slot only — slots 0/4 return 404).
    All three scoring formats share the same PPR ranking list.
    draftRanksByRankType[PPR].rank is used (ownership.averageDraftPosition is always 170.0).
    """
    import json as _json
    empty = pd.DataFrame(columns=['player_name', 'name_key', 'adp_rank', 'team', 'position'])
    out = {'ppr': empty, 'half_ppr': empty, 'standard': empty}
    pos_map = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE'}
    # Only slot 3 (PPR) is publicly available; reuse for all formats
    espn_configs = {
        'ppr': {'slot': 3, 'rank_key': 'PPR', 'sort_val': 'PPR'},
    }
    for scoring, cfg in espn_configs.items():
        try:
            fantasy_filter = _json.dumps({
                'players': {
                    'limit': 300,
                    'sortDraftRanks': {
                        'sortPriority': 100,
                        'sortAsc': True,
                        'value': cfg['sort_val'],
                    },
                    'filterSlotIds': {'value': [0, 2, 4, 6, 23]},
                }
            })
            headers = {
                'Accept': 'application/json',
                'User-Agent': 'Mozilla/5.0',
                'X-Fantasy-Filter': fantasy_filter,
            }
            url = (f'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl'
                   f'/seasons/2025/segments/0/leaguedefaults/{cfg["slot"]}'
                   f'?view=kona_player_info')
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            players_raw = data.get('players', [])
            entries = []
            for entry in players_raw:
                p = entry.get('player', {})
                name   = p.get('fullName', '')
                pos_id = p.get('defaultPositionId', 0)
                if pos_id not in pos_map or not name:
                    continue
                pos = pos_map[pos_id]
                # Use draftRanksByRankType rank — ownership.averageDraftPosition is 170.0 for all
                rank_info = (p.get('draftRanksByRankType') or {}).get(cfg['rank_key'], {})
                adp = rank_info.get('rank')
                if adp is None or adp == 0:
                    continue
                try:
                    adp = float(adp)
                except (TypeError, ValueError):
                    continue
                _espn_team_map = {
                    1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',
                    9:'GB',10:'TEN',11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',
                    16:'MIN',17:'NE',18:'NO',19:'NYG',20:'NYJ',21:'PHI',22:'ARI',
                    23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',28:'WAS',29:'CAR',
                    30:'JAX',33:'BAL',34:'HOU',
                }
                team_abbr = _espn_team_map.get(p.get('proTeamId', 0), '')
                entries.append((adp, name, pos, team_abbr))
            entries.sort(key=lambda x: x[0])
            records = [
                {'player_name': name, 'name_key': _normalize_name(name),
                 'adp_rank': rank_i, 'team': team, 'position': pos}
                for rank_i, (adp, name, pos, team) in enumerate(entries, 1)
            ]
            df = pd.DataFrame(records) if records else out[scoring]
            out['ppr'] = out['half_ppr'] = out['standard'] = df
            print(f'ESPN ADP (PPR slot only): {len(records)} players')
        except Exception as e:
            print(f'Warning: could not fetch ESPN ADP: {e}')
    return out

_espn_adp = _fetch_espn_adp()

# ── Team abbreviation normalization ──────────────────────────────────
def _norm_team(t):
    """Normalize team abbreviations (LA -> LAR, ARZ -> ARI, etc.)"""
    t = str(t).strip().upper()
    return _TEAM_ABBR_MAP.get(t, t)


def _latest_player_team_map():
    def _team_col(df):
        return next((c for c in ['recent_team', 'team', 'posteam', 'team_abbr', 'club', 'Tm', 'Team'] if c in df.columns), None)

    if _nfl_seasonal.empty:
        frames = []
        for filename, default_pos in [('final_qb_data.pkl', 'QB'), ('final_rb_data.pkl', 'RB'), ('final_wrte_data.pkl', None)]:
            df = _load(filename)
            if df.empty:
                continue
            df = df[df['season'] == df['season'].max()].copy()
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            name_col = 'player_display_name' if 'player_display_name' in df.columns else None
            team_col = _team_col(df)
            pos_col = 'position' if 'position' in df.columns else None
            if not (name_col and team_col):
                continue
            use_cols = [name_col, team_col]
            if pos_col:
                use_cols.append(pos_col)
            slim = df[use_cols].copy()
            if not pos_col and default_pos:
                slim['position'] = default_pos
            frames.append(slim.rename(columns={name_col: 'name', team_col: 'team', pos_col or 'position': 'position'}))
        if not frames:
            return {}
        latest_df = pd.concat(frames, ignore_index=True).dropna(subset=['name', 'team']).drop_duplicates('name')
        return {
            _normalize_name(row['name']): _norm_team(row['team'])
            for _, row in latest_df.iterrows()
            if _clean_text(row.get('name')) and _clean_text(row.get('team'))
        }

    season_col = next((c for c in ['season'] if c in _nfl_seasonal.columns), None)
    name_col = next((c for c in ['player_display_name', 'player_name'] if c in _nfl_seasonal.columns), None)
    team_col = next((c for c in ['recent_team', 'team'] if c in _nfl_seasonal.columns), None)
    games_col = next((c for c in ['games', 'GP'] if c in _nfl_seasonal.columns), None)
    points_col = next((c for c in ['fantasy_points_ppr', 'fantasy_points'] if c in _nfl_seasonal.columns), None)
    if not (season_col and name_col and team_col):
        return {}

    latest_df = _nfl_seasonal[_nfl_seasonal[season_col] == _nfl_seasonal[season_col].max()].copy()
    if 'season_type' in latest_df.columns:
        latest_df = latest_df[latest_df['season_type'] == 'REG']
    latest_df = latest_df.dropna(subset=[name_col, team_col])
    if latest_df.empty:
        return {}

    sort_cols = []
    ascending = []
    if games_col:
        sort_cols.append(games_col)
        ascending.append(False)
    if points_col:
        sort_cols.append(points_col)
        ascending.append(False)
    if sort_cols:
        latest_df = latest_df.sort_values(sort_cols, ascending=ascending)

    latest_df = latest_df.drop_duplicates(name_col)
    return {
        _normalize_name(row[name_col]): _norm_team(row[team_col])
        for _, row in latest_df.iterrows()
        if _clean_text(row.get(name_col)) and _clean_text(row.get(team_col))
    }


def _build_rankings_flags(name, pos, team, prior_team_map, watch_news_map):
    flags = []
    update = _get_sleeper_player_update(name, team, pos)
    status_key = (update.get('status') or '').upper()
    summary_key = (update.get('summary') or '').upper()
    name_key = _normalize_name(name)
    watch_news = watch_news_map.get(name_key, {})

    if watch_news:
        flags.append({
            'label': watch_news.get('label', 'Off-field'),
            'tone': watch_news.get('tone', 'warning'),
            'title': watch_news.get('title', ''),
            'description': watch_news.get('description', ''),
            'expected_time_missed': watch_news.get('expected_time_missed', 'Unknown'),
        })

    if 'SUSP' in status_key or 'SUSP' in summary_key:
        flags.append({
            'label': 'Suspension',
            'tone': 'danger',
            'title': _compose_flag_tooltip(
                'Suspension',
                update.get('title') or update.get('summary') or 'Official status flag',
                _extract_expected_time_missed(update.get('title') or update.get('summary') or ''),
            ),
            'description': update.get('title') or update.get('summary') or 'Official status flag',
            'expected_time_missed': _extract_expected_time_missed(update.get('title') or update.get('summary') or ''),
        })
    elif (
        update.get('injury_status')
        or update.get('injury_notes')
        or any(token in status_key for token in ('OUT', 'DOUBTFUL', 'QUESTIONABLE', 'PUP', 'IR', 'INACTIVE'))
    ):
        flags.append({
            'label': 'Injury',
            'tone': 'warning',
            'title': _compose_flag_tooltip(
                'Injury',
                update.get('title') or update.get('summary') or 'Injury update',
                _extract_expected_time_missed(update.get('title') or update.get('summary') or ''),
            ),
            'description': update.get('title') or update.get('summary') or 'Injury update',
            'expected_time_missed': _extract_expected_time_missed(update.get('title') or update.get('summary') or ''),
        })

    prior_team = prior_team_map.get(_normalize_name(name))
    if prior_team and team and prior_team != team:
        move_news = _fetch_player_move_news(name, team, prior_team)
        move_desc_parts = [f'{prior_team} -> {team}']
        if update.get('depth_chart_label'):
            move_desc_parts.append(f'Depth: {update["depth_chart_label"]}')
        if move_news.get('headline'):
            move_desc_parts.append(f'News: {move_news["headline"]}')
            if move_news.get('source'):
                move_desc_parts.append(f'Source: {move_news["source"]}')
            if move_news.get('published_label'):
                move_desc_parts.append(f'Updated {move_news["published_label"]}')
        move_description = ' | '.join(move_desc_parts)
        flags.append({
            'label': 'New Team',
            'tone': 'info',
            'title': _compose_flag_tooltip('New Team', move_description, 'Unknown'),
            'description': move_description,
            'expected_time_missed': 'Unknown',
        })

    return flags

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

        # Join Sleeper ADP (format-specific)
        _adp_df = _sleeper_adp.get(scoring, pd.DataFrame())
        if not _adp_df.empty:
            combined['name_key'] = combined['player_name'].apply(_normalize_name)
            adp_slim = _adp_df[['name_key', 'adp_rank']].drop_duplicates('name_key')
            combined = combined.merge(adp_slim, on='name_key', how='left')
        else:
            combined['adp_rank'] = None

        # ESPN ADP fallback: covers 2026 rookies not in 2025 Sleeper stats
        _espn_df = _espn_adp.get('ppr', pd.DataFrame())
        if not _espn_df.empty:
            if 'name_key' not in combined.columns:
                combined['name_key'] = combined['player_name'].apply(_normalize_name)
            _espn_slim = _espn_df[['name_key', 'adp_rank']].drop_duplicates('name_key').rename(
                columns={'adp_rank': '_espn_adp'}
            )
            combined = combined.merge(_espn_slim, on='name_key', how='left')
            _missing_adp = combined['adp_rank'].isna() & combined['_espn_adp'].notna()
            combined.loc[_missing_adp, 'adp_rank'] = combined.loc[_missing_adp, '_espn_adp']
            combined = combined.drop(columns=['_espn_adp'], errors='ignore')

        # Normalize team abbreviations (LA -> LAR, etc.)
        combined['team'] = combined['team'].apply(_norm_team)
        
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
_model_table = {k: json.loads(v.to_json(orient='records')) if not v.empty else [] for k, v in _model_data.items()}


def _inject_rankings_flags(rows):
    if not rows:
        return rows

    prior_team_map = _latest_player_team_map()
    watch_news_map = _fetch_player_watch_news([row.get('Name', '') for row in rows])

    enriched = []
    for row in rows:
        update = _get_sleeper_player_update(
            row.get('Name', ''),
            row.get('Team', ''),
            row.get('Position', ''),
        )
        flags = _build_rankings_flags(
            row.get('Name', ''),
            row.get('Position', ''),
            row.get('Team', ''),
            prior_team_map,
            watch_news_map,
        )
        ordered = {}
        for key, value in row.items():
            ordered[key] = value
            if key == 'Team':
                ordered['Depth'] = update.get('depth_chart_label', '')
                ordered['Flags'] = flags
        if 'Depth' not in ordered:
            ordered['Depth'] = update.get('depth_chart_label', '')
        if 'Flags' not in ordered:
            ordered['Flags'] = flags
        enriched.append(ordered)
    # Drop Depth column entirely when Sleeper has no current depth chart data (off-season)
    if all(not row.get('Depth', '') for row in enriched):
        for row in enriched:
            row.pop('Depth', None)
    return enriched


_model_table = {k: _inject_rankings_flags(v) for k, v in _model_table.items()}
for k, v in _model_table.items():
    print(f'Model table ({k}): {len(v)} rows')

_rookie_names = set()
try:
    _rook_df = pd.read_pickle(_BASE_DIR / 'Models' / 'PickleFiles' / 'NewModel' / 'combined_predictions_ppr.pkl')
    if 'is_rookie' in _rook_df.columns:
        _rookie_names = set(_rook_df[_rook_df['is_rookie'] == True]['player_name'].tolist())
    print(f'Rookie names loaded: {len(_rookie_names)}')
except Exception as _re:
    print(f'Rookie names unavailable: {_re}')

# ── Similarity model (Phase 4) ────────────────────────────────────
import pickle as _pickle

_similarity_comps = {}
_umap_coords_json = '[]'
_similarity_comps_json = '{}'
try:
    import numpy as _np
    class _NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, _np.floating): return float(obj)
            if isinstance(obj, _np.integer):  return int(obj)
            if isinstance(obj, _np.ndarray):  return obj.tolist()
            return super().default(obj)
    _sim_dir = _BASE_DIR / 'Models' / 'PickleFiles' / 'NewModel'
    with open(_sim_dir / 'similarity_comps.pkl', 'rb') as _f:
        _similarity_comps = _pickle.load(_f)
    _similarity_comps_json = json.dumps(_similarity_comps, cls=_NpEncoder)
    _umap_df = pd.read_pickle(_sim_dir / 'umap_coords.pkl')
    _umap_coords_json = _umap_df.to_json(orient='records')
    print(f'Similarity model loaded: {len(_similarity_comps)} players, {len(_umap_df)} UMAP points')
except Exception as _e:
    print(f'Warning: could not load similarity model: {_e}')

# Pre-warm Sleeper player cache in background so first player click is instant
import threading as _threading
_threading.Thread(target=_refresh_sleeper_player_cache, daemon=True).start()

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

    # ALWAYS use PFF grades from currAVs.pkl first (except TE which uses fantasy points)
    pff_loaded = False
    try:
        curr_avs = _load('currAVs.pkl')
        if not curr_avs.empty and 'team' in curr_avs.columns:
            for _, row in curr_avs.iterrows():
                team = _norm_team(row['team'])
                # Normalize PFF grades from 0-100 scale to 0-1 scale
                # Store both pass blocking (OLine) and run blocking (RB_OLine) separately
                # Note: TE will be calculated from fantasy points below
                per_team[team] = {
                    'QB': round(float(row.get('qb', 50)) / 100.0, 2),
                    'RB': round(float(row.get('rb', 50)) / 100.0, 2),
                    'WR': round(float(row.get('wrte', 50)) / 100.0, 2),
                    'OLine': round(float(row.get('oline', 50)) / 100.0, 2),  # Pass blocking for non-RB
                    'RB_OLine': round(float(row.get('rb', 50)) / 100.0, 2),  # Run blocking for RB
                    'DST': round(float(row.get('dst', 50)) / 100.0, 2),
                }
            pff_loaded = True
            print(f'Loaded PFF grades for {len(per_team)} teams from currAVs.pkl')
            
            # Calculate TE grades from fantasy points (original method)
            wrte = _load('final_wrte_data.pkl')
            if not wrte.empty:
                latest = wrte['season'].max()
                st_col = 'season_type' if 'season_type' in wrte.columns else None
                mask = wrte['season'] == latest
                if st_col:
                    mask = mask & (wrte[st_col] == 'REG')
                df = wrte[mask].copy()
                tc = _find_team_col(df)
                if tc and 'fantasy_points' in df.columns and 'GP' in df.columns:
                    pc = next((c for c in ['position', 'Position'] if c in df.columns), None)
                    if pc:
                        df[tc] = df[tc].apply(_norm_team)
                        df['fpg'] = df['fantasy_points'] / df['GP'].clip(lower=1)
                        te_df = df[df[pc].str.upper() == 'TE'].copy()
                        te_df = te_df.sort_values('fantasy_points', ascending=False)
                        top_te = te_df.groupby(tc).head(2)
                        raw = {}
                        for team, val in top_te.groupby(tc)['fpg'].mean().items():
                            sf = _safe_f(val, 3)
                            if sf is not None:
                                raw[team] = sf
                        # Normalize TE grades
                        if raw:
                            mn, mx = min(raw.values()), max(raw.values())
                            rng = mx - mn if mx > mn else 1.0
                            for team, v in raw.items():
                                normalized = round((v - mn) / rng, 2)
                                if team in per_team:
                                    per_team[team]['TE'] = normalized
                        print(f'Calculated TE grades from fantasy points for {len(raw)} teams')
    except Exception as e:
        print(f'Warning: could not load currAVs.pkl: {e}')

    # Only calculate from player stats if PFF grades failed to load
    if not pff_loaded:
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
            # Last resort: calculate from player stats
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

    # Ensure every team that appears in any grade has all keys (fill missing with median)
    all_teams = set(per_team.keys())
    for grade_key in ['QB', 'RB', 'WR', 'TE', 'OLine', 'RB_OLine', 'DST']:
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

# teamsPastRoster.pkl was saved with Python 3.9 and contains struct_time objects
# that trigger a fatal C-level error in Python 3.11. Skip loading it entirely.
_roster_df = pd.DataFrame()
_qb_model    = _load('QBDFForModelPPR.pkl')
_rb_model    = _load('RBDFForModelPPR.pkl')
_wrte_model  = _load('WRTEDFForModelPPR.pkl')
_rankings    = _load('Full PPR Rankings with Weighted VBD.pkl')

@main.route('/', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('main.home'))

    # Handle OAuth code if Supabase redirected here instead of /auth/callback
    code = request.args.get('code')
    if code:
        try:
            data = supabase_auth.exchange_code_for_session(code)
            _ensure_local_user_from_token(data)
            return redirect(url_for('main.home'))
        except Exception:
            import traceback
            traceback.print_exc()
            flash('Authentication failed. Please try again.', 'danger')

    form = LoginForm()
    if form.validate_on_submit():
        try:
            resp = supabase_auth.sign_in(form.email.data, form.password.data)
            _ensure_local_user(resp.user)
            next_page = request.args.get('next')
            if next_page and not next_page.startswith('/'):
                next_page = None
            return redirect(next_page) if next_page else redirect(url_for('main.home'))
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash('Invalid email or password', 'danger')
    return render_template('login.html', form=form)


@main.route('/register', methods=['GET', 'POST'])
def register():
    if g.user:
        return redirect(url_for('main.home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            supabase_auth.sign_up(form.email.data.strip(), form.password.data)
            flash('Registration successful! Check your email to confirm.', 'success')
            return redirect(url_for('main.login'))
        except Exception:
            flash('Registration failed. Email may already be in use.', 'danger')
    return render_template('register.html', form=form)


@main.route('/login/<provider>')
def social_login(provider):
    """Redirect to OAuth provider (google, apple)."""
    if provider not in ('google',):
        abort(404)
    resp = supabase_auth.sign_in_with_oauth(
        provider,
        redirect_to=url_for('main.auth_callback', _external=True),
    )
    return redirect(resp.url)


@main.route('/auth/callback')
def auth_callback():
    """Handle redirect from OAuth provider.

    Supabase redirects here with ?code=... which we exchange for a session
    server-side.
    """
    code = request.args.get('code')
    if not code:
        return redirect(url_for('main.login'))
    try:
        data = supabase_auth.exchange_code_for_session(code)
        _ensure_local_user_from_token(data)
        return redirect(url_for('main.home'))
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash('Authentication failed. Please try again.', 'danger')
        return redirect(url_for('main.login'))


@main.route('/logout')
def logout():
    supabase_auth.sign_out()
    flash('You have been logged out.')
    return redirect(url_for('main.login'))


@main.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        if email:
            try:
                supabase_auth.reset_password(
                    email,
                    redirect_to=url_for('main.reset_password_confirm', _external=True),
                )
            except Exception:
                pass
            # Same message regardless of whether email exists (prevent enumeration)
            flash('If that email is registered, a reset link has been sent.', 'info')
        else:
            flash('Please enter your email address.', 'warning')
        return redirect(url_for('main.login'))
    return render_template('forgot_password.html')


@main.route('/reset-password', methods=['GET', 'POST'])
def reset_password_confirm():
    """User lands here from the reset email link."""
    if request.method == 'POST':
        new_password = request.form.get('password', '')
        if len(new_password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('reset_password.html')
        try:
            supabase_auth.get_supabase().auth.update_user({'password': new_password})
            flash('Password updated! Please log in.', 'success')
            return redirect(url_for('main.login'))
        except Exception:
            flash('Failed to reset password. The link may have expired.', 'danger')
    return render_template('reset_password.html')


def _ensure_local_user(supabase_user):
    """Create or update local User record from Supabase user data."""
    user = User.query.get(supabase_user.id)
    if not user:
        user = User(
            id=supabase_user.id,
            email=supabase_user.email,
            username=(supabase_user.user_metadata or {}).get('old_username'),
        )
        db.session.add(user)
    else:
        user.email = supabase_user.email
    db.session.commit()


def _ensure_local_user_from_token(token_data):
    """Create or update local User record from raw token response dict."""
    user_data = token_data.get('user', {})
    user_id = user_data.get('id', '')
    email = user_data.get('email', '')
    if not user_id:
        return
    user = User.query.get(user_id)
    if not user:
        user = User(id=user_id, email=email)
        db.session.add(user)
    else:
        user.email = email
    db.session.commit()

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
    saved = UserRanking.query.filter_by(user_id=g.user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_model_table['ppr'], table_type='PPR',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/rankings/half-ppr')
@login_required
def get_half_ppr_rankings():
    saved = UserRanking.query.filter_by(user_id=g.user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_model_table['half_ppr'], table_type='Half PPR',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/rankings/standard')
@login_required
def get_standard_rankings():
    saved = UserRanking.query.filter_by(user_id=g.user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_model_table['standard'], table_type='Standard',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/rankings/new-model')
@login_required
def get_new_model_rankings():
    return redirect(url_for('main.get_ppr_rankings'))

@main.route('/player-comps')
@login_required
def player_comps():
    return render_template('player_comps.html',
                           umap_coords_json=_umap_coords_json,
                           similarity_comps_json=_similarity_comps_json)

@main.route('/save_rankings', methods=['POST'])
@login_required
def save_rankings():
    data = request.get_json()
    ranking_data = data.get('ranking', [])
    ranking_type = data.get('ranking_type', 'Custom')
    name = data.get('name', 'Untitled')

    # Check for duplicate name
    existing = UserRanking.query.filter_by(user_id=g.user.id, name=name).first()
    if existing:
        return jsonify({'error': 'A ranking with that name already exists. Please choose a different name.'}), 400

    # Convert ranking data to JSON format
    ranking_json = json.dumps(ranking_data)

    # Save the ranking to the database
    user_ranking = UserRanking(user_id=g.user.id, name=name, ranking_type=ranking_type, ranking_data=ranking_json)
    db.session.add(user_ranking)
    db.session.commit()

    return jsonify({'message': 'Rankings saved successfully!', 'ranking_id': user_ranking.id})

@main.route('/update_ranking/<int:ranking_id>', methods=['PUT'])
@login_required
def update_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != g.user.id:
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
    if ranking.user_id != g.user.id:
        flash('Access denied.')
        return redirect(url_for('main.rankings'))
    # Parse the saved JSON data back into table format
    rows = json.loads(ranking.ranking_data)
    current_header_map = {'PPR': 'ppr', 'Half PPR': 'half_ppr', 'Standard': 'standard'}
    current_table_key = current_header_map.get(ranking.ranking_type)
    if current_table_key and _model_table.get(current_table_key):
        headers = list(_model_table[current_table_key][0].keys())
    else:
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
    saved = UserRanking.query.filter_by(user_id=g.user.id).order_by(UserRanking.timestamp.desc()).all()
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
    user_rankings = UserRanking.query.filter_by(user_id=g.user.id).all()
    return render_template('user_rankings.html', user_rankings=user_rankings)

@main.route('/delete_ranking/<int:ranking_id>', methods=['DELETE'])
@login_required
def delete_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != g.user.id:
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
    
    team = _norm_team(team)

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
            cols = ['season', 'recent_team', 'games', 'completions', 'attempts', 'passing_yards',
                    'passing_tds', 'passing_interceptions', 'rushing_yards', 'rushing_tds', 'fantasy_points_ppr']
        elif pos == 'RB':
            cols = ['season', 'recent_team', 'games', 'carries', 'rushing_yards', 'rushing_tds',
                    'receptions', 'targets', 'receiving_yards', 'receiving_tds', 'fantasy_points_ppr']
        else:  # WR / TE
            cols = ['season', 'recent_team', 'games', 'receptions', 'targets', 'receiving_yards',
                    'receiving_tds', 'target_share', 'air_yards_share', 'fantasy_points_ppr']

        available = [c for c in cols if c in player_rows.columns]
        hist = player_rows[available].round(1)
        hist = hist.rename(columns={'games': 'GP', 'fantasy_points_ppr': 'fantasy_points', 'recent_team': 'team'})
        history = _clean_hist(hist)

    # Fallback: build history from pkl files when nflreadpy is unavailable
    # These pkl files were saved with Python 3.9 and may fail to load in Python 3.11 — skip silently
    if not history:
        try:
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
                    hist = player_rows[available].round(1)
                    history = _clean_hist(hist)
        except Exception:
            pass

    # --- Rankings info ---
    rank_row = _rankings[_rankings['Name'] == name] if not _rankings.empty and 'Name' in _rankings.columns else pd.DataFrame()
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
    team_grade_ranks = {}
    if team and team in _composite_grades:
        cg = _composite_grades[team]
        
        # Conditionally use pass blocking or run blocking for OLine based on position
        oline_grade = cg.get('RB_OLine') if pos == 'RB' else cg.get('OLine')
        
        team_grade = {
            'OLine': oline_grade,
            'QB':    cg.get('QB'),
            'RB':    cg.get('RB'),
            'WR':    cg.get('WR'),
            'TE':    cg.get('TE'),
            'DST':   cg.get('DST'),
        }
        
        # Calculate rankings (1-32) for each grade
        for grade_key in ['QB', 'RB', 'WR', 'TE', 'DST']:
            if grade_key in team_grade and team_grade[grade_key] is not None:
                all_grades = sorted(
                    [g.get(grade_key, 0) for g in _composite_grades.values() if g.get(grade_key) is not None],
                    reverse=True
                )
                rank = all_grades.index(team_grade[grade_key]) + 1 if team_grade[grade_key] in all_grades else None
                team_grade_ranks[grade_key] = rank
        
        # Handle OLine rank separately (different source for RB vs others)
        if oline_grade is not None:
            oline_key = 'RB_OLine' if pos == 'RB' else 'OLine'
            all_oline_grades = sorted(
                [g.get(oline_key, 0) for g in _composite_grades.values() if g.get(oline_key) is not None],
                reverse=True
            )
            oline_rank = all_oline_grades.index(oline_grade) + 1 if oline_grade in all_oline_grades else None
            team_grade_ranks['OLine'] = oline_rank

    return jsonify({
        'history': history,
        'ranking': ranking,
        'team_grade': team_grade,
        'team_grade_ranks': team_grade_ranks,
        'comps': _similarity_comps.get(name, []),
        'injury_news': _get_sleeper_player_update(name, team, pos),
        'is_rookie': name in _rookie_names,
    })


def _get_player_roster_profile(name, team='', pos=''):
    # Sleeper cache first: filter by position + team to avoid name collisions (e.g. two "Lamar Jackson"s)
    espn_id = None
    _sleeper_candidates = _sleeper_player_cache['by_name'].get(_normalize_name(name), [])
    _norm_team_arg = _norm_team(team).upper() if team else ''
    _pos_arg = pos.upper() if pos else ''
    # Pass 1: exact position + team match
    for _sc in _sleeper_candidates:
        if not _sc.get('espn_id'):
            continue
        _sc_pos  = (_sc.get('position') or '').upper()
        _sc_team = _norm_team(_sc.get('team') or '').upper()
        if (_pos_arg and _sc_pos == _pos_arg) and (_norm_team_arg and _sc_team == _norm_team_arg):
            espn_id = _sc['espn_id']
            break
    # Pass 2: position match only (team might differ — e.g. mid-season trade)
    if not espn_id:
        for _sc in _sleeper_candidates:
            if not _sc.get('espn_id'):
                continue
            _sc_pos = (_sc.get('position') or '').upper()
            if _pos_arg and _sc_pos == _pos_arg:
                espn_id = _sc['espn_id']
                break
    # Pass 3: any Sleeper candidate (name-only match, least precise)
    if not espn_id:
        for _sc in _sleeper_candidates:
            if _sc.get('espn_id'):
                espn_id = _sc['espn_id']
                break
    # Final fallback: nfl_data_py map (may have collisions for common names)
    if not espn_id:
        espn_id = _espn_id_map.get(name)

    bio = dict(_bio_map.get(name, {}))
    try:
        roster_df = _roster_df
        if not roster_df.empty:
            match = roster_df[roster_df['Player'] == name]
            if not match.empty:
                row = match.iloc[0]
                raw_id = row.get('espn_id')
                if raw_id is not None and str(raw_id) not in ('', 'nan', 'None'):
                    espn_id = str(raw_id)

                def _sv(v):
                    return str(v) if pd.notna(v) and str(v) not in ('nan', 'None', '') else '—'

                def _fmt_height(v):
                    try:
                        inches = float(v)
                        ft = int(inches // 12)
                        rem = int(inches % 12)
                        return f"{ft}'{rem}\""
                    except (TypeError, ValueError):
                        return '—'

                def _fmt_weight(v):
                    try:
                        return f"{int(float(v))} lbs"
                    except (TypeError, ValueError):
                        return '—'

                def _fmt_year(v):
                    try:
                        return str(int(float(v)))
                    except (TypeError, ValueError):
                        return '—'

                def _fmt_age(birth_str):
                    try:
                        from datetime import date
                        import re as _re_age
                        s = str(birth_str).strip()
                        m = _re_age.match(r'(\d{4})-(\d{2})-(\d{2})', s)
                        if m:
                            born = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        else:
                            m2 = _re_age.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)
                            if m2:
                                born = date(int(m2.group(3)), int(m2.group(1)), int(m2.group(2)))
                            else:
                                return '—'
                        today = date.today()
                        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                        return str(age)
                    except Exception:
                        return '—'

                def _fmt_pick(round_val, pick_val):
                    try:
                        r = int(float(round_val))
                        p = int(float(pick_val))
                        return f"Rd {r} Pk {p}"
                    except (TypeError, ValueError):
                        return '—'

                bio = {
                    'Age': _fmt_age(row.get('BirthDate')),
                    'Height': _fmt_height(row.get('height')),
                    'Weight': _fmt_weight(row.get('weight')),
                    'College': _sv(row.get('College')),
                    'Draft Year': _fmt_year(row.get('DraftYear')),
                    'Draft Team': _sv(row.get('DraftTeam')),
                    'Pick': _fmt_pick(row.get('DraftRound'), row.get('DraftPick')),
                    'Seasons Played': _fmt_year(row.get('ExperienceYears')),
                }
    except Exception as exc:
        print(f'Warning: could not look up player roster profile: {exc}')

    # Supplement College from Sleeper cache if nfl_data_py didn't have it
    if 'College' not in bio:
        for _sc in _sleeper_candidates:
            if _sc.get('college'):
                bio['College'] = _sc['college']
                break

    injury_news = _get_sleeper_player_update(name, team, pos)
    if injury_news.get('summary'):
        bio['Status'] = injury_news['summary']
        update_parts = []
        if injury_news.get('detail'):
            update_parts.append(injury_news['detail'])
        if injury_news.get('updated_label'):
            update_parts.append(f"Updated {injury_news['updated_label']}")
        if update_parts:
            bio['Update'] = ' | '.join(update_parts)

    return {'espn_id': espn_id, 'bio': bio, 'injury_news': injury_news}


@main.route('/player_quick_stats')
@login_required
def player_quick_stats():
    import traceback as _tb
    name = request.args.get('name', '').strip()
    pos  = request.args.get('pos', '').strip().upper()
    team = request.args.get('team', '').strip().upper()

    if not name:
        return jsonify({})

    try:
        roster_profile = _get_player_roster_profile(name, team, pos)
        espn_id = roster_profile['espn_id']
        bio = roster_profile['bio']
        injury_news = roster_profile['injury_news']

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

        # Team grade (OLine + position-specific grade), normalized 0-1
        team_grade = {}
        if team and team in _composite_grades:
            cg = _composite_grades[team]
            team_grade['OLine'] = cg.get('RB_OLine') if pos == 'RB' else cg.get('OLine')
            if pos in ('QB', 'RB', 'WR', 'TE'):
                team_grade[pos] = cg.get(pos)

        return jsonify({
            'espn_id': espn_id,
            'bio': bio,
            'stats': stats,
            'fantasy_points': fantasy_points,
            'ranking': ranking,
            'injury_news': injury_news,
            'team_grade': team_grade,
            'is_rookie': name in _rookie_names,
        })
    except Exception as _e:
        _tb.print_exc()
        return jsonify({'espn_id': None, 'bio': {}, 'stats': {}, 'fantasy_points': None,
                        'ranking': {}, 'injury_news': {}, '_error': str(_e)})


@main.route('/player/<path:name>')
@login_required
def player_profile(name):
    pos     = request.args.get('pos', '').strip().upper()
    team    = request.args.get('team', '').strip().upper()
    team    = _norm_team(team)  # Normalize LA -> LAR, etc.
    compare = request.args.get('compare', 'false').lower() == 'true'
    back_url = request.args.get('back', '/rankings/ppr')

    roster_profile = _get_player_roster_profile(name, team, pos)
    espn_id = roster_profile['espn_id']
    player_bio = roster_profile['bio']

    player_comps_data = _similarity_comps.get(name, [])

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
        player_comps_json=json.dumps(player_comps_data),
        is_rookie=name in _rookie_names,
    )


@main.route('/mockdraft')
@login_required
def mock_draft():
    return render_template('mockdraft.html')


@main.route('/mockdraft/players')
def mockdraft_players():
    import math, re as _re2
    scoring = request.args.get('scoring', 'ppr')
    source  = request.args.get('source', 'darkhorse').lower()

    def _with_injury_news(row):
        enriched = dict(row)
        name = enriched.get('Name') or enriched.get('Player') or ''
        pos = _re2.sub(r'\d+$', '', (enriched.get('Position') or '').strip()).upper()
        team = enriched.get('Team') or ''
        enriched['InjuryNews'] = _get_sleeper_player_update(name, team, pos)
        return enriched

    def _clean(players_list):
        out = []
        for row in players_list:
            pos = _re2.sub(r'\d+$', '', (row.get('Position') or '')).strip().upper()
            if pos in ('K', 'DEF', 'DST', 'P'):
                continue
            clean_row = {
                k: (None if isinstance(v, float) and math.isnan(v) else v)
                for k, v in row.items()
            }
            out.append(_with_injury_news(clean_row))
        return out

    if source == 'darkhorse':
        records = _model_table.get(scoring) or _model_table.get('ppr') or []
        return jsonify(_clean(records))

    # External ADP source — build player list from ADP DataFrame
    adp_map = {'sleeper': _sleeper_adp, 'espn': _espn_adp}
    adp_dict = adp_map.get(source)
    if adp_dict is None:
        # Unknown source — fall back to darkhorse
        records = _model_table.get(scoring) or _model_table.get('ppr') or []
        return jsonify(_clean(records))

    adp_df = adp_dict.get(scoring)
    if adp_df is None:
        adp_df = adp_dict.get('ppr')
    if adp_df is None or adp_df.empty:
        records = _model_table.get(scoring) or _model_table.get('ppr') or []
        return jsonify(_clean(records))

    # Also pull bye weeks from existing model table for enrichment
    bye_lookup = {}
    for row in (_model_table.get('ppr') or []):
        bye_lookup[_normalize_name(row.get('Name', ''))] = row.get('Bye Week')

    players_out = []
    for i, row in adp_df.iterrows():
        pos = (row.get('position') or '').upper()
        if pos in ('K', 'DEF', 'DST', 'P', ''):
            continue
        name = row.get('player_name', '') or ''
        if not name:
            continue
        try:
            rank = int(row['adp_rank'])
        except (ValueError, TypeError):
            continue
        name_key = row.get('name_key') or _normalize_name(name)
        team = row.get('team', '')
        if team is None or (isinstance(team, float) and math.isnan(team)):
            team = ''
        players_out.append({
            'Rank':     rank,
            'Name':     name,
            'Position': pos,
            'Team':     str(team),
            'ADP':      rank,
            'Bye Week': bye_lookup.get(name_key, ''),
        })

    return jsonify([_with_injury_news(row) for row in players_out])


@main.route('/mockdraft/save', methods=['POST'])
@login_required
def mockdraft_save():
    data = request.get_json()
    draft = MockDraft(
        user_id=g.user.id,
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
        msg['To'] = g.user.email
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, g.user.email, msg.as_string())

        return jsonify({'message': f'Draft emailed to {g.user.email}!'})
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
    drafts = MockDraft.query.filter_by(user_id=g.user.id).order_by(MockDraft.created_at.desc()).all()
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
    if draft.user_id != g.user.id:
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
    if draft.user_id != g.user.id:
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

# ══════════════════════════════════════════════════════════════════
#  DRAFT BOARD — helpers
# ══════════════════════════════════════════════════════════════════

def _detect_sleeper_scoring(scoring_settings):
    """Infer PPR / half_ppr / standard from a Sleeper scoring_settings dict."""
    rec = float(scoring_settings.get('rec', 0) or 0)
    if rec >= 1.0:
        return 'ppr'
    if rec >= 0.5:
        return 'half_ppr'
    return 'standard'


def _parse_sleeper_roster_positions(roster_positions):
    """Convert Sleeper roster_positions list to our slot-count dict."""
    slots = {'QB': 0, 'RB': 0, 'WR': 0, 'TE': 0, 'FLEX': 0, 'K': 0, 'DST': 0, 'bench': 0}
    for pos in (roster_positions or []):
        pos = str(pos).upper()
        if pos == 'QB':
            slots['QB'] += 1
        elif pos == 'RB':
            slots['RB'] += 1
        elif pos == 'WR':
            slots['WR'] += 1
        elif pos == 'TE':
            slots['TE'] += 1
        elif pos in ('FLEX', 'WR,RB,TE', 'RB,WR,TE', 'WR/RB/TE', 'RB/WR/TE'):
            slots['FLEX'] += 1
        elif pos == 'K':
            slots['K'] += 1
        elif pos in ('DEF', 'DST'):
            slots['DST'] += 1
        elif pos == 'BN':
            slots['bench'] += 1
        # IR slots are excluded from draft round count
    return slots


def _format_sleeper_pick(pick, roster_id_to_slot=None):
    """Normalise a raw Sleeper pick object into our unified format.

    roster_id_to_slot: {roster_id (int) → draft_slot (int, 1-indexed)}
    When provided, uses the actual picking team's slot (handles traded picks).
    """
    meta  = pick.get('metadata') or {}
    first = meta.get('first_name', '')
    last  = meta.get('last_name', '')
    name  = f'{first} {last}'.strip()

    # `roster_id` / `picked_by` = who actually made this pick (after any trades)
    roster_id = pick.get('roster_id') or pick.get('picked_by') or 0
    try:
        roster_id = int(roster_id)
    except (TypeError, ValueError):
        roster_id = 0

    if roster_id_to_slot and roster_id in roster_id_to_slot:
        actual_slot = roster_id_to_slot[roster_id]
    else:
        actual_slot = pick.get('draft_slot', 1)

    return {
        'player_id':     pick.get('player_id', ''),
        'name':          name,
        'position':      meta.get('position', '').upper(),
        'nfl_team':      meta.get('team', ''),
        'round':         pick.get('round', 1),
        'pick_no':       pick.get('pick_no', 0),
        'draft_slot':    actual_slot,
        'roster_id':     roster_id,
        'original_slot': pick.get('draft_slot', 1),
    }


# ── ESPN draft-board helpers ───────────────────────────────────────

_ESPN_POS_MAP = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST'}
_ESPN_SLOT_MAP = {
    0: 'QB', 2: 'RB', 4: 'WR', 6: 'TE', 23: 'FLEX',
    17: 'K', 16: 'DST', 20: 'Bench', 21: 'IR',
}
_ESPN_TEAM_ID_MAP = {
    1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',
    9:'GB',10:'TEN',11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',
    16:'MIN',17:'NE',18:'NO',19:'NYG',20:'NYJ',21:'PHI',22:'ARI',
    23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',28:'WAS',29:'CAR',
    30:'JAX',33:'BAL',34:'HOU',
}


def _espn_api_fetch(league_id, year, views, cookies=None):
    """Make an ESPN fantasy API call.  Returns (data, error_key)."""
    url = (f'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl'
           f'/seasons/{year}/segments/0/leagues/{league_id}')
    params = [('view', v) for v in views]
    jar = {}
    if cookies:
        s2 = cookies.get('espn_s2') or ''
        swid = cookies.get('swid') or ''
        if s2 and swid:
            jar = {'espn_s2': s2, 'SWID': swid}
    resp = requests.get(url, params=params, cookies=jar, timeout=15)
    if resp.status_code == 401:
        return None, 'private'
    if resp.status_code == 404:
        return None, 'not_found'
    resp.raise_for_status()
    return resp.json(), None


# In-memory cache for ESPN player map (espn_id → {name, position, team})
_espn_player_cache = {'ts': 0, 'data': {}}
_ESPN_PLAYER_CACHE_TTL = 3600  # 1 hour


def _get_espn_player_map(year=None):
    """Fetch + cache ESPN NFL player dict.  Returns {player_id: {name, position, team}}."""
    import time as _time, json as _json
    now = _time.time()
    if now - _espn_player_cache['ts'] < _ESPN_PLAYER_CACHE_TTL and _espn_player_cache['data']:
        return _espn_player_cache['data']
    if year is None:
        year = datetime.utcnow().year
    try:
        fantasy_filter = _json.dumps({
            'players': {'limit': 2000, 'filterActive': {'value': True}}
        })
        url = (f'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl'
               f'/seasons/{year}/players?view=kona_player_info')
        resp = requests.get(url,
                            headers={'X-Fantasy-Filter': fantasy_filter,
                                     'Accept': 'application/json'},
                            timeout=20)
        if resp.status_code == 200:
            slim = {}
            for entry in resp.json():
                p = entry.get('player') if isinstance(entry, dict) else entry
                if not p:
                    p = entry
                pid = p.get('id') or entry.get('id')
                name = p.get('fullName', '')
                if not name or not pid:
                    continue
                pos = _ESPN_POS_MAP.get(p.get('defaultPositionId', 0), '')
                team = _ESPN_TEAM_ID_MAP.get(p.get('proTeamId', 0), '')
                slim[int(pid)] = {'name': name, 'position': pos, 'team': team}
            _espn_player_cache['ts'] = now
            _espn_player_cache['data'] = slim
            return slim
    except Exception:
        pass
    return _espn_player_cache['data']


def _detect_espn_scoring(settings):
    """Infer PPR / half_ppr / standard from ESPN league settings."""
    scoring_items = (settings.get('scoringSettings') or {}).get('scoringItems') or []
    for item in scoring_items:
        # statId 53 = receivingReceptions
        if item.get('statId') == 53:
            val = float(item.get('pointsOverrides', {}).get('53', item.get('points', 0)))
            if val >= 1.0:
                return 'ppr'
            if val >= 0.5:
                return 'half_ppr'
            return 'standard'
    return 'standard'


def _parse_espn_roster_slots(settings):
    """Convert ESPN lineupSlotCounts to our unified slot-count dict."""
    counts = (settings.get('rosterSettings') or {}).get('lineupSlotCounts') or {}
    # ESPN uses string keys in JSON
    slot_mapping = {
        '0': 'QB', '2': 'RB', '4': 'WR', '6': 'TE', '23': 'FLEX',
        '17': 'K', '16': 'DST', '20': 'bench',
    }
    slots = {'QB': 0, 'RB': 0, 'WR': 0, 'TE': 0, 'FLEX': 0, 'K': 0, 'DST': 0, 'bench': 0}
    for slot_id, our_key in slot_mapping.items():
        slots[our_key] = int(counts.get(slot_id, counts.get(int(slot_id), 0)))
    return slots


def _espn_starter_slot_labels(settings):
    """Build a flat list of starter slot labels like ['QB','RB','RB','WR','WR','TE','FLEX','K','DST']."""
    slots = _parse_espn_roster_slots(settings)
    labels = []
    for pos in ('QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'DST'):
        labels.extend([pos] * slots.get(pos, 0))
    return labels


def _format_espn_pick(pick, team_id_to_slot, player_map, num_teams=12):
    """Normalise an ESPN draft pick into our unified format.

    pick_no must be the OVERALL pick number (1-indexed, continuous) because
    the frontend's applyPick() feeds it to pickToSlot() which expects that.
    """
    pid = pick.get('playerId', 0)
    p = player_map.get(int(pid), {})
    team_id = pick.get('teamId', 0)
    overall = pick.get('overallPickNumber', 0)
    slot = team_id_to_slot.get(team_id, team_id)

    # ESPN may not always return roundId — calculate from overallPickNumber
    round_id = pick.get('roundId', 0)
    if not round_id and overall and num_teams:
        round_id = ((overall - 1) // num_teams) + 1

    return {
        'player_id':     str(pid),
        'name':          p.get('name', f'Player {pid}'),
        'position':      p.get('position', '??'),
        'nfl_team':      p.get('team', ''),
        'round':         round_id or 1,
        'pick_no':       overall,    # OVERALL pick number — frontend expects this
        'draft_slot':    slot,
        'roster_id':     team_id,
        'original_slot': slot,
    }


# ══════════════════════════════════════════════════════════════════
#  DRAFT BOARD — routes
# ══════════════════════════════════════════════════════════════════

@main.route('/draft-board')
@login_required
def draft_board():
    return render_template('draft_board.html')


@main.route('/draft-board/sleeper/lookup', methods=['POST'])
@login_required
def draft_board_sleeper_lookup():
    """Given a Sleeper username, return their NFL leagues for the current season."""
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'Username required'}), 400

    try:
        user_resp = requests.get(f'https://api.sleeper.app/v1/user/{username}', timeout=8)
        if user_resp.status_code != 200 or not user_resp.json():
            return jsonify({'error': 'Sleeper user not found'}), 404
        user_data = user_resp.json()
        user_id   = user_data.get('user_id')

        season = datetime.utcnow().year
        leagues_resp = requests.get(
            f'https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{season}',
            timeout=8,
        )
        leagues = leagues_resp.json() if leagues_resp.status_code == 200 else []

        return jsonify({
            'user_id':      user_id,
            'display_name': user_data.get('display_name', username),
            'leagues': [
                {
                    'league_id':  lg.get('league_id'),
                    'name':       lg.get('name', 'Unnamed League'),
                    'num_teams':  lg.get('total_rosters', 12),
                    'status':     lg.get('status', ''),
                    'scoring':    _detect_sleeper_scoring(lg.get('scoring_settings') or {}),
                }
                for lg in (leagues or [])
            ],
        })
    except requests.RequestException:
        return jsonify({'error': 'Failed to connect to Sleeper API'}), 503


@main.route('/draft-board/sleeper/connect', methods=['POST'])
@login_required
def draft_board_sleeper_connect():
    """Connect to a specific Sleeper league: return draft metadata + existing picks."""
    data            = request.get_json(silent=True) or {}
    league_id       = (data.get('league_id') or '').strip()
    sleeper_user_id = (data.get('sleeper_user_id') or '').strip()

    if not league_id:
        return jsonify({'error': 'league_id required'}), 400

    try:
        # League metadata
        lg_resp = requests.get(f'https://api.sleeper.app/v1/league/{league_id}', timeout=8)
        if lg_resp.status_code != 200:
            return jsonify({'error': 'League not found'}), 404
        league    = lg_resp.json()
        scoring   = _detect_sleeper_scoring(league.get('scoring_settings') or {})
        num_teams = league.get('total_rosters', 12)
        roster_slots = _parse_sleeper_roster_positions(league.get('roster_positions') or [])

        # Detect dynasty / keeper leagues
        # Sleeper returns type as an integer: 0=redraft, 1=keeper, 2=dynasty
        # It can also be a string in some endpoints, so normalise both.
        league_settings = league.get('settings') or {}
        raw_type = league.get('type') or league_settings.get('type') or 0
        _type_int_map = {0: 'redraft', 1: 'keeper', 2: 'dynasty'}
        if isinstance(raw_type, int):
            league_type = _type_int_map.get(raw_type, 'redraft')
        else:
            league_type = str(raw_type).lower() or 'redraft'
        is_dynasty = league_type in ('dynasty', 'keeper')

        # Users map: user_id → display_name
        users_resp = requests.get(f'https://api.sleeper.app/v1/league/{league_id}/users', timeout=8)
        users_data = users_resp.json() if users_resp.status_code == 200 else []
        user_map   = {u['user_id']: u.get('display_name') or u.get('user_id', '') for u in (users_data or [])}

        # Drafts — prefer in-progress, then pre_draft, then most recent complete
        drafts_resp = requests.get(f'https://api.sleeper.app/v1/league/{league_id}/drafts', timeout=8)
        drafts = drafts_resp.json() if drafts_resp.status_code == 200 else []
        if not drafts:
            return jsonify({'error': 'No draft found for this league'}), 404

        draft = None
        for status_pref in ('in_progress', 'pre_draft', 'complete'):
            for d in drafts:
                if d.get('status') == status_pref:
                    draft = d
                    break
            if draft:
                break
        if not draft:
            draft = drafts[0]

        draft_id       = draft.get('draft_id')
        draft_status   = draft.get('status', 'pre_draft')
        draft_settings = draft.get('settings') or {}

        # num_rounds: use the actual draft's rounds setting, not the roster size
        num_rounds = int(draft_settings.get('rounds') or 0)

        # slot_to_roster_id: the canonical Sleeper mapping of draft slot → roster_id
        # This is the most reliable source and accounts for pick trades.
        slot_to_roster = draft.get('slot_to_roster_id') or {}
        # Build inverse: roster_id (int) → slot (int, 1-indexed)
        roster_id_to_slot = {}
        for slot_str, rid in slot_to_roster.items():
            try:
                roster_id_to_slot[int(rid)] = int(slot_str)
            except (TypeError, ValueError):
                pass

        # Also build owner_to_slot from draft_order as a fallback
        draft_order   = draft.get('draft_order') or {}
        owner_to_slot = {}
        for uid, slot in draft_order.items():
            try:
                owner_to_slot[str(uid)] = int(slot)
            except (ValueError, TypeError):
                pass

        # Fetch full league rosters — needed for slot mapping and player lists
        rosters_resp = requests.get(f'https://api.sleeper.app/v1/league/{league_id}/rosters', timeout=8)
        rosters_data = rosters_resp.json() if rosters_resp.status_code == 200 else []

        # Build roster_id → slot if slot_to_roster was empty (older leagues)
        # Fallback: derive from draft_order + owner_id on roster
        if not roster_id_to_slot:
            for roster in (rosters_data or []):
                owner_id  = str(roster.get('owner_id') or '')
                roster_id = roster.get('roster_id')
                if roster_id and owner_id in owner_to_slot:
                    roster_id_to_slot[int(roster_id)] = owner_to_slot[owner_id]
                elif roster_id:
                    roster_id_to_slot[int(roster_id)] = int(roster_id)  # 1:1 fallback

        # Build team_names indexed by slot (0-indexed)
        team_names = [f'Team {i + 1}' for i in range(num_teams)]

        # Map roster_id → owner display name
        rid_to_name = {}
        for roster in (rosters_data or []):
            rid       = int(roster.get('roster_id') or 0)
            owner_id  = str(roster.get('owner_id') or '')
            slot      = roster_id_to_slot.get(rid)
            disp_name = user_map.get(owner_id, '')
            if disp_name:
                rid_to_name[rid] = disp_name
            if slot and disp_name:
                idx = slot - 1
                if 0 <= idx < num_teams:
                    team_names[idx] = disp_name

        # Fallback: fill names from draft_order if still missing
        for uid, slot in draft_order.items():
            try:
                idx = int(slot) - 1
                if 0 <= idx < num_teams and team_names[idx] == f'Team {idx + 1}':
                    team_names[idx] = user_map.get(str(uid), team_names[idx])
            except (ValueError, TypeError):
                pass

        # Determine user's draft slot (1-indexed), or 0 if user not in this league
        user_slot = 0
        if sleeper_user_id:
            # Try draft_order first
            for uid, slot in draft_order.items():
                if str(uid) == str(sleeper_user_id):
                    try:
                        user_slot = int(slot)
                    except (ValueError, TypeError):
                        pass
                    break
            # Also check roster owner_id
            if user_slot == 0:
                for roster in (rosters_data or []):
                    if str(roster.get('owner_id') or '') == str(sleeper_user_id):
                        rid  = int(roster.get('roster_id') or 1)
                        slot = roster_id_to_slot.get(rid)
                        if slot:
                            user_slot = slot
                        break
        # If no sleeper_user_id provided at all, default to slot 1
        if not sleeper_user_id:
            user_slot = 1

        # Fetch existing draft picks — pass roster_id_to_slot so traded picks are attributed correctly
        picks_resp = requests.get(f'https://api.sleeper.app/v1/draft/{draft_id}/picks', timeout=8)
        picks_raw  = picks_resp.json() if picks_resp.status_code == 200 else []

        # If num_rounds still 0, infer from picks
        if num_rounds <= 0 and picks_raw:
            num_rounds = max((p.get('round', 1) for p in picks_raw), default=1)
        if num_rounds <= 0:
            num_rounds = max(sum(v for k, v in roster_slots.items()), 1)

        picks = [_format_sleeper_pick(p, roster_id_to_slot) for p in picks_raw]

        # Resolve player IDs → names
        player_map = _get_sleeper_player_map()

        # Starter slot labels (positions that are actual starters, not BN/IR/TAXI)
        _non_starter = {'BN', 'IR', 'TAXI'}
        starter_slot_labels = [
            p for p in (league.get('roster_positions') or [])
            if p not in _non_starter
        ]

        def _resolve(pid):
            """Return a player dict from the Sleeper player map, or None."""
            if not pid or str(pid) == '0':
                return None
            p = player_map.get(str(pid))
            if not p:
                return None
            return {'id': pid, 'name': p['name'], 'position': p['position'], 'team': p['team']}

        # Build structured team_rosters with starters/bench/reserve/taxi in Sleeper order
        empty_roster = {
            'starters':          [],
            'starter_slots':     starter_slot_labels,
            'bench':             [],
            'reserve':           [],
            'taxi':              [],
        }
        team_rosters = [None] * num_teams

        for roster in (rosters_data or []):
            rid      = int(roster.get('roster_id') or 1)
            owner_id = str(roster.get('owner_id') or '')
            slot     = roster_id_to_slot.get(rid, rid)          # 1-indexed
            idx      = max(0, min(slot - 1, num_teams - 1))     # 0-indexed

            all_ids     = set(roster.get('players') or [])
            starter_ids = roster.get('starters') or []
            reserve_ids = set(roster.get('reserve') or [])
            taxi_ids    = set(roster.get('taxi') or [])
            starter_set = set(pid for pid in starter_ids if pid and pid != '0')
            bench_ids   = [
                pid for pid in all_ids
                if pid not in starter_set and pid not in reserve_ids and pid not in taxi_ids
            ]

            # Starters: preserve Sleeper order, pair with slot label
            starters_out = []
            for pid, label in zip(starter_ids, starter_slot_labels + ['?'] * 10):
                p = _resolve(pid)
                starters_out.append({
                    'slot':     label,
                    'player':   p,             # None = empty slot
                })

            team_rosters[idx] = {
                'starters':      starters_out,
                'starter_slots': starter_slot_labels,
                'bench':         [p for p in (_resolve(pid) for pid in bench_ids) if p],
                'reserve':       [p for p in (_resolve(pid) for pid in reserve_ids) if p],
                'taxi':          [p for p in (_resolve(pid) for pid in taxi_ids) if p],
            }

            # Backfill team name from owner if still generic
            if team_names[idx] == f'Team {idx + 1}' and owner_id in user_map:
                team_names[idx] = user_map[owner_id]

        # Fill any slots that had no roster data
        team_rosters = [r if r is not None else dict(empty_roster) for r in team_rosters]

        # Flat list of every player name on any roster, resolved via Sleeper's player map.
        # Used by the frontend to reliably mark players as drafted (avoids name-suffix mismatches).
        roster_player_names = []
        for roster in (rosters_data or []):
            for pid in (roster.get('players') or []):
                p = player_map.get(str(pid))
                if p and p.get('name'):
                    roster_player_names.append(p['name'])

        # Build standings from roster records
        standings = []
        for roster in (rosters_data or []):
            rid       = int(roster.get('roster_id') or 0)
            r_settings = roster.get('settings') or {}
            slot      = roster_id_to_slot.get(rid, rid)
            idx       = max(0, min(slot - 1, num_teams - 1))
            name      = team_names[idx] if 0 <= idx < len(team_names) else f'Team {idx + 1}'
            standings.append({
                'slot':     slot,
                'name':     name,
                'wins':     r_settings.get('wins', 0),
                'losses':   r_settings.get('losses', 0),
                'ties':     r_settings.get('ties', 0),
                'pts_for':  round(r_settings.get('fpts', 0) + r_settings.get('fpts_decimal', 0) / 100, 1),
                'seed':     0,
                'rank':     0,
            })
        standings.sort(key=lambda s: (-s['wins'], -s['pts_for']))

        # Resolve earliest season by following previous_league_id chain (max 15 hops)
        league_start_year = int(league.get('season') or datetime.utcnow().year)
        prev_lid = league.get('previous_league_id')
        hops = 0
        while prev_lid and hops < 15:
            try:
                prev_resp = requests.get(
                    f'https://api.sleeper.app/v1/league/{prev_lid}', timeout=5)
                if prev_resp.status_code != 200:
                    break
                prev_lg = prev_resp.json()
                prev_season = prev_lg.get('season')
                if prev_season:
                    league_start_year = int(prev_season)
                prev_lid = prev_lg.get('previous_league_id')
                hops += 1
            except Exception:
                break

        return jsonify({
            'draft_id':            draft_id,
            'league_name':         league.get('name', 'My League'),
            'num_teams':           num_teams,
            'num_rounds':          num_rounds,
            'scoring':             scoring,
            'roster_slots':        roster_slots,
            'starter_slot_labels': starter_slot_labels,
            'team_names':          team_names,
            'user_slot':           user_slot,
            'draft_status':        draft_status,
            'league_type':         league_type,
            'picks':               picks,
            'team_rosters':        team_rosters,
            'roster_player_names': roster_player_names,
            'season':              league.get('season') or datetime.utcnow().year,
            'previous_league_id':  league.get('previous_league_id'),
            'standings':           standings,
            'league_start_year':   league_start_year,
        })
    except requests.RequestException:
        return jsonify({'error': 'Failed to connect to Sleeper API'}), 503


@main.route('/draft-board/sleeper/sync')
@login_required
def draft_board_sleeper_sync():
    """
    Unified polling endpoint — fetches picks AND current rosters in one call.
    Requires: draft_id, league_id (for rosters + slot mapping)
    Returns: { picks, team_rosters, draft_status }
    """
    draft_id  = request.args.get('draft_id', '').strip()
    league_id = request.args.get('league_id', '').strip()
    last_pick = int(request.args.get('last_pick', 0) or 0)
    if not draft_id or not league_id:
        return jsonify({'error': 'draft_id and league_id required'}), 400

    try:
        # ── 1. Draft metadata (need slot_to_roster_id for trade correction) ──
        draft_resp = requests.get(f'https://api.sleeper.app/v1/draft/{draft_id}', timeout=8)
        draft      = draft_resp.json() if draft_resp.status_code == 200 else {}
        draft_status    = draft.get('status', 'in_progress')
        slot_to_roster  = draft.get('slot_to_roster_id') or {}
        draft_order     = draft.get('draft_order') or {}

        # Build roster_id → slot mapping (accounts for traded picks)
        roster_id_to_slot = {}
        for slot_str, rid in slot_to_roster.items():
            try:
                roster_id_to_slot[int(rid)] = int(slot_str)
            except (TypeError, ValueError):
                pass

        # ── 2. Picks (with trade-corrected slot attribution) ──
        picks_resp = requests.get(f'https://api.sleeper.app/v1/draft/{draft_id}/picks', timeout=8)
        picks_raw  = picks_resp.json() if picks_resp.status_code == 200 else []

        # Fast path: no new picks and draft still going — skip expensive roster fetch
        if len(picks_raw) <= last_pick and draft_status not in ('complete', 'pre_draft'):
            return jsonify({
                'picks':               [],
                'team_rosters':        None,
                'draft_status':        draft_status,
                'roster_player_names': None,
                'pick_count':          len(picks_raw),
            })

        # If slot_to_roster was empty, fall back to roster_id derived from rosters endpoint
        need_roster_fallback = not roster_id_to_slot

        picks = [_format_sleeper_pick(p, roster_id_to_slot) for p in picks_raw]

        # ── 3. Current rosters (starters / bench / IR / taxi) ──
        rosters_resp = requests.get(f'https://api.sleeper.app/v1/league/{league_id}/rosters', timeout=8)
        rosters_data = rosters_resp.json() if rosters_resp.status_code == 200 else []

        # If we need a fallback slot mapping, derive from roster owner + draft_order
        if need_roster_fallback:
            users_resp = requests.get(f'https://api.sleeper.app/v1/league/{league_id}/users', timeout=8)
            users_data = users_resp.json() if users_resp.status_code == 200 else []
            owner_to_slot_fb = {}
            for u in (users_data or []):
                uid  = u.get('user_id', '')
                slot = draft_order.get(uid)
                if slot:
                    try:
                        owner_to_slot_fb[str(uid)] = int(slot)
                    except (TypeError, ValueError):
                        pass
            for roster in (rosters_data or []):
                rid      = roster.get('roster_id')
                owner_id = str(roster.get('owner_id') or '')
                slot     = owner_to_slot_fb.get(owner_id, rid)
                if rid and slot:
                    try:
                        roster_id_to_slot[int(rid)] = int(slot)
                    except (TypeError, ValueError):
                        pass
            # Re-format picks with the now-populated mapping
            picks = [_format_sleeper_pick(p, roster_id_to_slot) for p in picks_raw]

        player_map   = _get_sleeper_player_map()
        _non_starter = {'BN', 'IR', 'TAXI'}

        # Get league roster_positions for starter slot labels
        league_resp   = requests.get(f'https://api.sleeper.app/v1/league/{league_id}', timeout=8)
        league_data   = league_resp.json() if league_resp.status_code == 200 else {}
        starter_slots = [
            p for p in (league_data.get('roster_positions') or [])
            if p not in _non_starter
        ]

        def _resolve(pid):
            if not pid or str(pid) == '0':
                return None
            p = player_map.get(str(pid))
            return {'id': pid, 'name': p['name'], 'position': p['position'], 'team': p['team']} if p else None

        num_teams    = league_data.get('total_rosters', len(rosters_data))
        team_rosters = [None] * num_teams

        for roster in (rosters_data or []):
            rid      = int(roster.get('roster_id') or 1)
            owner_id = str(roster.get('owner_id') or '')
            slot     = roster_id_to_slot.get(rid, rid)
            idx      = max(0, min(slot - 1, num_teams - 1))

            all_ids     = set(roster.get('players') or [])
            starter_ids = roster.get('starters') or []
            reserve_ids = set(roster.get('reserve') or [])
            taxi_ids    = set(roster.get('taxi') or [])
            starter_set = set(pid for pid in starter_ids if pid and pid != '0')
            bench_ids   = [
                pid for pid in all_ids
                if pid not in starter_set and pid not in reserve_ids and pid not in taxi_ids
            ]

            starters_out = []
            for pid, label in zip(starter_ids, starter_slots + ['?'] * 10):
                starters_out.append({'slot': label, 'player': _resolve(pid)})

            team_rosters[idx] = {
                'starters': starters_out,
                'bench':    [p for p in (_resolve(pid) for pid in bench_ids) if p],
                'reserve':  [p for p in (_resolve(pid) for pid in reserve_ids) if p],
                'taxi':     [p for p in (_resolve(pid) for pid in taxi_ids) if p],
            }

        team_rosters = [r if r is not None else {'starters': [], 'bench': [], 'reserve': [], 'taxi': []} for r in team_rosters]

        # Flat list of every player name on any roster (Sleeper player map names).
        # Sent to the frontend so it can reliably mark players as drafted.
        roster_player_names = []
        for roster in (rosters_data or []):
            for pid in (roster.get('players') or []):
                p = player_map.get(str(pid))
                if p and p.get('name'):
                    roster_player_names.append(p['name'])

        return jsonify({
            'picks':               picks,
            'team_rosters':        team_rosters,
            'draft_status':        draft_status,
            'roster_player_names': roster_player_names,
            'pick_count':          len(picks_raw),
        })

    except requests.RequestException:
        return jsonify({'error': 'Sleeper API unavailable'}), 503


# ── ESPN draft-board routes ───────────────────────────────────────

@main.route('/draft-board/espn/lookup', methods=['POST'])
@login_required
def draft_board_espn_lookup():
    """Validate an ESPN league ID and return league info for confirmation."""
    data = request.get_json(silent=True) or {}
    league_id = (data.get('league_id') or '').strip()
    if not league_id:
        return jsonify({'error': 'League ID required'}), 400

    cookies = {}
    if data.get('espn_s2') and data.get('swid'):
        cookies = {'espn_s2': data['espn_s2'], 'swid': data['swid']}

    year = datetime.utcnow().year
    try:
        resp_data, err = _espn_api_fetch(league_id, year, ['mSettings', 'mTeam'], cookies or None)
        if err == 'private':
            return jsonify({
                'error': 'private',
                'message': 'This league is private. Please provide your ESPN cookies (SWID and espn_s2).',
            }), 401
        if err == 'not_found':
            return jsonify({'error': 'not_found', 'message': 'League not found. Check your league ID.'}), 404

        settings = resp_data.get('settings') or {}
        teams = resp_data.get('teams') or []

        scoring = _detect_espn_scoring(settings)

        team_list = []
        for t in teams:
            owners = t.get('owners') or []
            owner_name = owners[0] if owners else ''
            # ESPN sometimes provides member objects in a different view
            team_list.append({
                'id':     t.get('id'),
                'name':   t.get('name', t.get('location', '') + ' ' + t.get('nickname', '')).strip(),
                'abbrev': t.get('abbrev', ''),
            })

        return jsonify({
            'league_id':   league_id,
            'league_name': settings.get('name', 'ESPN League'),
            'num_teams':   settings.get('size', len(teams)),
            'scoring':     scoring,
            'season':      year,
            'teams':       team_list,
        })
    except requests.RequestException:
        return jsonify({'error': 'Failed to connect to ESPN API'}), 503


@main.route('/draft-board/espn/connect', methods=['POST'])
@login_required
def draft_board_espn_connect():
    """Connect to an ESPN league: return draft metadata + existing picks + rosters."""
    data = request.get_json(silent=True) or {}
    league_id    = (data.get('league_id') or '').strip()
    user_team_id = data.get('user_team_id')
    if not league_id:
        return jsonify({'error': 'league_id required'}), 400

    cookies = {}
    if data.get('espn_s2') and data.get('swid'):
        cookies = {'espn_s2': data['espn_s2'], 'swid': data['swid']}

    year = int(data.get('year', 0)) or datetime.utcnow().year
    try:
        resp_data, err = _espn_api_fetch(
            league_id, year,
            ['mDraftDetail', 'mSettings', 'mTeam', 'mRoster'],
            cookies or None,
        )
        if err == 'private':
            return jsonify({'error': 'This league is private. Provide ESPN cookies.'}), 401
        if err == 'not_found':
            return jsonify({'error': f'No data found for the {year} season. The league may not have existed yet.'}), 404

        settings       = resp_data.get('settings') or {}
        teams          = resp_data.get('teams') or []
        draft_detail   = resp_data.get('draftDetail') or {}

        num_teams      = settings.get('size', len(teams))
        scoring        = _detect_espn_scoring(settings)
        roster_slots   = _parse_espn_roster_slots(settings)
        starter_labels = _espn_starter_slot_labels(settings)

        # Draft settings
        draft_settings = settings.get('draftSettings') or {}
        num_rounds     = int(draft_settings.get('rounds', 0))
        if num_rounds <= 0:
            num_rounds = sum(roster_slots.values())

        # Draft status
        in_progress = draft_detail.get('inProgress', False)
        drafted     = draft_detail.get('drafted', False)
        if in_progress:
            draft_status = 'in_progress'
        elif drafted:
            draft_status = 'complete'
        else:
            draft_status = 'pre_draft'

        # Build team_id → slot mapping from draft pick order or team index
        # ESPN teams have an 'id' field; draft slot order comes from draftSettings.pickOrder
        pick_order = draft_settings.get('pickOrder') or []
        team_id_to_slot = {}
        if pick_order:
            for slot_idx, tid in enumerate(pick_order):
                team_id_to_slot[tid] = slot_idx + 1  # 1-indexed
        else:
            # Fallback: use team list order
            for slot_idx, t in enumerate(sorted(teams, key=lambda x: x.get('id', 0))):
                team_id_to_slot[t.get('id')] = slot_idx + 1

        # Build team_names (0-indexed by slot)
        team_names = [f'Team {i + 1}' for i in range(num_teams)]
        for t in teams:
            tid  = t.get('id')
            slot = team_id_to_slot.get(tid)
            name = t.get('name', '').strip()
            if not name:
                name = (t.get('location', '') + ' ' + t.get('nickname', '')).strip()
            if slot and name:
                idx = slot - 1
                if 0 <= idx < num_teams:
                    team_names[idx] = name

        # Determine user's slot — None if the user's team doesn't exist in this season
        user_slot = None
        if user_team_id is not None:
            tid = int(user_team_id)
            # Check if this team ID actually exists in the league for this season
            team_ids_this_season = {t.get('id') for t in teams}
            if tid in team_ids_this_season:
                user_slot = team_id_to_slot.get(tid)
        if user_slot is None:
            user_slot = 0  # 0 signals "no user team" to the frontend

        # Format existing picks — skip unfilled placeholder slots (playerId <= 0)
        player_map = _get_espn_player_map(year)
        picks_raw  = draft_detail.get('picks') or []
        picks      = [
            _format_espn_pick(p, team_id_to_slot, player_map, num_teams)
            for p in picks_raw
            if (p.get('playerId') or 0) > 0
        ]

        # Build team_rosters from teams[].roster.entries
        team_rosters = [None] * num_teams
        roster_player_names = []

        for t in teams:
            tid  = t.get('id')
            slot = team_id_to_slot.get(tid, tid)
            idx  = max(0, min(slot - 1, num_teams - 1))

            entries = []
            roster_obj = t.get('roster') or {}
            entries = roster_obj.get('entries') or []

            starters_out = []
            bench_out    = []
            reserve_out  = []

            for entry in entries:
                lineup_slot_id = entry.get('lineupSlotId', 20)  # default to Bench
                ppe = entry.get('playerPoolEntry') or {}
                player_info = ppe.get('player') or {}
                pid  = player_info.get('id') or ppe.get('id', 0)
                name = player_info.get('fullName', '')
                pos  = _ESPN_POS_MAP.get(player_info.get('defaultPositionId', 0), '')
                team_abbr = _ESPN_TEAM_ID_MAP.get(player_info.get('proTeamId', 0), '')

                player_obj = {'id': str(pid), 'name': name, 'position': pos, 'team': team_abbr}
                if name:
                    roster_player_names.append(name)

                slot_label = _ESPN_SLOT_MAP.get(lineup_slot_id, 'Bench')
                if slot_label == 'IR':
                    reserve_out.append(player_obj)
                elif slot_label == 'Bench':
                    bench_out.append(player_obj)
                else:
                    starters_out.append({'slot': slot_label, 'player': player_obj})

            team_rosters[idx] = {
                'starters':      starters_out,
                'starter_slots': starter_labels,
                'bench':         bench_out,
                'reserve':       reserve_out,
                'taxi':          [],
            }

        team_rosters = [
            r if r is not None
            else {'starters': [], 'starter_slots': starter_labels, 'bench': [], 'reserve': [], 'taxi': []}
            for r in team_rosters
        ]

        # Build standings from team records (useful for historical seasons)
        standings = []
        for t in teams:
            tid  = t.get('id')
            slot = team_id_to_slot.get(tid, tid)
            idx  = max(0, min(slot - 1, num_teams - 1))
            rec  = (t.get('record') or {}).get('overall') or {}
            name = team_names[idx] if 0 <= idx < len(team_names) else f'Team {idx + 1}'
            standings.append({
                'slot':     slot,
                'name':     name,
                'wins':     rec.get('wins', 0),
                'losses':   rec.get('losses', 0),
                'ties':     rec.get('ties', 0),
                'pts_for':  round(rec.get('pointsFor', 0), 1),
                'seed':     t.get('playoffSeed', 0),
                'rank':     t.get('rankCalculatedFinal', 0),
            })
        # Sort by wins desc, then points for desc
        standings.sort(key=lambda s: (-s['wins'], -s['pts_for']))

        # Determine the earliest year the league existed
        # Probe backwards until we hit a 404 (max 10 years back for speed)
        league_start_year = year
        for probe_y in range(year - 1, max(year - 11, 2001), -1):
            try:
                _, probe_err = _espn_api_fetch(league_id, probe_y, ['mSettings'], cookies or None)
                if probe_err:
                    break
                league_start_year = probe_y
            except Exception:
                break

        return jsonify({
            'draft_id':            None,
            'league_name':         settings.get('name', 'ESPN League'),
            'num_teams':           num_teams,
            'num_rounds':          num_rounds,
            'scoring':             scoring,
            'roster_slots':        roster_slots,
            'starter_slot_labels': starter_labels,
            'team_names':          team_names,
            'user_slot':           user_slot,
            'draft_status':        draft_status,
            'league_type':         'redraft',
            'picks':               picks,
            'team_rosters':        team_rosters,
            'roster_player_names': roster_player_names,
            'season':              year,
            'standings':           standings,
            'league_start_year':   league_start_year,
        })
    except requests.RequestException:
        return jsonify({'error': 'Failed to connect to ESPN API'}), 503


@main.route('/draft-board/espn/sync')
@login_required
def draft_board_espn_sync():
    """Poll ESPN for live draft updates — mirrors sleeper/sync."""
    league_id = request.args.get('league_id', '').strip()
    if not league_id:
        return jsonify({'error': 'league_id required'}), 400

    cookies = {}
    espn_s2 = request.args.get('espn_s2', '').strip()
    swid    = request.args.get('swid', '').strip()
    if espn_s2 and swid:
        cookies = {'espn_s2': espn_s2, 'swid': swid}

    year = datetime.utcnow().year
    try:
        resp_data, err = _espn_api_fetch(
            league_id, year,
            ['mDraftDetail', 'mTeam', 'mRoster', 'mSettings'],
            cookies or None,
        )
        if err == 'private':
            return jsonify({'error': 'ESPN auth expired. Please re-enter your cookies.'}), 401
        if err == 'not_found':
            return jsonify({'error': 'League not found'}), 404

        settings     = resp_data.get('settings') or {}
        teams        = resp_data.get('teams') or []
        draft_detail = resp_data.get('draftDetail') or {}

        # Draft status
        in_progress = draft_detail.get('inProgress', False)
        drafted     = draft_detail.get('drafted', False)
        if in_progress:
            draft_status = 'in_progress'
        elif drafted:
            draft_status = 'complete'
        else:
            draft_status = 'pre_draft'

        # Build team_id → slot mapping
        draft_settings = settings.get('draftSettings') or {}
        pick_order = draft_settings.get('pickOrder') or []
        team_id_to_slot = {}
        if pick_order:
            for slot_idx, tid in enumerate(pick_order):
                team_id_to_slot[tid] = slot_idx + 1
        else:
            for slot_idx, t in enumerate(sorted(teams, key=lambda x: x.get('id', 0))):
                team_id_to_slot[t.get('id')] = slot_idx + 1

        num_teams      = settings.get('size', len(teams))
        starter_labels = _espn_starter_slot_labels(settings)

        # Format picks — skip unfilled placeholder slots (playerId <= 0)
        player_map = _get_espn_player_map(year)
        picks_raw  = draft_detail.get('picks') or []
        picks      = [
            _format_espn_pick(p, team_id_to_slot, player_map, num_teams)
            for p in picks_raw
            if (p.get('playerId') or 0) > 0
        ]

        # Rebuild rosters
        team_rosters = [None] * num_teams
        roster_player_names = []

        for t in teams:
            tid  = t.get('id')
            slot = team_id_to_slot.get(tid, tid)
            idx  = max(0, min(slot - 1, num_teams - 1))

            roster_obj = t.get('roster') or {}
            entries = roster_obj.get('entries') or []

            starters_out = []
            bench_out    = []
            reserve_out  = []

            for entry in entries:
                lineup_slot_id = entry.get('lineupSlotId', 20)
                ppe = entry.get('playerPoolEntry') or {}
                player_info = ppe.get('player') or {}
                pid  = player_info.get('id') or ppe.get('id', 0)
                name = player_info.get('fullName', '')
                pos  = _ESPN_POS_MAP.get(player_info.get('defaultPositionId', 0), '')
                team_abbr = _ESPN_TEAM_ID_MAP.get(player_info.get('proTeamId', 0), '')

                player_obj = {'id': str(pid), 'name': name, 'position': pos, 'team': team_abbr}
                if name:
                    roster_player_names.append(name)

                slot_label = _ESPN_SLOT_MAP.get(lineup_slot_id, 'Bench')
                if slot_label == 'IR':
                    reserve_out.append(player_obj)
                elif slot_label == 'Bench':
                    bench_out.append(player_obj)
                else:
                    starters_out.append({'slot': slot_label, 'player': player_obj})

            team_rosters[idx] = {
                'starters': starters_out,
                'bench':    bench_out,
                'reserve':  reserve_out,
                'taxi':     [],
            }

        team_rosters = [
            r if r is not None
            else {'starters': [], 'bench': [], 'reserve': [], 'taxi': []}
            for r in team_rosters
        ]

        return jsonify({
            'picks':               picks,
            'team_rosters':        team_rosters,
            'draft_status':        draft_status,
            'roster_player_names': roster_player_names,
        })

    except requests.RequestException:
        return jsonify({'error': 'ESPN API unavailable'}), 503


@main.route('/draft-board/save', methods=['POST'])
@login_required
def draft_board_save():
    """Upsert the user's draft board session (one session per user)."""
    data = request.get_json(silent=True) or {}
    existing = DraftBoardSession.query.filter_by(user_id=g.user.id).first()
    if existing:
        existing.source    = data.get('source', 'manual')
        existing.league_id = data.get('league_id')
        existing.draft_id  = data.get('draft_id')
        existing.settings  = json.dumps(data.get('settings', {}))
        existing.state     = json.dumps(data.get('state', {}))
        existing.last_pick = int(data.get('last_pick', 0))
        existing.updated_at = datetime.utcnow()
    else:
        db.session.add(DraftBoardSession(
            user_id   = g.user.id,
            source    = data.get('source', 'manual'),
            league_id = data.get('league_id'),
            draft_id  = data.get('draft_id'),
            settings  = json.dumps(data.get('settings', {})),
            state     = json.dumps(data.get('state', {})),
            last_pick = int(data.get('last_pick', 0)),
        ))
    db.session.commit()
    return jsonify({'saved': True})


@main.route('/draft-board/load')
@login_required
def draft_board_load():
    """Return the user's saved draft board session, if any."""
    sess = DraftBoardSession.query.filter_by(user_id=g.user.id).first()
    if not sess:
        return jsonify({'found': False})
    return jsonify({
        'found':      True,
        'source':     sess.source,
        'league_id':  sess.league_id,
        'draft_id':   sess.draft_id,
        'settings':   json.loads(sess.settings)   if sess.settings   else {},
        'state':      json.loads(sess.state)       if sess.state      else {},
        'last_pick':  sess.last_pick or 0,
        'updated_at': sess.updated_at.isoformat()  if sess.updated_at else None,
    })


@main.route('/draft-board/reset', methods=['POST'])
@login_required
def draft_board_reset():
    """Delete the user's saved draft board session so they can start fresh."""
    sess = DraftBoardSession.query.filter_by(user_id=g.user.id).first()
    if sess:
        db.session.delete(sess)
        db.session.commit()
    return jsonify({'reset': True})


# ── Saved leagues ─────────────────────────────────────────────

@main.route('/draft-board/leagues')
@login_required
def draft_board_leagues_list():
    """Return all leagues saved by the current user."""
    leagues = (SavedLeague.query
               .filter_by(user_id=g.user.id)
               .order_by(SavedLeague.last_accessed.desc())
               .all())
    return jsonify([{
        'league_id':       lg.league_id,
        'league_name':     lg.league_name,
        'source':          lg.source,
        'num_teams':       lg.num_teams,
        'scoring':         lg.scoring,
        'league_type':     lg.league_type,
        'sleeper_user_id': lg.sleeper_user_id,
        'espn_s2':         lg.espn_s2 if lg.source == 'espn' else None,
        'espn_swid':       lg.espn_swid if lg.source == 'espn' else None,
        'user_slot':       lg.user_slot,
        'last_accessed':   lg.last_accessed.isoformat() if lg.last_accessed else None,
    } for lg in leagues])


@main.route('/draft-board/leagues/save', methods=['POST'])
@login_required
def draft_board_leagues_save():
    """Upsert a saved league entry for the current user."""
    data      = request.get_json(silent=True) or {}
    league_id = (data.get('league_id') or '').strip()
    if not league_id:
        return jsonify({'error': 'league_id required'}), 400

    try:
        existing = SavedLeague.query.filter_by(user_id=g.user.id, league_id=league_id).first()
        if existing:
            existing.league_name    = data.get('league_name', existing.league_name)
            existing.num_teams      = data.get('num_teams', existing.num_teams)
            existing.scoring        = data.get('scoring', existing.scoring)
            existing.league_type    = data.get('league_type', existing.league_type)
            existing.sleeper_user_id = data.get('sleeper_user_id', existing.sleeper_user_id)
            existing.espn_s2        = data.get('espn_s2', existing.espn_s2)
            existing.espn_swid      = data.get('espn_swid', existing.espn_swid)
            existing.user_slot      = data.get('user_slot', existing.user_slot)
            existing.last_accessed  = datetime.utcnow()
        else:
            db.session.add(SavedLeague(
                user_id        = g.user.id,
                league_id      = league_id,
                league_name    = data.get('league_name', 'My League'),
                source         = data.get('source', 'sleeper'),
                num_teams      = data.get('num_teams', 12),
                scoring        = data.get('scoring', 'ppr'),
                league_type    = data.get('league_type', 'redraft'),
                sleeper_user_id = data.get('sleeper_user_id'),
                espn_s2        = data.get('espn_s2'),
                espn_swid      = data.get('espn_swid'),
                user_slot      = data.get('user_slot'),
            ))
        db.session.commit()
        return jsonify({'saved': True})
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@main.route('/draft-board/leagues/<league_id>', methods=['DELETE'])
@login_required
def draft_board_leagues_delete(league_id):
    """Remove a saved league from the user's account."""
    lg = SavedLeague.query.filter_by(user_id=g.user.id, league_id=league_id).first()
    if lg:
        db.session.delete(lg)
        db.session.commit()
    return jsonify({'deleted': True})


@main.route('/draft-board/ai-suggest', methods=['POST'])
@login_required
def draft_board_ai_suggest():
    """Return AI draft suggestions (in-draft) or full roster analysis (draft complete)."""
    data = request.get_json(silent=True) or {}

    # ── Draft-complete: full position-group analysis ───────────────────────
    if data.get('mode') == 'complete':
        roster              = data.get('roster') or {}
        league_type         = (data.get('league_type') or 'redraft').lower()
        is_dynasty          = league_type in ('dynasty', 'keeper')
        starter_slot_labels = data.get('starter_slot_labels') or []
        # team_label: 'you' for the user's own team, or the team's name for others.
        # Used to generate correctly-pronouned trade suggestions.
        raw_label  = (data.get('team_label') or 'you').strip()
        is_self    = raw_label.lower() == 'you'
        # Possessive: "Your RB group" vs "Team X's RB group"
        poss       = 'Your' if is_self else f"{raw_label}'s"
        # Subject: "you" vs "they" / "this team"
        subj       = 'you' if is_self else 'this team'

        # Derive which positions the league actually uses from starter slot labels.
        # FLEX-type slots expand to their component positions.
        _flex_expansion = {
            'FLEX':       {'RB', 'WR', 'TE'},
            'SUPER_FLEX': {'QB', 'RB', 'WR', 'TE'},
            'IDP_FLEX':   {'QB', 'RB', 'WR', 'TE', 'DB', 'LB', 'DL'},
            'REC_FLEX':   {'WR', 'TE'},
            'WRRB_FLEX':  {'WR', 'RB'},
        }
        _skip_slots = {'BN', 'IR', 'TAXI', 'DL', 'DB', 'LB'}  # non-scoring / IDP only
        league_positions = set()
        for slot in starter_slot_labels:
            su = slot.upper()
            if su in _skip_slots:
                continue
            if su in _flex_expansion:
                league_positions.update(_flex_expansion[su])
            else:
                league_positions.add(su)

        # Fall back to all standard skill positions if labels not provided
        if not league_positions:
            league_positions = {'QB', 'RB', 'WR', 'TE', 'K', 'DST'}

        # Ordered list of positions to analyze (only those in the league)
        _pos_order = ['QB', 'RB', 'WR', 'TE', 'K', 'DST']
        analyze_positions = [p for p in _pos_order if p in league_positions]

        # Reject empty rosters — can't grade what isn't there
        all_roster_players = (roster.get('starters') or []) + (roster.get('bench') or [])
        if not any(p and p.get('name') for p in all_roster_players):
            return jsonify({'mode': 'complete', 'position_groups': [], 'overall_grade': '—',
                            'strengths': [], 'needs': [], 'is_dynasty': is_dynasty,
                            'trade_suggestions': [], 'empty': True})

        # Frontend sends starters = exactly the filled starter slots from the right panel,
        # bench = everyone else. No slot-matching needed here.
        starters_by_pos = defaultdict(list)
        for p in (roster.get('starters') or []):
            if p and p.get('position'):
                starters_by_pos[p['position'].upper()].append(p)

        by_pos = defaultdict(list)
        for p in (roster.get('starters') or []):
            if p and p.get('position'):
                by_pos[p['position'].upper()].append(p)
        for p in (roster.get('bench') or []):
            if p and p.get('position'):
                by_pos[p['position'].upper()].append(p)

        # Per-position depth targets (dynasty needs much more depth)
        targets_depth = {
            'QB':  (3 if is_dynasty else 2),
            'RB':  (8 if is_dynasty else 4),
            'WR':  (9 if is_dynasty else 5),
            'TE':  (3 if is_dynasty else 2),
            'K':   1,
            'DST': 1,
        }

        grade_map = {'A': 4, 'B': 3, 'C': 2, 'D': 1, 'F': 0}

        def _grade(count, ideal, min_count):
            if count == 0:          return 'F'
            if count < min_count:   return 'D'
            ratio = count / max(ideal, 1)
            if ratio >= 0.85:       return 'A'
            if ratio >= 0.65:       return 'B'
            if ratio >= 0.45:       return 'C'
            return 'D'

        def _quality_grade(starters):
            """Grade quality based on actual starters' ranks.
            Lower rank = better player. Unranked starters (retired/inactive) count as rank 999.
            Returns grade A-F, or None only if the starters list is completely empty."""
            if not starters:
                return None
            # Unranked players (not in our rankings = likely inactive/retired) get a penalty rank
            ranks = [p.get('rank') if p.get('rank') is not None else 999 for p in starters]
            best_rank = min(ranks)
            avg_rank  = sum(ranks) / len(ranks)
            # Weight: 60% best starter, 40% average of starters
            combined  = best_rank * 0.6 + avg_rank * 0.4
            if combined <= 12:      return 'A'
            elif combined <= 25:    return 'B'
            elif combined <= 50:    return 'C'
            elif combined <= 80:    return 'D'
            else:                   return 'F'

        def _note(pos, count, depth_grade, all_players, qual_grade=None, starters=None):
            starters = starters or []
            # Only name players who have rank data — unranked players are likely inactive/retired
            ranked_starters = [p for p in starters if p.get('rank') is not None]
            top_starters = [p.get('name', '') for p in ranked_starters[:2] if p.get('name')]
            anchor = ' & '.join(top_starters) if top_starters else None

            # Also check bench for notable backup depth
            all_ranked = [p for p in all_players if p.get('rank') is not None]
            starter_names = {p.get('name') for p in starters}
            bench_ranked = [p for p in all_ranked if p.get('name') not in starter_names]

            depth_part = ''
            qual_part  = ''

            if depth_grade == 'F':
                return f'No {pos} on this roster — a critical gap.'
            if depth_grade == 'D':
                depth_part = f'Very thin at {pos} ({count} player{"s" if count != 1 else ""}) — needs depth.'
            elif depth_grade == 'A':
                depth_part = f'Loaded at {pos} ({count} players) — among the deepest in the league.'
            elif depth_grade == 'B':
                depth_part = f'Solid {pos} corps ({count} players) with quality depth behind the starters.'
            else:
                depth_part = f'Adequate {pos} depth ({count} players) — serviceable but not a strength.'

            if anchor:
                depth_part += f' Anchored by {anchor}.'
            elif bench_ranked and not anchor:
                backup_name = bench_ranked[0].get('name', '').split()[-1]
                depth_part += f' {backup_name} leads a thin starter group.'

            if qual_grade == 'A':
                qual_part = ' Elite-caliber starters at this position.'
            elif qual_grade == 'B':
                qual_part = ' Quality starters — above-average production expected.'
            elif qual_grade == 'C':
                qual_part = ' Average starter quality — manageable but not dominant.'
            elif qual_grade == 'D':
                qual_part = ' Below-average starters — a clear upgrade target.'
            elif qual_grade == 'F':
                qual_part = ' Low-end starters — significant weakness in the lineup.'

            return (depth_part + qual_part).strip()

        groups = []
        for pos in analyze_positions:
            all_players = by_pos.get(pos, [])
            starters    = starters_by_pos.get(pos, [])
            # Dedupe
            if pos in ('RB', 'WR', 'TE', 'QB'):
                seen = set()
                deduped = []
                for p in all_players:
                    nm = p.get('name', '')
                    if nm and nm not in seen:
                        seen.add(nm)
                        deduped.append(p)
                all_players = deduped
            # Sort by rank
            all_players.sort(key=lambda p: p.get('rank') or 9999)
            starters.sort(key=lambda p: p.get('rank') or 9999)
            count       = len(all_players)
            ideal       = targets_depth.get(pos, 2)
            depth_grade = _grade(count, ideal, 1)
            # Quality is based on actual starters; fall back to all players if no starter data
            qual_grade  = _quality_grade(starters) if starters else _quality_grade(all_players[:2])

            # Combined grade: average depth and quality grades when both available
            if qual_grade:
                depth_score = grade_map.get(depth_grade, 0)
                qual_score  = grade_map.get(qual_grade, 0)
                combined    = (depth_score * 0.5 + qual_score * 0.5)
                if combined >= 3.6:   grade = 'A'
                elif combined >= 3.0: grade = 'B'
                elif combined >= 2.0: grade = 'C'
                elif combined >= 1.0: grade = 'D'
                else:                 grade = 'F'
            else:
                grade = depth_grade

            # Show only the actual starters for this position in the card.
            # If no starters identified (e.g. manual mode fallback), show top-ranked players.
            display_players = starters if starters else all_players[:2]

            groups.append({
                'position':  pos,
                'count':     count,
                'grade':     grade,
                'note':      _note(pos, count, depth_grade, all_players, qual_grade, starters),
                'players':   [{'name': p.get('name', ''), 'team': p.get('team', '')}
                               for p in display_players if p.get('name')],
            })

        # Trade suggestions — specific, player-named recommendations
        trade_suggestions = []
        skill_positions = [p for p in analyze_positions if p not in ('K', 'DST')]
        grade_val = lambda g: grade_map.get(g, 0)

        surplus  = [g for g in groups if g['position'] in skill_positions and grade_val(g['grade']) >= 3]
        average  = [g for g in groups if g['position'] in skill_positions and grade_val(g['grade']) == 2]
        deficit  = [g for g in groups if g['position'] in skill_positions and grade_val(g['grade']) <= 1]

        def _top_names(group, n=2):
            """Return last names of top n players in group."""
            ps = group.get('players') or []
            names = [p['name'].split()[-1] for p in ps[:n] if p.get('name')]
            return names

        def _names_str(group, n=2):
            names = _top_names(group, n)
            if not names: return None
            return ' & '.join(names) if len(names) > 1 else names[0]

        # 1. Hard imbalances: stacked at one pos, thin at another
        for s in surplus:
            for d in deficit:
                if s['position'] == d['position']:
                    continue
                s_names = _names_str(s, 2)
                d_pos   = d['position']
                depth_note = f' ({s["count"]} {s["position"]}s drafted, graded {s["grade"]})'
                bait_note  = f' — {s_names} could be the centerpiece' if s_names else ''
                trade_suggestions.append(
                    f'{poss} {s["position"]} group is a clear strength{depth_note}{bait_note}. '
                    f'{poss} {d_pos} ({d["grade"]}) is a liability. '
                    f'Package {s["position"]} depth to acquire an elite {d_pos}.'
                )

        # 2. Quality upgrades: average group, surplus to deal
        for avg_g in average:
            pos = avg_g['position']
            for s in surplus:
                if s['position'] == pos:
                    continue
                s_names = _names_str(s, 1)
                avg_names = _names_str(avg_g, 1)
                from_note = f' — {s_names} has trade value' if s_names else ''
                starter_note = f' ({avg_names} is the current starter)' if avg_names else ''
                trade_suggestions.append(
                    f'{poss} {pos} group is graded {avg_g["grade"]}{starter_note}. '
                    f'There is {s["position"]} depth to move{from_note}. '
                    f'A {pos} upgrade here could push {subj} into contention.'
                )
                break  # one suggestion per average group

        # 3. Sell-high when stacked with no deficits
        if len(surplus) >= 2 and not deficit:
            s = surplus[0]
            s_names = _names_str(s, 2)
            sell_note = f'{s_names} represent' if s_names else f'The {s["position"]} depth represents'
            trade_suggestions.append(
                f'No critical weaknesses — strong, balanced roster. '
                f'{sell_note} surplus value at {s["position"]} ({s["grade"]}). '
                f'Consider dealing that depth for future picks or an elite player at any position.'
            )

        # 4. Warn if roster is balanced but star-less (all C grades)
        if not surplus and not deficit and len(average) >= 3:
            trade_suggestions.append(
                f'Roster is balanced but lacks a true alpha — no elite group stands out. '
                f'Look to consolidate by moving multiple average players for one proven starter.'
            )

        # Overall grade = weighted average (skill positions matter more)
        weight = {'QB': 2, 'RB': 3, 'WR': 3, 'TE': 2, 'K': 0.5, 'DST': 0.5}
        total_w, total_score = 0, 0
        for g in groups:
            w = weight.get(g['position'], 1)
            total_score += grade_map.get(g['grade'], 0) * w
            total_w += w
        avg = total_score / total_w if total_w else 2
        if avg >= 3.6:   overall = 'A'
        elif avg >= 3.1: overall = 'A-'
        elif avg >= 2.7: overall = 'B+'
        elif avg >= 2.3: overall = 'B'
        elif avg >= 1.8: overall = 'B-'
        elif avg >= 1.4: overall = 'C+'
        elif avg >= 1.0: overall = 'C'
        else:            overall = 'D'

        non_special = [p for p in analyze_positions if p not in ('K', 'DST')]
        strengths = [g['position'] for g in groups
                     if grade_map.get(g['grade'], 0) >= 3 and g['position'] in non_special]
        needs     = [g['position'] for g in groups
                     if grade_map.get(g['grade'], 0) <= 1 and g['position'] in non_special]

        return jsonify({
            'mode':              'complete',
            'position_groups':   groups,
            'overall_grade':     overall,
            'strengths':         strengths,
            'needs':             needs,
            'is_dynasty':        is_dynasty,
            'trade_suggestions': trade_suggestions,
        })

    # ── In-draft suggestions (existing logic) ─────────────────────────────
    data             = data  # already parsed above
    user_roster      = data.get('user_roster', [])
    roster_slots     = data.get('roster_slots', {'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 'FLEX': 1})
    available        = data.get('available_players', [])
    other_teams      = data.get('other_teams', [])
    pick_number      = int(data.get('pick_number', 0))
    picks_until_next = int(data.get('picks_until_next', 12))

    # --- Positional need ---
    filled = {}
    for pick in user_roster:
        pos = (pick.get('position') or pick.get('Position') or '').upper()
        filled[pos] = filled.get(pos, 0) + 1

    starter_needs = {
        'QB': int(roster_slots.get('QB', 1)),
        'RB': int(roster_slots.get('RB', 2)),
        'WR': int(roster_slots.get('WR', 2)),
        'TE': int(roster_slots.get('TE', 1)),
    }

    need_scores = {
        pos: max(0, needed - filled.get(pos, 0)) / max(needed, 1)
        for pos, needed in starter_needs.items()
    }
    sorted_needs = sorted(need_scores.items(), key=lambda x: -x[1])

    # --- Top targets (one from each most-needed position) ---
    targets, seen = [], set()
    for pos, score in sorted_needs:
        if score <= 0:
            continue
        for p in available:
            p_pos  = (p.get('Position') or '').upper()
            p_name = p.get('Name', '')
            if p_pos == pos and p_name not in seen:
                targets.append(p)
                seen.add(p_name)
                break
        if len(targets) >= 3:
            break

    # Fill remaining target slots with best available at any position
    if len(targets) < 3:
        for p in available:
            p_name = p.get('Name', '')
            if p_name not in seen:
                targets.append(p)
                seen.add(p_name)
            if len(targets) >= 3:
                break

    # --- Best available (top 3 regardless of position) ---
    best_available = available[:3]

    # --- Danger alerts: players likely taken before next pick ---
    alerts = []
    for p in available[:15]:
        adp = p.get('ADP') or p.get('Rank') or 999
        try:
            adp = float(adp)
        except (TypeError, ValueError):
            continue
        if adp <= pick_number + picks_until_next:
            pos = (p.get('Position') or '').upper()
            teams_needing = sum(
                1 for t in other_teams
                if sum(
                    1 for tp in (t.get('picks') or [])
                    if (tp.get('position') or '').upper() == pos
                ) < starter_needs.get(pos, 2)
            )
            alerts.append({
                'name':         p.get('Name', ''),
                'position':     pos,
                'adp':          adp,
                'teams_needing': teams_needing,
                'urgency':      'high' if teams_needing >= 2 or adp <= pick_number else 'medium',
            })

    return jsonify({
        'needs':          [{'position': pos, 'score': round(sc, 2)} for pos, sc in sorted_needs],
        'targets':        targets[:3],
        'best_available': best_available,
        'alerts':         alerts[:2],
    })


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
