#!/usr/bin/env python3
"""Keep the per-example copies of shared/cw_http.py identical to the canonical file.

Each example is meant to be copied out on its own, so each folder carries its own copy of the small client.

    python scripts/sync_client.py          # copy shared/cw_http.py into every example that has one
    python scripts/sync_client.py --check  # exit 1 if any copy differs (used by CI)
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "shared" / "cw_http.py"
TARGETS = sorted(ROOT.glob("0[1-4]-*/cw_http.py"))


def main() -> int:
    stale = [t for t in TARGETS if t.read_bytes() != CANONICAL.read_bytes()]
    if "--check" in sys.argv:
        for target in stale:
            print(f"out of date: {target.relative_to(ROOT)} (run python scripts/sync_client.py)")
        return 1 if stale else 0
    for target in TARGETS:
        shutil.copyfile(CANONICAL, target)
        print(f"synced {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
