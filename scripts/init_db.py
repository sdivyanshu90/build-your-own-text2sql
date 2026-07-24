#!/usr/bin/env python
"""Create the reference schema (and optionally seed it).

Usage:
    python scripts/init_db.py            # create tables if missing
    python scripts/init_db.py --drop     # drop then create (clean slate)
    python scripts/init_db.py --seed     # create then load seed data
    python scripts/init_db.py --drop --seed

Reads configuration from the environment (see ``.env.example``). For the default
SQLite URL this creates ``./data/text_to_sql.db``. Equivalent to running the
Alembic initial migration; both derive from ``reference_schema.metadata``.
"""

from __future__ import annotations

import argparse

from text_to_sql.configuration import get_settings
from text_to_sql.infrastructure.bootstrap import create_schema, seed_database
from text_to_sql.infrastructure.database import make_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the reference database.")
    parser.add_argument("--drop", action="store_true", help="Drop existing tables first.")
    parser.add_argument("--seed", action="store_true", help="Load deterministic seed data.")
    args = parser.parse_args()

    settings = get_settings()
    database = make_database(settings)
    try:
        create_schema(database.engine, drop_first=args.drop)
        print(f"Schema created (drop_first={args.drop}) on {database.backend}.")
        if args.seed:
            counts = seed_database(database.engine)
            total = sum(counts.values())
            print(f"Seeded {total} rows: {counts}")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
