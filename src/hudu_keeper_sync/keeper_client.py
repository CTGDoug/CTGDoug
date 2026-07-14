"""Thin client for Keeper Secrets Manager (KSM), used as the write-capable
API for the sync tool. KSM applications must be granted edit rights on the
shared folder(s) referenced in the scope map for create/update to work.

Records are stored as the standard "login" record type, using its `login`,
`password`, and `url` fields plus a `notes` field for the free-text notes.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from keeper_secrets_manager_core import SecretsManager
from keeper_secrets_manager_core.core import CreateOptions, QueryOptions
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
    _folders_cache: list | None = None

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
        rc.notes = record.notes

        # create_secret() (the simpler SDK entrypoint) re-fetches and decrypts
        # every record in every folder shared with this application on every
        # call just to find the destination folder's key. create_secret_with_options()
        # takes a pre-fetched folder list instead, so a whole sync run only
        # pays for one (much cheaper) folder-metadata fetch no matter how many
        # records it creates.
        if self._folders_cache is None:
            self._folders_cache = self._sm.get_folders()
        uid = self._sm.create_secret_with_options(CreateOptions(record.scope, None), rc, folders=self._folders_cache)

        return dataclasses.replace(record, source="keeper", source_id=uid)

    def update_record(self, uid: str, record: PasswordRecord) -> PasswordRecord:
        raw = self._sm.get_secrets(uids=[uid])
        if not raw:
            raise KeeperClientError(f"Keeper record {uid} not found")
        raw_record = raw[0]

        # Title and notes are plain attributes/dict keys, not entries in the
        # `fields` list, so they only make it into the payload that save()
        # actually sends if they're set *before* the last set_standard_field_value()
        # call below -- that call is what regenerates the record's encrypted
        # raw_json from its current .dict. Setting them after, as a previous
        # version of this code did for notes, silently drops the change: the
        # save() succeeds, but the new value never reaches Keeper.
        raw_record.title = record.title
        raw_record.dict["notes"] = record.notes
        raw_record.set_standard_field_value("login", record.username)
        raw_record.set_standard_field_value("password", record.password)
        raw_record.set_standard_field_value("url", record.url)
        self._sm.save(raw_record)

        return dataclasses.replace(record, source="keeper", source_id=uid, scope=raw_record.folder_uid)


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
