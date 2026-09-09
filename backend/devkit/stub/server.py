"""Running the stub as its own process — ``python -m devkit.stub.server <port>``.

Its own process, and not a thread inside the launcher, for one reason that matters in
practice: the backend runs under uvicorn's reloader, and anything sharing that process
loses its state every time a source file is touched. A script pushed before an edit
should still be there after one.
"""

from __future__ import annotations

import sys

import uvicorn

from devkit.stub.app import create_stub


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].isdigit():
        print("usage: python -m devkit.stub.server <port>", file=sys.stderr)
        return 2
    # Loopback only. The stub authenticates nobody and answers anything.
    uvicorn.run(create_stub(), host="127.0.0.1", port=int(args[0]), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
