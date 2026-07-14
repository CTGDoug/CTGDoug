from __future__ import annotations

from hudu_keeper_sync.state_store import StateStore


def test_upsert_and_lookup(tmp_path):
    with StateStore(str(tmp_path / "state.db")) as store:
        store.upsert("hudu-1", "keeper-1", "company-1", "folder-1", "hash-a", "hash-b")

        by_hudu = store.get_by_hudu_id("hudu-1")
        by_keeper = store.get_by_keeper_uid("keeper-1")

        assert by_hudu is not None
        assert by_hudu.keeper_uid == "keeper-1"
        assert by_hudu.hudu_company_id == "company-1"
        assert by_hudu.keeper_folder_uid == "folder-1"
        assert by_hudu.hudu_hash == "hash-a"
        assert by_hudu.keeper_hash == "hash-b"
        assert by_keeper is not None
        assert by_keeper.hudu_id == "hudu-1"


def test_upsert_updates_existing_link(tmp_path):
    with StateStore(str(tmp_path / "state.db")) as store:
        store.upsert("hudu-1", "keeper-1", "company-1", "folder-1", "hash-a", "hash-b")
        store.upsert("hudu-1", "keeper-1", "company-1", "folder-1", "hash-c", "hash-d")

        link = store.get_by_hudu_id("hudu-1")
        assert link.hudu_hash == "hash-c"
        assert link.keeper_hash == "hash-d"
        assert len(store.all_links()) == 1


def test_delete_by_hudu_id(tmp_path):
    with StateStore(str(tmp_path / "state.db")) as store:
        store.upsert("hudu-1", "keeper-1", "company-1", "folder-1", "hash-a", "hash-b")
        store.delete_by_hudu_id("hudu-1")

        assert store.get_by_hudu_id("hudu-1") is None
        assert store.all_links() == []


def test_missing_link_lookup_returns_none(tmp_path):
    with StateStore(str(tmp_path / "state.db")) as store:
        assert store.get_by_hudu_id("nope") is None
        assert store.get_by_keeper_uid("nope") is None


def test_state_persists_across_reopen(tmp_path):
    db_path = str(tmp_path / "state.db")
    with StateStore(db_path) as store:
        store.upsert("hudu-1", "keeper-1", "company-1", "folder-1", "hash-a", "hash-b")

    with StateStore(db_path) as store:
        link = store.get_by_hudu_id("hudu-1")
        assert link is not None
        assert link.keeper_uid == "keeper-1"


def test_links_for_scope_filters_by_company_and_folder(tmp_path):
    with StateStore(str(tmp_path / "state.db")) as store:
        store.upsert("hudu-1", "keeper-1", "company-1", "folder-1", "hash-a", "hash-b")
        store.upsert("hudu-2", "keeper-2", "company-2", "folder-2", "hash-c", "hash-d")

        scoped = store.links_for_scope("company-1", "folder-1")
        assert [link.hudu_id for link in scoped] == ["hudu-1"]
