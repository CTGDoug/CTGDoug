from __future__ import annotations

import dataclasses

import pytest
from fakes import FakeHuduClient, FakeKeeperClient

from hudu_keeper_sync.config import Config, ScopeMapping
from hudu_keeper_sync.state_store import StateStore
from hudu_keeper_sync.sync_engine import run_sync

COMPANY = "12"
FOLDER = "folder-abc"


@pytest.fixture()
def config() -> Config:
    return Config(
        hudu_base_url="https://example.huducloud.com",
        hudu_api_key="unused",
        keeper_config_path="unused",
        scope_mappings=[ScopeMapping(hudu_company_id=COMPANY, keeper_folder_uid=FOLDER)],
        state_db_path=":memory:",
        conflict_winner="hudu",
    )


@pytest.fixture()
def state(tmp_path) -> StateStore:
    store = StateStore(str(tmp_path / "state.db"))
    yield store
    store.close()


def test_unlinked_records_create_counterparts_on_both_sides(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Only in Hudu", username="u1", password="p1", url="https://a")
    keeper.seed(scope=FOLDER, title="Only in Keeper", username="u2", password="p2", url="https://b")

    stats = run_sync(config, hudu, keeper, state)

    assert stats.created_in_keeper == 1
    assert stats.created_in_hudu == 1
    assert stats.conflicts == 0

    keeper_titles = {r.title for r in keeper.list_records(FOLDER)}
    hudu_titles = {r.title for r in hudu.list_passwords(COMPANY)}
    assert "Only in Hudu" in keeper_titles
    assert "Only in Keeper" in hudu_titles

    # Both pairs are now linked.
    assert len(state.all_links()) == 2


def test_bootstrap_match_by_title_links_without_overwriting_content(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu_rec = hudu.seed(scope=COMPANY, title="  Router Admin  ", username="admin", password="hudu-pass", url="")
    keeper_rec = keeper.seed(scope=FOLDER, title="router admin", username="admin", password="keeper-pass", url="")

    stats = run_sync(config, hudu, keeper, state, bootstrap_match_title=True)

    assert stats.created_in_keeper == 0
    assert stats.created_in_hudu == 0
    assert len(state.all_links()) == 1

    # Neither side was overwritten by the match itself.
    assert hudu.get_password(hudu_rec.source_id).password == "hudu-pass"
    assert keeper.get_record(keeper_rec.source_id).password == "keeper-pass"

    link = state.all_links()[0]
    assert link.hudu_id == hudu_rec.source_id
    assert link.keeper_uid == keeper_rec.source_id


def test_dry_run_makes_no_changes(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="New Password", username="u", password="p", url="")

    stats = run_sync(config, hudu, keeper, state, dry_run=True)

    assert stats.created_in_keeper == 1
    assert keeper.list_records(FOLDER) == []
    assert state.all_links() == []


def test_change_on_hudu_side_propagates_to_keeper(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Shared", username="u", password="old-pass", url="")
    run_sync(config, hudu, keeper, state)  # establishes the link

    [hudu_rec] = hudu.list_passwords(COMPANY)
    hudu._records[hudu_rec.source_id] = dataclasses.replace(hudu_rec, password="new-pass")

    stats = run_sync(config, hudu, keeper, state)

    assert stats.updated_in_keeper == 1
    assert stats.updated_in_hudu == 0
    [keeper_rec] = keeper.list_records(FOLDER)
    assert keeper_rec.password == "new-pass"


def test_change_on_keeper_side_propagates_to_hudu(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    keeper.seed(scope=FOLDER, title="Shared", username="u", password="old-pass", url="")
    run_sync(config, hudu, keeper, state)  # establishes the link

    [keeper_rec] = keeper.list_records(FOLDER)
    keeper._records[keeper_rec.source_id] = dataclasses.replace(keeper_rec, password="new-pass")

    stats = run_sync(config, hudu, keeper, state)

    assert stats.updated_in_hudu == 1
    assert stats.updated_in_keeper == 0
    [hudu_rec] = hudu.list_passwords(COMPANY)
    assert hudu_rec.password == "new-pass"


def test_conflicting_edits_use_configured_winner(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Shared", username="u", password="orig", url="")
    run_sync(config, hudu, keeper, state)

    [hudu_rec] = hudu.list_passwords(COMPANY)
    [keeper_rec] = keeper.list_records(FOLDER)
    hudu._records[hudu_rec.source_id] = dataclasses.replace(hudu_rec, password="from-hudu")
    keeper._records[keeper_rec.source_id] = dataclasses.replace(keeper_rec, password="from-keeper")

    stats = run_sync(config, hudu, keeper, state)  # conflict_winner="hudu"

    assert stats.conflicts == 1
    [keeper_rec_after] = keeper.list_records(FOLDER)
    [hudu_rec_after] = hudu.list_passwords(COMPANY)
    assert hudu_rec_after.password == "from-hudu"
    assert keeper_rec_after.password == "from-hudu"


def test_conflicting_edits_keeper_can_win(config, state):
    config = dataclasses.replace(config, conflict_winner="keeper")
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Shared", username="u", password="orig", url="")
    run_sync(config, hudu, keeper, state)

    [hudu_rec] = hudu.list_passwords(COMPANY)
    [keeper_rec] = keeper.list_records(FOLDER)
    hudu._records[hudu_rec.source_id] = dataclasses.replace(hudu_rec, password="from-hudu")
    keeper._records[keeper_rec.source_id] = dataclasses.replace(keeper_rec, password="from-keeper")

    stats = run_sync(config, hudu, keeper, state)

    assert stats.conflicts == 1
    [hudu_rec_after] = hudu.list_passwords(COMPANY)
    assert hudu_rec_after.password == "from-keeper"


def test_deleted_counterpart_is_reported_not_deleted(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Shared", username="u", password="orig", url="")
    run_sync(config, hudu, keeper, state)

    [keeper_rec] = keeper.list_records(FOLDER)
    del keeper._records[keeper_rec.source_id]

    stats = run_sync(config, hudu, keeper, state)

    assert stats.orphaned_links == 1
    assert stats.errors == []
    # The surviving Hudu record is left alone, not deleted or recreated.
    assert len(hudu.list_passwords(COMPANY)) == 1


def test_link_removed_when_both_sides_deleted(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Shared", username="u", password="orig", url="")
    run_sync(config, hudu, keeper, state)
    assert len(state.all_links()) == 1

    [hudu_rec] = hudu.list_passwords(COMPANY)
    [keeper_rec] = keeper.list_records(FOLDER)
    del hudu._records[hudu_rec.source_id]
    del keeper._records[keeper_rec.source_id]

    run_sync(config, hudu, keeper, state)

    assert state.all_links() == []


def test_unchanged_records_are_noop(config, state):
    hudu = FakeHuduClient()
    keeper = FakeKeeperClient()
    hudu.seed(scope=COMPANY, title="Shared", username="u", password="orig", url="")
    run_sync(config, hudu, keeper, state)

    stats = run_sync(config, hudu, keeper, state)

    assert stats.unchanged == 1
    assert stats.updated_in_hudu == 0
    assert stats.updated_in_keeper == 0
