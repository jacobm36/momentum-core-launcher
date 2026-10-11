#!/usr/bin/env python3
"""Import user game shortcuts; preserve existing entries unless --update is explicit."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

import game_import

HERE = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="Explicitly refresh matching entries' command and working directory")
    args = parser.parse_args(argv)
    output = HERE / "games.json"
    try:
        with (HERE / "games.json.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            games = json.loads(output.read_text()) if output.exists() else []
            scan = game_import.discover([] if args.update else games)
            updated = False
            if args.update:
                by_id = {g["id"]: g for g in games}
                for candidate in scan["candidates"]:
                    entry = candidate["entry"]
                    existing = by_id.get(entry["id"])
                    if existing is not None and not candidate["reason"]:
                        for key in ("exec", "cwd"):
                            value = entry.get(key)
                            if existing.get(key) != value:
                                if value is None:
                                    existing.pop(key, None)
                                else:
                                    existing[key] = value
                                print("updated", entry["id"], key)
                                updated = True
            games, result = game_import.add(games, scan["candidates"], HERE)
            for entry in result["added"]:
                print("added", entry["id"])
            for entry in [*scan["skipped"], *result["skipped"], *result["warnings"]]:
                print("skipped", entry["name"], "-", entry["reason"])
            if result["added"] or updated:
                fd, name = tempfile.mkstemp(dir=HERE, prefix="games.", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w") as stream:
                        stream.write(json.dumps(games, indent=2, ensure_ascii=False) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(name, output)
                finally:
                    Path(name).unlink(missing_ok=True)
            print(f"{len(result['added'])} added; {len(scan['skipped']) + len(result['skipped'])} skipped.")
        return 0
    except (game_import.ImportError, OSError, ValueError) as exc:
        print(f"Cannot import game shortcuts: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
