"""Two-way reconciliation between a Hudu company's passwords and a Keeper
shared folder's login records.

Sync unit of work is a ``ScopeMapping`` (one Hudu company <-> one Keeper
folder). For each mapping:

1. Previously-linked pairs (tracked in the state store by Hudu password ID
   <-> Keeper record UID) are compared against the content hash recorded at
   last sync. Whichever side's hash changed gets pushed to the other side.
   If both changed since last sync, ``config.conflict_winner`` decides
   (documented limitation: Keeper records don't expose a wall-clock
   modification time via KSM, so true last-write-wins by timestamp isn't
   possible cross-system -- see README).

2. Records with no link on either side are new:
   - If ``bootstrap_match_title`` is set, an unlinked Hudu record is first
     matched against an unlinked Keeper record with the same (trimmed,
     case-insensitive) title in the same scope; a match creates a link
     without overwriting either side, so pre-existing data in both systems
     doesn't get clobbered by the first run.
   - Anything still unmatched gets created on the other side and linked.

Deletions are never propagated automatically: if one side of a linked pair
disappears, the pair is left as an "orphaned link" and reported, not acted
on, since silently deleting credentials is not something a background job
should do without a human looking at it.
"""

from __future__ import annotations

import dataclasses
import logging

from .config import Config, ScopeMapping
from .hudu_client import HuduClient
from .keeper_client import KeeperClient
from .models import PasswordRecord, SyncStats
from .state_store import StateStore

logger = logging.getLogger(__name__)


def _normalized_title(record: PasswordRecord) -> str:
    return (record.title or "").strip().casefold()


def sync_scope(
    mapping: ScopeMapping,
    hudu: HuduClient,
    keeper: KeeperClient,
    state: StateStore,
    conflict_winner: str,
    dry_run: bool,
    bootstrap_match_title: bool,
    stats: SyncStats,
) -> None:
    hudu_records = {r.source_id: r for r in hudu.list_passwords(company_id=mapping.hudu_company_id)}
    keeper_records = {r.source_id: r for r in keeper.list_records(folder_uid=mapping.keeper_folder_uid)}

    scoped_links = state.links_for_scope(mapping.hudu_company_id, mapping.keeper_folder_uid)

    for link in scoped_links:
        hudu_rec = hudu_records.pop(link.hudu_id, None)
        keeper_rec = keeper_records.pop(link.keeper_uid, None)

        if hudu_rec is None and keeper_rec is None:
            logger.info("Both sides of link %s <-> %s are gone; removing link", link.hudu_id, link.keeper_uid)
            if not dry_run:
                state.delete_by_hudu_id(link.hudu_id)
            continue

        if hudu_rec is None:
            logger.warning("Hudu password %s was deleted but Keeper record %s still exists", link.hudu_id, link.keeper_uid)
            stats.orphaned_links += 1
            continue

        if keeper_rec is None:
            logger.warning("Keeper record %s was deleted but Hudu password %s still exists", link.keeper_uid, link.hudu_id)
            stats.orphaned_links += 1
            continue

        hudu_changed = hudu_rec.content_hash() != link.hudu_hash
        keeper_changed = keeper_rec.content_hash() != link.keeper_hash

        if not hudu_changed and not keeper_changed:
            stats.unchanged += 1
            continue

        if hudu_changed and keeper_changed:
            stats.conflicts += 1
            winner = conflict_winner
            logger.warning(
                "Conflict on %s (hudu=%s, keeper=%s): both sides changed since last sync, %s wins",
                hudu_rec.title,
                link.hudu_id,
                link.keeper_uid,
                winner,
            )
        else:
            winner = "hudu" if hudu_changed else "keeper"

        if winner == "hudu":
            logger.info("Pushing Hudu -> Keeper for %s", hudu_rec.title)
            if not dry_run:
                keeper_rec = keeper.update_record(link.keeper_uid, hudu_rec)
            stats.updated_in_keeper += 1
        else:
            logger.info("Pushing Keeper -> Hudu for %s", keeper_rec.title)
            if not dry_run:
                hudu_rec = hudu.update_password(link.hudu_id, keeper_rec)
            stats.updated_in_hudu += 1

        if not dry_run:
            state.upsert(
                link.hudu_id,
                link.keeper_uid,
                mapping.hudu_company_id,
                mapping.keeper_folder_uid,
                hudu_rec.content_hash(),
                keeper_rec.content_hash(),
            )

    if bootstrap_match_title:
        keeper_by_title = {_normalized_title(r): r for r in keeper_records.values()}
        for hudu_id in list(hudu_records.keys()):
            hudu_rec = hudu_records[hudu_id]
            match = keeper_by_title.get(_normalized_title(hudu_rec))
            if match is None:
                continue
            logger.info("Bootstrap-matched %r by title (hudu=%s, keeper=%s)", hudu_rec.title, hudu_id, match.source_id)
            if hudu_rec.content_hash() != match.content_hash():
                logger.warning(
                    "Bootstrap-matched %r has differing content between Hudu and Keeper; "
                    "linked without overwriting either side, review manually",
                    hudu_rec.title,
                )
            if not dry_run:
                state.upsert(
                    hudu_id,
                    match.source_id,
                    mapping.hudu_company_id,
                    mapping.keeper_folder_uid,
                    hudu_rec.content_hash(),
                    match.content_hash(),
                )
            hudu_records.pop(hudu_id, None)
            keeper_records.pop(match.source_id, None)

    for hudu_id, hudu_rec in hudu_records.items():
        logger.info("Creating Keeper record for new Hudu password %r", hudu_rec.title)
        if not dry_run:
            keeper_scoped = dataclasses.replace(hudu_rec, scope=mapping.keeper_folder_uid)
            created = keeper.create_record(keeper_scoped)
            state.upsert(
                hudu_id,
                created.source_id,
                mapping.hudu_company_id,
                mapping.keeper_folder_uid,
                hudu_rec.content_hash(),
                created.content_hash(),
            )
        stats.created_in_keeper += 1

    for keeper_uid, keeper_rec in keeper_records.items():
        logger.info("Creating Hudu password for new Keeper record %r", keeper_rec.title)
        if not dry_run:
            hudu_scoped = dataclasses.replace(keeper_rec, scope=mapping.hudu_company_id)
            created = hudu.create_password(hudu_scoped)
            state.upsert(
                created.source_id,
                keeper_uid,
                mapping.hudu_company_id,
                mapping.keeper_folder_uid,
                created.content_hash(),
                keeper_rec.content_hash(),
            )
        stats.created_in_hudu += 1


def run_sync(
    config: Config,
    hudu: HuduClient,
    keeper: KeeperClient,
    state: StateStore,
    dry_run: bool = False,
    bootstrap_match_title: bool = False,
) -> SyncStats:
    stats = SyncStats()
    for mapping in config.scope_mappings:
        logger.info("Syncing Hudu company %s <-> Keeper folder %s", mapping.hudu_company_id, mapping.keeper_folder_uid)
        try:
            sync_scope(
                mapping=mapping,
                hudu=hudu,
                keeper=keeper,
                state=state,
                conflict_winner=config.conflict_winner,
                dry_run=dry_run,
                bootstrap_match_title=bootstrap_match_title,
                stats=stats,
            )
        except Exception as exc:  # noqa: BLE001 - one scope failing shouldn't abort the whole run
            logger.exception("Sync failed for scope %s <-> %s", mapping.hudu_company_id, mapping.keeper_folder_uid)
            stats.errors.append(f"{mapping.hudu_company_id} <-> {mapping.keeper_folder_uid}: {exc}")
    return stats
