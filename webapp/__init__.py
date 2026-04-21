from flask import Flask
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin

# Initialize the database globally
db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.String(100), primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(100))
    rankings = db.relationship('UserRanking', backref='user', lazy=True)

class UserRanking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    ranking_type = db.Column(db.String(50), nullable=False)  # Type of ranking: PPR, Half PPR, etc.
    ranking_data = db.Column(db.Text, nullable=False)  # Store the ranking data as JSON or plain text
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'your-very-secret-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///yourdatabase.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize the database with the app
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'

    # User loader function for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    # Import and register blueprints
    from .views import main as main_blueprint
    app.register_blueprint(main_blueprint)

    with app.app_context():
        db.create_all()  # Ensure tables are created

    return app
