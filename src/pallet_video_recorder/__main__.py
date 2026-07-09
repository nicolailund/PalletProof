from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from .app import PalletVideoApp
from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Barcode-triggered pallet video recorder")
    parser.add_argument("--config", default="config.toml", help="Path to TOML configuration")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(Path(args.config))
    app = PalletVideoApp(config)

    def stop_handler(signum: int, _frame: object) -> None:
        logging.getLogger(__name__).info("Received signal %s, shutting down", signum)
        app.stop()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
