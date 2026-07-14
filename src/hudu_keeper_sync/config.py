"""Configuration loading for the Hudu <-> Keeper password sync tool.

All secrets are read from the environment (optionally via a local .env file
loaded by the caller, e.g. with `python-dotenv` in the CLI entrypoint). We
never accept secrets as CLI arguments, since those end up in shell history
and process listings.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    pass


@dataclass
class ScopeMapping:
    """Links a Hudu company_id to the Keeper shared-folder UID that should
    hold its passwords, so new records land in the right place on either
    side."""

    hudu_company_id: str
    keeper_folder_uid: str


@dataclass
class Config:
    hudu_base_url: str
    hudu_api_key: str
    keeper_config_path: str
    scope_mappings: list[ScopeMapping]
    state_db_path: str = "hudu_keeper_sync_state.db"
    conflict_winner: str = "hudu"  # "hudu" or "keeper", used only when both sides changed since last sync
    request_timeout_seconds: float = 30.0

    def mapping_for_hudu_company(self, company_id: str) -> ScopeMapping | None:
        for m in self.scope_mappings:
            if str(m.hudu_company_id) == str(company_id):
                return m
        return None

    def mapping_for_keeper_folder(self, folder_uid: str) -> ScopeMapping | None:
        for m in self.scope_mappings:
            if m.keeper_folder_uid == folder_uid:
                return m
        return None


def _load_scope_mappings(path: str | None) -> list[ScopeMapping]:
    if not path:
        return []
    if not os.path.isfile(path):
        raise ConfigError(f"Scope mapping file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    mappings = []
    for entry in raw:
        try:
            mappings.append(
                ScopeMapping(
                    hudu_company_id=str(entry["hudu_company_id"]),
                    keeper_folder_uid=str(entry["keeper_folder_uid"]),
                )
            )
        except KeyError as exc:
            raise ConfigError(f"Scope mapping entry missing key {exc}: {entry}") from exc
    return mappings


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Required:
      HUDU_BASE_URL            e.g. https://yourcompany.huducloud.com
      HUDU_API_KEY
      KEEPER_CONFIG_PATH       path to a KSM client config (JSON) created via
                                `keeper secrets-manager client add-client ...`
      SCOPE_MAP_PATH           path to a JSON file mapping Hudu companies to
                                Keeper shared folders, see scope_map.example.json

    Optional:
      STATE_DB_PATH            default: hudu_keeper_sync_state.db
      CONFLICT_WINNER          "hudu" (default) or "keeper"
      REQUEST_TIMEOUT_SECONDS  default: 30
    """
    e = env if env is not None else os.environ

    def require(name: str) -> str:
        value = e.get(name)
        if not value:
            raise ConfigError(f"Missing required environment variable: {name}")
        return value

    hudu_base_url = require("HUDU_BASE_URL").rstrip("/")
    hudu_api_key = require("HUDU_API_KEY")
    keeper_config_path = require("KEEPER_CONFIG_PATH")
    scope_map_path = require("SCOPE_MAP_PATH")

    conflict_winner = e.get("CONFLICT_WINNER", "hudu").lower()
    if conflict_winner not in ("hudu", "keeper"):
        raise ConfigError("CONFLICT_WINNER must be 'hudu' or 'keeper'")

    return Config(
        hudu_base_url=hudu_base_url,
        hudu_api_key=hudu_api_key,
        keeper_config_path=keeper_config_path,
        scope_mappings=_load_scope_mappings(scope_map_path),
        state_db_path=e.get("STATE_DB_PATH", "hudu_keeper_sync_state.db"),
        conflict_winner=conflict_winner,
        request_timeout_seconds=float(e.get("REQUEST_TIMEOUT_SECONDS", "30")),
    )
