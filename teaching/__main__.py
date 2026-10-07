"""python -m teaching [--demo] [--no-browser]"""

from __future__ import annotations

import argparse

from . import server


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m teaching", description="Akira Teaching Mode")
    ap.add_argument("--demo", action="store_true", help="create the offline sample course first")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    if args.demo:
        from . import demo
        demo.seed()
    server.run(open_browser=not args.no_browser, port=args.port)


if __name__ == "__main__":
    main()
