"""
Compute forward-test performance for Alex's portfolio picks.

Usage:
    python forward_test.py              # compute + save to DB
    python forward_test.py --dry-run    # print results, no DB writes
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


def main():
    parser = argparse.ArgumentParser(description="Forward-test Alex's newsletter picks")
    parser.add_argument("--dry-run", action="store_true", help="Print results, don't write to DB")
    args = parser.parse_args()

    from newsletters.forward_tester import run_forward_tests
    count = run_forward_tests(dry_run=args.dry_run)
    print(f"\nDone — {count} picks processed.")


if __name__ == "__main__":
    main()
