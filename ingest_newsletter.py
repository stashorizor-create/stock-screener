"""
Ingest PrimeTrading newsletter emails from a Google Takeout .mbox file.

Usage:
    python ingest_newsletter.py                              # default path
    python ingest_newsletter.py --mbox path/to/file.mbox    # custom path
    python ingest_newsletter.py --dry-run                    # preview, no DB writes
    python ingest_newsletter.py --limit 5                    # process only 5 emails
    python ingest_newsletter.py --mbox file.mbox --dry-run --limit 3

The default mbox path is: data/newsletters/primetrading.mbox
After Google Takeout, unzip and copy the .mbox file to that path.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_MBOX = ROOT / "data" / "newsletters" / "primetrading.mbox"


def main():
    parser = argparse.ArgumentParser(description="Ingest PrimeTrading newsletter .mbox")
    parser.add_argument("--mbox",     default=str(DEFAULT_MBOX), help="Path to .mbox file")
    parser.add_argument("--dry-run",  action="store_true", help="Print output, don't write to DB")
    parser.add_argument("--limit",    type=int, default=None, help="Process at most N emails")
    parser.add_argument("--skip",     type=int, default=0,    help="Skip first N emails (by file order)")
    args = parser.parse_args()

    from newsletters.runner import run
    count = run(mbox_path=args.mbox, dry_run=args.dry_run, limit=args.limit, skip=args.skip)
    print(f"\nFinished — {count} email(s) processed.")


if __name__ == "__main__":
    main()
