"""Thin client for Keeper Secrets Manager (KSM), used as the write-capable
API for the sync tool. KSM applications must be granted edit rights on the
shared folder(s) referenced in the scope map for create/update to work.

Records are stored as the standard "login" record type, using its `login`,
`password`, and `url` fields plus a `notes` field for the free-text notes.
"""

from __future__ import annotations

from dataclasses import dataclass

from keeper_secrets_manager_core import SecretsManager
from keeper_secrets_manager_core.core import QueryOptions
from keeper_secrets_manager_core.dto.dtos import Record, RecordCreate, RecordField
from keeper_secrets_manager_core.storage import FileKeyValueStorage

from .models import PasswordRecord

RECORD_TYPE = "login"


class KeeperClientError(RuntimeError):
    pass


@dataclass
class KeeperClient:
    config_path: str
    _sm: SecretsManager | None = None

    def __post_init__(self) -> None:
        if self._sm is None:
            self._sm = SecretsManager(config=FileKeyValueStorage(self.config_path))

    def list_records(self, folder_uid: str) -> list[PasswordRecord]:
        query_options = QueryOptions(records_filter=None, folders_filter=[folder_uid], request_links=None)
        raw_records = self._sm.get_secrets_with_options(query_options)
        return [
            _to_password_record(r, folder_uid)
            for r in raw_records
            if r.type == RECORD_TYPE and r.folder_uid == folder_uid
        ]

    def get_record(self, uid: str) -> PasswordRecord | None:
        raw = self._sm.get_secrets(uids=[uid])
        if not raw:
            return None
        return _to_password_record(raw[0], raw[0].folder_uid)

    def create_record(self, record: PasswordRecord) -> PasswordRecord:
        rc = RecordCreate(RECORD_TYPE, record.title)
        rc.fields = [
            RecordField(field_type="login", value=record.username),
            RecordField(field_type="password", value=record.password),
            RecordField(field_type="url", value=record.url),
        ]
        if record.notes:
            rc.notes = record.notes
        uid = self._sm.create_secret(record.scope, rc)
        created = self.get_record(uid)
        if created is None:
            raise KeeperClientError(f"Created Keeper record {uid} but could not read it back")
        return created

    def update_record(self, uid: str, record: PasswordRecord) -> PasswordRecord:
        raw = self._sm.get_secrets(uids=[uid])
        if not raw:
            raise KeeperClientError(f"Keeper record {uid} not found")
        raw_record = raw[0]
        raw_record.title = record.title
        raw_record.set_standard_field_value("login", record.username)
        raw_record.set_standard_field_value("password", record.password)
        raw_record.set_standard_field_value("url", record.url)
        raw_record.dict["notes"] = record.notes
        self._sm.save(raw_record)
        updated = self.get_record(uid)
        if updated is None:
            raise KeeperClientError(f"Updated Keeper record {uid} but could not read it back")
        return updated


def _to_password_record(r: Record, folder_uid: str) -> PasswordRecord:
    def field(name: str) -> str:
        try:
            value = r.get_standard_field_value(name, single=True)
        except ValueError:
            return ""
        return value or ""

    return PasswordRecord(
        source="keeper",
        source_id=r.uid,
        scope=folder_uid,
        title=r.title or "",
        username=field("login"),
        password=field("password"),
        url=field("url"),
        notes=r.dict.get("notes") or "",
        updated_at="",
    )
