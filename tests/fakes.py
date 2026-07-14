"""In-memory stand-ins for HuduClient/KeeperClient used by the sync engine
tests, so the engine's logic can be exercised without network access or the
real KSM SDK."""

from __future__ import annotations

import itertools
from dataclasses import replace

from hudu_keeper_sync.models import PasswordRecord


class FakeHuduClient:
    def __init__(self) -> None:
        self._records: dict[str, PasswordRecord] = {}
        self._ids = itertools.count(1)

    def seed(self, **kwargs) -> PasswordRecord:
        record_id = str(next(self._ids))
        record = PasswordRecord(source="hudu", source_id=record_id, **kwargs)
        self._records[record_id] = record
        return record

    def list_passwords(self, company_id: str | None = None) -> list[PasswordRecord]:
        return [r for r in self._records.values() if company_id is None or r.scope == company_id]

    def get_password(self, password_id: str) -> PasswordRecord:
        return self._records[password_id]

    def create_password(self, record: PasswordRecord) -> PasswordRecord:
        record_id = str(next(self._ids))
        created = replace(record, source="hudu", source_id=record_id)
        self._records[record_id] = created
        return created

    def update_password(self, password_id: str, record: PasswordRecord) -> PasswordRecord:
        updated = replace(record, source="hudu", source_id=password_id, scope=self._records[password_id].scope)
        self._records[password_id] = updated
        return updated


class FakeKeeperClient:
    def __init__(self) -> None:
        self._records: dict[str, PasswordRecord] = {}
        self._ids = itertools.count(1)

    def seed(self, **kwargs) -> PasswordRecord:
        record_id = f"uid{next(self._ids)}"
        record = PasswordRecord(source="keeper", source_id=record_id, **kwargs)
        self._records[record_id] = record
        return record

    def list_records(self, folder_uid: str) -> list[PasswordRecord]:
        return [r for r in self._records.values() if r.scope == folder_uid]

    def get_record(self, uid: str) -> PasswordRecord | None:
        return self._records.get(uid)

    def create_record(self, record: PasswordRecord) -> PasswordRecord:
        record_id = f"uid{next(self._ids)}"
        created = replace(record, source="keeper", source_id=record_id)
        self._records[record_id] = created
        return created

    def update_record(self, uid: str, record: PasswordRecord) -> PasswordRecord:
        updated = replace(record, source="keeper", source_id=uid, scope=self._records[uid].scope)
        self._records[uid] = updated
        return updated
