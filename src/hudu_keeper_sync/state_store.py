"""SQLite-backed link table mapping a Hudu asset_password to the Keeper
record it's paired with, plus the content hash observed on each side as of
the last successful sync. This is what lets the engine tell "changed since
last sync" apart from "differs because the other side changed it".

Each link also records which scope (Hudu company_id / Keeper folder_uid
pair) it belongs to. That's needed so a link whose *both* sides get deleted
can still be found and cleaned up by ``sync_scope`` -- once both remote
records are gone there's nothing left to infer the scope from except this
column.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Link:
    hudu_id: str
    keeper_uid: str
    hudu_company_id: str
    keeper_folder_uid: str
    hudu_hash: str
    keeper_hash: str
    last_synced_at: str


_COLUMNS = "hudu_id, keeper_uid, hudu_company_id, keeper_folder_uid, hudu_hash, keeper_hash, last_synced_at"

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    hudu_id TEXT PRIMARY KEY,
    keeper_uid TEXT NOT NULL UNIQUE,
    hudu_company_id TEXT NOT NULL,
    keeper_folder_uid TEXT NOT NULL,
    hudu_hash TEXT NOT NULL,
    keeper_hash TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def all_links(self) -> list[Link]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM links").fetchall()
        return [Link(*row) for row in rows]

    def links_for_scope(self, hudu_company_id: str, keeper_folder_uid: str) -> list[Link]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM links WHERE hudu_company_id = ? AND keeper_folder_uid = ?",
            (hudu_company_id, keeper_folder_uid),
        ).fetchall()
        return [Link(*row) for row in rows]

    def get_by_hudu_id(self, hudu_id: str) -> Link | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM links WHERE hudu_id = ?",
            (hudu_id,),
        ).fetchone()
        return Link(*row) if row else None

    def get_by_keeper_uid(self, keeper_uid: str) -> Link | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM links WHERE keeper_uid = ?",
            (keeper_uid,),
        ).fetchone()
        return Link(*row) if row else None

    def upsert(
        self,
        hudu_id: str,
        keeper_uid: str,
        hudu_company_id: str,
        keeper_folder_uid: str,
        hudu_hash: str,
        keeper_hash: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO links (hudu_id, keeper_uid, hudu_company_id, keeper_folder_uid, hudu_hash, keeper_hash, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hudu_id) DO UPDATE SET
                keeper_uid = excluded.keeper_uid,
                hudu_company_id = excluded.hudu_company_id,
                keeper_folder_uid = excluded.keeper_folder_uid,
                hudu_hash = excluded.hudu_hash,
                keeper_hash = excluded.keeper_hash,
                last_synced_at = excluded.last_synced_at
            """,
            (hudu_id, keeper_uid, hudu_company_id, keeper_folder_uid, hudu_hash, keeper_hash, now),
        )
        self._conn.commit()

    def delete_by_hudu_id(self, hudu_id: str) -> None:
        self._conn.execute("DELETE FROM links WHERE hudu_id = ?", (hudu_id,))
        self._conn.commit()
