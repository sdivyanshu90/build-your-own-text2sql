#!/usr/bin/env python
"""Load deterministic seed data into an existing schema.

Usage:
    python scripts/seed.py           # seed (assumes tables already exist)
    python scripts/seed.py --reset   # drop, recreate, then seed

All data is synthetic and deterministic (fixed RNG seed + fixed base date), so
tests and the golden evaluation suite have stable expected results.
"""

from __future__ import annotations

import argparse

from text_to_sql.configuration import get_settings
from text_to_sql.infrastructure.bootstrap import create_schema, seed_database
from text_to_sql.infrastructure.database import make_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the reference database.")
    parser.add_argument("--reset", action="store_true", help="Drop & recreate before seeding.")
    args = parser.parse_args()

    settings = get_settings()
    database = make_database(settings)
    try:
        if args.reset:
            create_schema(database.engine, drop_first=True)
        counts = seed_database(database.engine)
        print(f"Seeded rows: {counts}")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
