#!/usr/bin/env python3
"""CLI tool to reset a CloudLabManager user password."""

import argparse
import getpass
import sys

from auth import hash_password
from database import SessionLocal, User


def main():
    parser = argparse.ArgumentParser(description="Reset a CloudLabManager user password")
    parser.add_argument("--username", help="Username to reset (interactive if omitted)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        users = session.query(User).filter_by(is_active=True).all()

        if not users:
            print("No users found in the database.")
            sys.exit(1)

        # Resolve username
        if args.username:
            user = session.query(User).filter_by(username=args.username).first()
            if not user:
                names = [u.username for u in users]
                print(f"User '{args.username}' not found. Available users: {', '.join(names)}")
                sys.exit(1)
        elif len(users) == 1:
            user = users[0]
            print(f"Only one user found: {user.username}")
        else:
            print("Available users:")
            for i, u in enumerate(users, 1):
                print(f"  {i}. {u.username}")
            try:
                choice = int(input("Select user number: "))
                user = users[choice - 1]
            except (ValueError, IndexError):
                print("Invalid selection.")
                sys.exit(1)

        # Prompt for new password
        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm password: ")

        if password != confirm:
            print("Passwords do not match.")
            sys.exit(1)

        if not password or len(password) < 8:
            print("Password must be at least 8 characters.")
            sys.exit(1)

        # Update
        user.password_hash = hash_password(password)
        session.commit()
        print(f"Password for '{user.username}' has been reset.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
