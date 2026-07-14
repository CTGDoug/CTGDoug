from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_config
from .hudu_client import HuduClient
from .keeper_client import KeeperClient
from .state_store import StateStore
from .sync_engine import run_sync


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hudu-keeper-sync",
        description="Two-way password sync between Hudu and Keeper Security.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing to Hudu, Keeper, or the state DB.",
    )
    parser.add_argument(
        "--bootstrap-match-title",
        action="store_true",
        help=(
            "On records with no existing link, pair Hudu/Keeper entries that share the same "
            "title within a scope instead of creating a duplicate. Only intended for the first "
            "run against systems that already hold overlapping data; it never overwrites either "
            "side, it only establishes the link."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    hudu = HuduClient(base_url=config.hudu_base_url, api_key=config.hudu_api_key, timeout=config.request_timeout_seconds)
    keeper = KeeperClient(config_path=config.keeper_config_path)

    with StateStore(config.state_db_path) as state:
        stats = run_sync(
            config=config,
            hudu=hudu,
            keeper=keeper,
            state=state,
            dry_run=args.dry_run,
            bootstrap_match_title=args.bootstrap_match_title,
        )

    print(("[dry-run] " if args.dry_run else "") + stats.summary())
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
