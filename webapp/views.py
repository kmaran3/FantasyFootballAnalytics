from flask import Blueprint, render_template, url_for, flash, redirect, request, jsonify, current_app as app
from flask_login import login_user, current_user, logout_user, login_required
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from bs4 import BeautifulSoup
from webapp.forms import LoginForm, RegistrationForm
from webapp import db, User, UserRanking
import json

main = Blueprint('main', __name__)

engine = create_engine('sqlite:///webapp/my_database.db', echo=True)

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
    # Query the Full PPR table
    with engine.connect() as connection:  # Use the engine to establish a connection
        df = pd.read_sql(text('SELECT * FROM Full_PPR'), con=connection)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='PPR', user_rankings=saved)

@main.route('/rankings/half-ppr')
@login_required
def get_half_ppr_rankings():
    # Query the Half PPR table
    with engine.connect() as connection:
        df = pd.read_sql(text('SELECT * FROM Half_PPR'), con=connection)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='Half PPR', user_rankings=saved)

@main.route('/rankings/standard')
@login_required
def get_standard_rankings():
    # Query the Non PPR table
    with engine.connect() as connection:
        df = pd.read_sql(text('SELECT * FROM Non_PPR'), con=connection)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='Standard', user_rankings=saved)

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
    return render_template('rankings.html', table_data=table_data, table_type=ranking.name, user_rankings=saved, saved_ranking_id=ranking.id, saved_ranking_name=ranking.name)

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

def fetch_player_data():
    url = 'https://www.footballguys.com/adp'
    response = requests.get(url)
    player_data = []
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            name_td = row.find('td', class_='name sticky-col text-start')
            if name_td:
                name_a = name_td.find('a')
                if name_a:
                    player_name = name_a.get_text().strip()
                    tds = row.find_all('td')
                    if len(tds) >= 9:
                        espn_value = tds[8].get_text().strip()
                        player_data.append((player_name, espn_value))
        player_data_sorted = sorted(player_data, key=lambda x: int(x[1]) if x[1].isdigit() else float('inf'))
        return player_data_sorted
    else:
        return []
