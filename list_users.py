"""Safely list users from the application database.

This script intentionally never exports or prints password material.
"""

from webapp import User, create_app


def list_users():
    app = create_app()
    with app.app_context():
        users = User.query.order_by(User.id.asc()).all()
        print(f"Total users: {len(users)}")
        for user in users:
            print(
                f"- username={user.id}, email={user.email}, has_password_hash={bool(user.password_hash)}"
            )


if __name__ == "__main__":
    list_users()
