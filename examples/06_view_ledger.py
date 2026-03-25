"""
Example 6: View Action Ledger
Review past sessions — what BRU did, what worked, what failed, what got corrected.

Usage:
    python examples/06_view_ledger.py                  # latest 5 sessions
    python examples/06_view_ledger.py --today           # today's sessions
    python examples/06_view_ledger.py --failures        # only sessions with failures
    python examples/06_view_ledger.py --date 2026-03-25 # specific day
    python examples/06_view_ledger.py --days            # list all days with data
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from bru_agent.core.ledger import ActionLedger

LEDGER_DIR = "./data/ledger"


def main():
    args = sys.argv[1:]

    if '--days' in args:
        days = ActionLedger.list_days(LEDGER_DIR)
        if not days:
            print("No ledger data found.")
        else:
            print("Days with ledger data:")
            for d in days:
                print(f"  {d}")
        return

    if '--today' in args:
        today = datetime.now().strftime("%Y-%m-%d")
        print(ActionLedger.read_day(today, LEDGER_DIR))
        return

    if '--failures' in args:
        print(ActionLedger.read_failures(LEDGER_DIR))
        return

    if '--date' in args:
        idx = args.index('--date')
        if idx + 1 < len(args):
            print(ActionLedger.read_day(args[idx + 1], LEDGER_DIR))
        else:
            print("Usage: --date 2026-03-25")
        return

    # Default: latest 5 sessions
    print(ActionLedger.read_latest(LEDGER_DIR))


if __name__ == "__main__":
    main()
