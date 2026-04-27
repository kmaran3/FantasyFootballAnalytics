"""One-time migration utility for legacy plain-text passwords.

This script adds a password_hash column if needed, hashes legacy password
values, and clears the old plain-text password field.
"""

from pathlib import Path
import sqlite3

from werkzeug.security import generate_password_hash


DB_PATH = Path(__file__).resolve().parent / "instance" / "yourdatabase.db"


def migrate_passwords():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "user" not in tables:
        print("No user table found. Nothing to migrate.")
        conn.close()
        return

    columns = [row[1] for row in cur.execute("PRAGMA table_info([user])").fetchall()]
    if "password_hash" not in columns:
        cur.execute("ALTER TABLE [user] ADD COLUMN password_hash VARCHAR(256)")
        columns.append("password_hash")
        print("Added password_hash column.")

    if "password" not in columns:
        print("No legacy password column found. Nothing to migrate.")
        conn.commit()
        conn.close()
        return

    rows = cur.execute("SELECT id, password, password_hash FROM [user]").fetchall()
    migrated_count = 0
    skipped_count = 0

    for user_id, plain_password, password_hash in rows:
        if password_hash:
            skipped_count += 1
            continue

        if not plain_password:
            skipped_count += 1
            continue

        new_hash = generate_password_hash(plain_password, method="pbkdf2:sha256")
        cur.execute(
            "UPDATE [user] SET password_hash = ?, password = NULL WHERE id = ?",
            (new_hash, user_id),
        )
        migrated_count += 1

    conn.commit()
    conn.close()

    print(f"Migrated {migrated_count} user(s).")
    print(f"Skipped {skipped_count} user(s).")


if __name__ == "__main__":
    print("Password Migration Script")
    print("=" * 50)
    response = input("This will hash legacy plain-text passwords. Continue? (yes/no): ")
    if response.strip().lower() == "yes":
        migrate_passwords()
    else:
        print("Migration cancelled")
