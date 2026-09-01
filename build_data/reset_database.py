#!/usr/bin/env python3
"""
Script to reset/purge the SQLite database.
Simply deletes the database file.
"""

import os
import sys

# Database file
DB_FILE = "data/apigeo.db"


def reset_database():
    """Delete the database file"""
    print("=" * 60)
    print("RESETTING DATABASE")
    print("=" * 60)
    print("")

    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
            print(f"✓ Database file deleted: {DB_FILE}")

            # Also remove journal files if they exist
            journal_files = [f"{DB_FILE}-journal", f"{DB_FILE}-shm", f"{DB_FILE}-wal"]
            for journal_file in journal_files:
                if os.path.exists(journal_file):
                    os.remove(journal_file)
                    print(f"✓ Cleaned up: {journal_file}")

            print("")
            print("=" * 60)
            print("✅ Database reset successfully!")
            print("=" * 60)
            print("")
            print("You can now run:")
            print("  python 7_load_into_spatialite.py")
            print("")

        except Exception as e:
            print(f"❌ Error deleting database: {e}")
            sys.exit(1)
    else:
        print(f"⚠️  Database file not found: {DB_FILE}")
        print("Database is already clean.")
        print("")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reset SQLite database")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.force:
        # Ask for confirmation
        print("")
        print("⚠️  WARNING: This will delete the database file!")
        print(f"   File: {DB_FILE}")
        print("")
        response = input("Are you sure you want to continue? (yes/no): ")

        if response.lower() not in ["yes", "y", "oui"]:
            print("Cancelled.")
            sys.exit(0)

    reset_database()
