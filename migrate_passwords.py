"""
Migration script to hash existing plain-text passwords.
Run this ONCE if you have existing users with plain-text passwords.
"""
from webapp import create_app, db, User

def migrate_passwords():
    app = create_app()
    with app.app_context():
        users = User.query.all()
        migrated_count = 0
        
        for user in users:
            # Check if password is plain text (no hashing prefix)
            if hasattr(user, 'password') and user.password and not user.password.startswith('pbkdf2:'):
                print(f"Migrating user: {user.id}")
                plain_password = user.password
                user.set_password(plain_password)
                migrated_count += 1
            elif not hasattr(user, 'password_hash') or not user.password_hash:
                print(f"Warning: User {user.id} has no password set")
        
        if migrated_count > 0:
            db.session.commit()
            print(f"\n✓ Successfully migrated {migrated_count} user password(s)")
        else:
            print("\n✓ No passwords to migrate")

if __name__ == '__main__':
    print("Password Migration Script")
    print("=" * 50)
    response = input("This will hash all plain-text passwords. Continue? (yes/no): ")
    if response.lower() == 'yes':
        migrate_passwords()
    else:
        print("Migration cancelled")
