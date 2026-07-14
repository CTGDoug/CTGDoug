"""Tests for KeeperClient against a fake SecretsManager that models the two
real-SDK quirks these tests exist to catch regressions on:

1. A Record's `raw_json` (what save() actually serializes and sends) is only
   regenerated when a standard/custom field setter runs -- direct `.dict`
   mutation alone does *not* update it. (See keeper_secrets_manager_core's
   Record._update() / SecretsManager.prepare_update_payload().)
2. create_secret() re-fetches the whole shared vault to find a folder's key;
   create_secret_with_options() takes a pre-fetched folder list instead.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from hudu_keeper_sync.keeper_client import KeeperClient
from hudu_keeper_sync.models import PasswordRecord

FOLDER = "folder-1"


class FakeRecord:
    def __init__(self, uid: str, data: dict, folder_uid: str = FOLDER) -> None:
        self.uid = uid
        self.dict = data
        self.title = data.get("title", "")
        self.type = data.get("type", "login")
        self.folder_uid = folder_uid
        self.raw_json = None
        self._resync()

    def _resync(self) -> None:
        self.dict["title"] = self.title
        self.raw_json = json.dumps(self.dict)

    def get_standard_field_value(self, field_type: str, single: bool = False):
        for f in self.dict.get("fields", []):
            if f["type"] == field_type:
                values = f.get("value", [])
                return (values[0] if values else None) if single else values
        raise ValueError(field_type)

    def set_standard_field_value(self, field_type: str, value) -> None:
        for f in self.dict.get("fields", []):
            if f["type"] == field_type:
                f["value"] = [value]
                self._resync()
                return
        raise ValueError(field_type)


class FakeSecretsManager:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self.get_secrets_calls = 0
        self.get_folders_calls = 0
        self.create_calls = 0

    def get_folders(self):
        self.get_folders_calls += 1
        return [SimpleNamespace(folder_uid=FOLDER, folder_key=b"fake-key")]

    def get_secrets(self, uids=None, full_response=False):
        self.get_secrets_calls += 1
        uids = uids or list(self.store.keys())
        return [FakeRecord(uid, dict(self.store[uid])) for uid in uids if uid in self.store]

    def get_secrets_with_options(self, query_options, full_response=False):
        self.get_secrets_calls += 1
        return [FakeRecord(uid, dict(data)) for uid, data in self.store.items()]

    def create_secret_with_options(self, create_options, record_data, folders=None):
        self.create_calls += 1
        assert folders, "create_record should pass a pre-fetched folder list"
        uid = f"uid{len(self.store) + 1}"
        self.store[uid] = record_data.to_dict()
        return uid

    def save(self, record, transaction_type=None, links_to_remove=None):
        # Mirrors prepare_update_payload(): only raw_json is persisted.
        self.store[record.uid] = json.loads(record.raw_json)


def seed(sm: FakeSecretsManager, uid: str, **fields) -> None:
    sm.store[uid] = {
        "title": fields.get("title", ""),
        "type": "login",
        "notes": fields.get("notes", ""),
        "fields": [
            {"type": "login", "value": [fields.get("username", "")]},
            {"type": "password", "value": [fields.get("password", "")]},
            {"type": "url", "value": [fields.get("url", "")]},
        ],
    }


def test_update_record_persists_notes_change():
    sm = FakeSecretsManager()
    seed(sm, "uid1", title="Old Title", username="u", password="p", url="", notes="old notes")
    client = KeeperClient(config_path="unused", _sm=sm)

    client.update_record(
        "uid1",
        PasswordRecord(source="hudu", source_id="x", scope=FOLDER, title="Old Title", username="u", password="p", url="", notes="new notes"),
    )

    assert sm.store["uid1"]["notes"] == "new notes"


def test_update_record_persists_title_and_fields():
    sm = FakeSecretsManager()
    seed(sm, "uid1", title="Old Title", username="u", password="old-pass", url="https://old", notes="")
    client = KeeperClient(config_path="unused", _sm=sm)

    result = client.update_record(
        "uid1",
        PasswordRecord(source="hudu", source_id="x", scope=FOLDER, title="New Title", username="u2", password="new-pass", url="https://new", notes=""),
    )

    assert sm.store["uid1"]["title"] == "New Title"
    assert result.title == "New Title"
    assert result.password == "new-pass"


def test_update_record_makes_a_single_lookup_round_trip():
    sm = FakeSecretsManager()
    seed(sm, "uid1", title="T", username="u", password="p", url="")
    client = KeeperClient(config_path="unused", _sm=sm)

    client.update_record("uid1", PasswordRecord(source="hudu", source_id="x", scope=FOLDER, title="T2", username="u", password="p", url=""))

    assert sm.get_secrets_calls == 1


def test_create_record_reuses_cached_folder_list_across_calls():
    sm = FakeSecretsManager()
    client = KeeperClient(config_path="unused", _sm=sm)

    client.create_record(PasswordRecord(source="hudu", source_id="1", scope=FOLDER, title="A", username="u", password="p", url=""))
    client.create_record(PasswordRecord(source="hudu", source_id="2", scope=FOLDER, title="B", username="u", password="p", url=""))

    assert sm.create_calls == 2
    assert sm.get_folders_calls == 1  # cached after the first create
    assert sm.get_secrets_calls == 0  # never falls back to the expensive full-vault fetch


def test_create_record_returns_values_without_a_read_back_round_trip():
    sm = FakeSecretsManager()
    client = KeeperClient(config_path="unused", _sm=sm)

    result = client.create_record(PasswordRecord(source="hudu", source_id="1", scope=FOLDER, title="A", username="u", password="p", url="", notes="n"))

    assert result.title == "A"
    assert result.password == "p"
    assert result.notes == "n"
    assert sm.get_secrets_calls == 0
