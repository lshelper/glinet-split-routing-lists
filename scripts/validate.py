#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from build import build_outputs


def main() -> int:
    _, manifest, errors = build_outputs()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    print(json.dumps(manifest["lists"], indent=2, sort_keys=True))
    print(json.dumps(manifest["compact"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
