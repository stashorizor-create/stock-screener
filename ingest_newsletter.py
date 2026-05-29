"""
Ingest PrimeTrading newsletter emails from a Google Takeout .mbox file.

Usage:
    python ingest_newsletter.py                                  # full ingest (default)
    python ingest_newsletter.py --portfolio-only                 # re-run vision only (refresh stop/trim data)
    python ingest_newsletter.py --mbox path/to/file.mbox        # custom path
    python ingest_newsletter.py --dry-run                        # preview, no DB writes
    python ingest_newsletter.py --limit 5                        # process only 5 emails
    python ingest_newsletter.py --skip 18 --limit 1             # process a specific email by index

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
    parser = argparse.ArgumentParser(description="Ingest PrimeTrading newsletter .mbox or .eml")
    parser.add_argument("--mbox",             default=str(DEFAULT_MBOX), help="Path to .mbox file")
    parser.add_argument("--eml",              default=None, help="Path to a single .eml file")
    parser.add_argument("--dry-run",          action="store_true", help="Print output, don't write to DB")
    parser.add_argument("--limit",            type=int, default=None, help="Process at most N emails (mbox only)")
    parser.add_argument("--skip",             type=int, default=0,    help="Skip first N emails (mbox only)")
    parser.add_argument("--portfolio-only",   action="store_true",
                        help="Re-run vision extraction only (refresh stop/trim data, skip text extraction)")
    args = parser.parse_args()

    from newsletters.runner import run, run_eml_bytes

    if args.eml:
        eml_path = Path(args.eml)
        if not eml_path.exists():
            print(f"ERROR: file not found: {eml_path}")
            sys.exit(1)
        ok, msg = run_eml_bytes(eml_path.read_bytes(), dry_run=args.dry_run)
        print(f"\n{'OK' if ok else 'FAILED'} — {msg}")
    else:
        count = run(
            mbox_path=args.mbox,
            dry_run=args.dry_run,
            limit=args.limit,
            skip=args.skip,
            portfolio_only=args.portfolio_only,
        )
        print(f"\nFinished — {count} email(s) processed.")


if __name__ == "__main__":
    main()
