from flask import Flask
from flask.json.provider import DefaultJSONProvider
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
import os
from dotenv import load_dotenv

try:
    import numpy as _np
    class _NumpyJSONProvider(DefaultJSONProvider):
        def default(self, obj):
            if isinstance(obj, _np.floating): return float(obj)
            if isinstance(obj, _np.integer):  return int(obj)
            if isinstance(obj, _np.ndarray):  return obj.tolist()
            return super().default(obj)
except ImportError:
    _NumpyJSONProvider = None

# Initialize the database globally
db = SQLAlchemy()
_csrf = CSRFProtect()

class User(db.Model):
    id = db.Column(db.String(36), primary_key=True)        # Supabase UUID
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=True)     # display name / old username
    rankings = db.relationship('UserRanking', backref='user', lazy=True)

class UserRanking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False, default='Untitled')
    ranking_type = db.Column(db.String(50), nullable=False)  # Type of ranking: PPR, Half PPR, etc.
    ranking_data = db.Column(db.Text, nullable=False)  # Store the ranking data as JSON or plain text
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class MockDraft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    draft_type = db.Column(db.String(20), nullable=False)   # 'snake' or 'auction'
    scoring = db.Column(db.String(20), nullable=False)       # 'ppr', 'half_ppr', 'standard'
    settings = db.Column(db.Text, nullable=False)            # JSON: all league settings
    board = db.Column(db.Text, nullable=False)               # JSON: full draft board
    user_team = db.Column(db.Text, nullable=False)           # JSON: just user's picks


class SavedLeague(db.Model):
    __tablename__ = 'saved_league'
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    league_id      = db.Column(db.String(100), nullable=False)
    league_name    = db.Column(db.String(200))
    source         = db.Column(db.String(20), default='sleeper')
    num_teams      = db.Column(db.Integer)
    scoring        = db.Column(db.String(20))
    league_type    = db.Column(db.String(20))
    sleeper_user_id = db.Column(db.String(100))
    espn_s2        = db.Column(db.Text, nullable=True)
    espn_swid      = db.Column(db.String(50), nullable=True)
    user_slot      = db.Column(db.Integer)
    last_accessed  = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'league_id', name='uq_user_league'),)


class DraftBoardSession(db.Model):
    __tablename__ = 'draft_board_session'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source     = db.Column(db.String(20))       # 'sleeper' | 'manual' | 'espn' | 'yahoo'
    league_id  = db.Column(db.String(100))      # external league ID
    draft_id   = db.Column(db.String(100))      # external draft ID (Sleeper draft_id, etc.)
    settings   = db.Column(db.Text)             # JSON: {numTeams, scoringFormat, rosterSlots, teamNames, userSlot}
    state      = db.Column(db.Text)             # JSON: {board, drafted, userRoster, otherRosters, currentPickNo}
    last_pick  = db.Column(db.Integer, default=0)  # total picks recorded at last save


def _get_secret_key(app):
    env_name = (os.environ.get('FLASK_ENV') or 'development').lower()
    env_secret = os.environ.get('SECRET_KEY')

    if env_name == 'production' and not env_secret:
        raise RuntimeError('SECRET_KEY must be set in production environment')

    if env_secret:
        return env_secret

    # Keep a stable local secret in instance folder so sessions and CSRF work across restarts.
    key_file = os.path.join(app.instance_path, '.secret_key')
    if os.path.exists(key_file):
        with open(key_file, 'r', encoding='utf-8') as f:
            file_secret = f.read().strip()
            if file_secret:
                return file_secret

    generated = os.urandom(32).hex()
    with open(key_file, 'w', encoding='utf-8') as f:
        f.write(generated)
    return generated


def _is_production():
    return (os.environ.get('FLASK_ENV') or '').lower() == 'production'


def _get_database_uri(app):
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # Some providers still provide postgres:// URLs, but SQLAlchemy expects postgresql://
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        return db_url

    # Local fallback: SQLite in instance folder
    instance_path = os.path.join(app.instance_path, 'yourdatabase.db')
    return f'sqlite:///{instance_path}'

def create_app():
    load_dotenv()
    app = Flask(__name__)
    if _NumpyJSONProvider:
        app.json_provider_class = _NumpyJSONProvider
        app.json = _NumpyJSONProvider(app)
    
    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)
    
    # Load a stable secret key from environment (preferred) or instance file (local dev fallback).
    app.config['SECRET_KEY'] = _get_secret_key(app)
    
    # Database configuration - Supabase Postgres in production, SQLite fallback for local dev.
    app.config['SQLALCHEMY_DATABASE_URI'] = _get_database_uri(app)
    engine_opts = {'pool_pre_ping': True}
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if 'supabase' in db_uri or 'pooler' in db_uri:
        # Supavisor transaction-mode pooling: disable prepared statement caching
        engine_opts['connect_args'] = {'options': '-c statement_timeout=30000'}
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_opts
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Security headers
    app.config['SESSION_COOKIE_SECURE'] = _is_production()
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour session timeout

    # Initialize the database with the app
    db.init_app(app)

    # Enable CSRF protection globally (makes csrf_token() available in all templates)
    from webapp import _csrf
    _csrf.init_app(app)

    from webapp.supabase_auth import init_supabase
    init_supabase(app)

    # Import and register blueprints
    from .views import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from .copilot import copilot_bp
    app.register_blueprint(copilot_bp)
    
    # Add security headers to all responses
    @app.after_request
    def set_security_headers(response):
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Prevent MIME sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Enable browser XSS protection
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Content Security Policy
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net https://cdn.plot.ly; "
            "style-src 'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.sleeper.app; "
        )
        # Force HTTPS in production
        if _is_production():
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    with app.app_context():
        try:
            db.create_all()  # Ensure tables are created

            # Migrate: add missing columns to saved_league if table already existed
            from sqlalchemy import inspect as sa_inspect, text
            insp = sa_inspect(db.engine)
            if insp.has_table('saved_league'):
                existing_cols = {c['name'] for c in insp.get_columns('saved_league')}
                migrations = {
                    'espn_s2':   'TEXT',
                    'espn_swid': 'VARCHAR(50)',
                }
                with db.engine.begin() as conn:
                    for col_name, col_type in migrations.items():
                        if col_name not in existing_cols:
                            conn.execute(text(
                                f'ALTER TABLE saved_league ADD COLUMN {col_name} {col_type}'
                            ))
                            print(f"  migrated: added {col_name} to saved_league")

            print(f"Database initialized at: {app.config['SQLALCHEMY_DATABASE_URI']}")
        except Exception as e:
            print(f"Error creating database tables: {e}")
            raise

    return app
