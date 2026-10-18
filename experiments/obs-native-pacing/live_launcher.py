"""Opt-in Lift Trace launcher with an independent native OBS output observer.

Uses the existing settings UI, HTTP API, controller polling and input logic.
Does not install a plugin, launch OBS, connect to Core, or enable automation.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server import Bridge, LocalServer  # noqa: E402
from live_bridge import NativePipeline, validate_channel  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True, help="Path to the Node executable")
    parser.add_argument("--channel", required=True, help="Channel name also entered in the experimental OBS source")
    parser.add_argument("--port", type=int, default=8766, help="Loopback UI port (default 8766)")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "artifacts" / "native-live-data",
                        help="Settings directory; isolated from normal Lift Trace by default")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This experiment currently requires Windows.")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")
    try:
        validate_channel(args.channel)
    except ValueError as exc:
        parser.error(str(exc))
    bridge = Bridge(args.data_dir.resolve())
    pipeline = NativePipeline(bridge, args.node, args.channel)
    server = None
    try:
        server = LocalServer(("127.0.0.1", args.port), ROOT / "web", bridge)
        pipeline.start()
        bridge.start()
        print(f"Lift Trace experimental UI: http://127.0.0.1:{args.port}/", flush=True)
        print(f"Native OBS channel: {args.channel}", flush=True)
        print("Select a controller in the existing UI. OBS automation remains explicitly opt-in.", flush=True)
        print("Ctrl+C stops only this launcher and its owned Node child.", flush=True)
        # handle_request keeps pipeline failure reporting outside all input and
        # renderer threads. An unavailable renderer does not close the UI.
        server.timeout = 0.2
        reported_failure = None
        while True:
            server.handle_request()
            if pipeline.failure and pipeline.failure != reported_failure:
                reported_failure = pipeline.failure
                print("Native renderer transport stopped; input/UI remain available: "
                      + pipeline.failure, file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.close()
        bridge.close()
        if server is not None:
            server.server_close()


if __name__ == "__main__":
    main()
