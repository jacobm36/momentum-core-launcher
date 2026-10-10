#!/usr/bin/env python3
"""Bounded loopback startup probe using Momentum's existing Python dependency."""
import argparse
import json
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(port, mode):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    base = f"http://127.0.0.1:{port}/"
    for suffix in ("api/id", ""):
        try:
            with opener.open(base + suffix, timeout=1) as response:
                content = response.read(65536)
            if mode == "responding":
                return True
            if suffix:
                try:
                    if json.loads(content).get("app") == "momentum-core-launcher":
                        return True
                except (ValueError, AttributeError):
                    continue
            elif b"<title>Momentum Core Launcher</title>" in content:
                return True
        except urllib.error.HTTPError:
            if mode == "responding":
                return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("ours", "responding"))
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    return 0 if probe(args.port, args.mode) else 1


if __name__ == "__main__":
    sys.exit(main())
