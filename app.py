from webapp import create_app, db
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = create_app()

# Add any missing columns to existing tables (lightweight migration).
# Runs on both gunicorn import and local `python app.py`.
with app.app_context():
    from sqlalchemy import inspect, text
    _inspector = inspect(db.engine)
    if 'user' in _inspector.get_table_names():
        _columns = [col['name'] for col in _inspector.get_columns('user')]
        if 'username' not in _columns:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN username VARCHAR(100)'))
            print('Migration: added username column to user table')
    db.create_all()

if __name__ == '__main__':
    
    # Use environment variables for production
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(debug=debug, host='0.0.0.0', port=port, use_reloader=False)