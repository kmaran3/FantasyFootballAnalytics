from flask import Blueprint, render_template, url_for, flash, redirect, request, jsonify, current_app as app
from flask_login import login_user, current_user, logout_user, login_required
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from bs4 import BeautifulSoup
from pathlib import Path
from webapp.forms import LoginForm, RegistrationForm
from webapp import db, User, UserRanking
import json

main = Blueprint('main', __name__)

_DB_PATH = Path(__file__).resolve().parent.parent / 'webapp' / 'my_database.db'
engine = create_engine(f'sqlite:///{_DB_PATH}', echo=True)

_BASE_DIR = Path(__file__).parent.parent
_PICKLE_DIR = _BASE_DIR / 'Models' / 'PickleFiles'

# nfl_data_py uses 'LA' for Rams; our DB uses 'LAR'
_TEAM_ABBR_MAP = {'LA': 'LAR'}

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

    # QB stats (YearsBack=1 = 2023 season)
    qb_path = _PICKLE_DIR / 'final_qb_data.pkl'
    if qb_path.exists():
        df = pd.read_pickle(qb_path)
        df = df[(df['YearsBack'] == 1) & (df['season_type'] == 'REG')]
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
        df = df[(df['YearsBack'] == 1) & (df['season_type'] == 'REG')]
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
        df = df[(df['YearsBack'] == 1) & (df['season_type'] == 'REG')]
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
        import nfl_data_py as nfl
        schedule_df = nfl.import_schedules([2024])
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
    with engine.connect() as connection:
        df = pd.read_sql(text('SELECT * FROM Full_PPR'), con=connection)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    pd_json, ts_json, teams, bye_weeks = _ranking_extras(df)
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='PPR',
                           user_rankings=saved, player_details_json=pd_json,
                           team_schedule_json=ts_json, teams=teams, bye_weeks=bye_weeks)

@main.route('/rankings/half-ppr')
@login_required
def get_half_ppr_rankings():
    with engine.connect() as connection:
        df = pd.read_sql(text('SELECT * FROM Half_PPR'), con=connection)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    pd_json, ts_json, teams, bye_weeks = _ranking_extras(df)
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='Half PPR',
                           user_rankings=saved, player_details_json=pd_json,
                           team_schedule_json=ts_json, teams=teams, bye_weeks=bye_weeks)

@main.route('/rankings/standard')
@login_required
def get_standard_rankings():
    with engine.connect() as connection:
        df = pd.read_sql(text('SELECT * FROM Non_PPR'), con=connection)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    pd_json, ts_json, teams, bye_weeks = _ranking_extras(df)
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='Standard',
                           user_rankings=saved, player_details_json=pd_json,
                           team_schedule_json=ts_json, teams=teams, bye_weeks=bye_weeks)

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

@main.route('/mockdraft', methods=['GET', 'POST'])
@login_required
def mock_draft():
    if request.method == 'POST':
        draft_position = request.form['position']
        player_data = fetch_player_data()  # Call function to fetch data
        return render_template('mockdraft.html', player_data=player_data, draft_position=draft_position)
    else:
        return render_template('mockdraft.html')


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
        columns=df.columns.tolist()
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
