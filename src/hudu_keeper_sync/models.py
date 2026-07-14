"""Normalized password record shared between Hudu and Keeper adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class PasswordRecord:
    """A password entry normalized to a common shape.

    ``source_id`` is the native ID/UID in whichever system produced the
    record. ``scope`` identifies the container the record lives in on that
    side (Hudu company_id, or Keeper folder_uid) and is used to pick the
    correct counterpart scope when creating a new linked record.
    """

    source: str  # "hudu" or "keeper"
    source_id: str
    scope: str
    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    updated_at: str = ""  # ISO 8601 if the source provides one, else ""

    def content_hash(self) -> str:
        """Hash of the fields that should trigger a sync when changed.

        Deliberately excludes ``updated_at``/``source_id``/``scope`` so the
        hash only reflects user-visible content.
        """
        payload = "\x1f".join(
            [self.title or "", self.username or "", self.password or "", self.url or "", self.notes or ""]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class SyncStats:
    created_in_hudu: int = 0
    created_in_keeper: int = 0
    updated_in_hudu: int = 0
    updated_in_keeper: int = 0
    unchanged: int = 0
    conflicts: int = 0
    orphaned_links: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"created_in_hudu={self.created_in_hudu} "
            f"created_in_keeper={self.created_in_keeper} "
            f"updated_in_hudu={self.updated_in_hudu} "
            f"updated_in_keeper={self.updated_in_keeper} "
            f"unchanged={self.unchanged} "
            f"conflicts={self.conflicts} "
            f"orphaned_links={self.orphaned_links} "
            f"errors={len(self.errors)}"
        )
