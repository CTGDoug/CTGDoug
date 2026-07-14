from __future__ import annotations

import json

import pytest

from hudu_keeper_sync.config import ConfigError, load_config

BASE_ENV = {
    "HUDU_BASE_URL": "https://example.huducloud.com",
    "HUDU_API_KEY": "key",
    "KEEPER_CONFIG_PATH": "unused",
}


def write_scope_map(tmp_path, content) -> str:
    path = tmp_path / "scope_map.json"
    path.write_text(json.dumps(content) if not isinstance(content, str) else content)
    return str(path)


def test_valid_config_loads(tmp_path):
    scope_map_path = write_scope_map(tmp_path, [{"hudu_company_id": "1", "keeper_folder_uid": "f1"}])
    env = {**BASE_ENV, "SCOPE_MAP_PATH": scope_map_path}

    config = load_config(env)

    assert config.scope_mappings[0].hudu_company_id == "1"
    assert config.request_timeout_seconds == 30.0


def test_invalid_request_timeout_raises_config_error(tmp_path):
    scope_map_path = write_scope_map(tmp_path, [])
    env = {**BASE_ENV, "SCOPE_MAP_PATH": scope_map_path, "REQUEST_TIMEOUT_SECONDS": "not-a-number"}

    with pytest.raises(ConfigError):
        load_config(env)


def test_empty_request_timeout_falls_back_to_default(tmp_path):
    scope_map_path = write_scope_map(tmp_path, [])
    env = {**BASE_ENV, "SCOPE_MAP_PATH": scope_map_path, "REQUEST_TIMEOUT_SECONDS": ""}

    config = load_config(env)

    assert config.request_timeout_seconds == 30.0


def test_scope_map_as_object_instead_of_array_raises_config_error(tmp_path):
    scope_map_path = write_scope_map(tmp_path, {"hudu_company_id": "1", "keeper_folder_uid": "f1"})
    env = {**BASE_ENV, "SCOPE_MAP_PATH": scope_map_path}

    with pytest.raises(ConfigError):
        load_config(env)


def test_scope_map_with_non_object_entry_raises_config_error(tmp_path):
    scope_map_path = write_scope_map(tmp_path, ["not-an-object"])
    env = {**BASE_ENV, "SCOPE_MAP_PATH": scope_map_path}

    with pytest.raises(ConfigError):
        load_config(env)


def test_malformed_json_raises_config_error(tmp_path):
    scope_map_path = write_scope_map(tmp_path, "{not valid json")
    env = {**BASE_ENV, "SCOPE_MAP_PATH": scope_map_path}

    with pytest.raises(ConfigError):
        load_config(env)
