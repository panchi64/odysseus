"""Child-process model downloader.

Run as ``python -m services.serving.download_worker`` by the ``DownloadManager`` so a
blocking HuggingFace fetch happens in a process the parent can kill cleanly. It writes
two control lines to stdout — ``TOTAL <bytes>`` (when the size is known) and
``ARTIFACT <path>`` (on success) — and exits non-zero with the reason on stderr if the
fetch fails. No state, no secrets (model weights are public).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import hf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="download_worker")
    parser.add_argument("--mode", required=True, choices=["file", "snapshot"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--quant", default=None)
    args = parser.parse_args(argv)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if args.mode == "file":
            filename = hf.gguf_filename(args.repo, args.quant)
            size = hf.file_size(args.repo, filename)
            if size is not None:
                print(f"TOTAL {size}", flush=True)
            artifact = hf.fetch_file(args.repo, filename, dest)
        else:
            size = hf.snapshot_size(args.repo)
            if size is not None:
                print(f"TOTAL {size}", flush=True)
            artifact = hf.fetch_snapshot(args.repo, dest)
    except Exception as exc:  # noqa: BLE001 — report any fetch failure as a non-zero exit
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(f"ARTIFACT {artifact}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
