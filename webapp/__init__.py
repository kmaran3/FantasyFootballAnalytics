from flask import Flask
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv

# Initialize the database globally
db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.String(100), primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    rankings = db.relationship('UserRanking', backref='user', lazy=True)
    
    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password):
        """Check if the provided password matches the hash."""
        return check_password_hash(self.password_hash, password)

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
    
    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)
    
    # Load a stable secret key from environment (preferred) or instance file (local dev fallback).
    app.config['SECRET_KEY'] = _get_secret_key(app)
    
    # Database configuration - Railway/Postgres in production, SQLite fallback for local dev.
    app.config['SQLALCHEMY_DATABASE_URI'] = _get_database_uri(app)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Security headers
    app.config['SESSION_COOKIE_SECURE'] = _is_production()
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour session timeout

    # Initialize the database with the app
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    login_manager.session_protection = 'strong'  # Protects against session hijacking

    # User loader function for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    # Import and register blueprints
    from .views import main as main_blueprint
    app.register_blueprint(main_blueprint)
    
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
        )
        # Force HTTPS in production
        if _is_production():
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    with app.app_context():
        try:
            db.create_all()  # Ensure tables are created
            print(f"Database initialized at: {app.config['SQLALCHEMY_DATABASE_URI']}")
        except Exception as e:
            print(f"Error creating database tables: {e}")
            raise

    return app
