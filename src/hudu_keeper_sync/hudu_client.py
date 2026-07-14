"""Thin client for the Hudu Passwords (asset_passwords) REST API.

Reference: Hudu's REST API is documented per-instance at
Admin > API > Hudu API Documentation. Endpoint shape confirmed against the
open-source HuduAPI PowerShell module (github.com/lwhitelock/HuduAPI):

  GET    /api/v1/asset_passwords            list, paginated via page/page_size
  GET    /api/v1/asset_passwords/{id}       fetch one
  POST   /api/v1/asset_passwords            create, body: {"asset_password": {...}}
  PUT    /api/v1/asset_passwords/{id}       update, body: {"asset_password": {...}}

Auth: header `x-api-key: <HUDU_API_KEY>`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import requests

from .models import PasswordRecord

PAGE_SIZE = 100


class HuduClientError(RuntimeError):
    pass


@dataclass
class HuduClient:
    base_url: str
    api_key: str
    timeout: float = 30.0
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update({"x-api-key": self.api_key, "Content-Type": "application/json"})

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if resp.status_code >= 400:
            raise HuduClientError(f"Hudu API {method} {path} failed: {resp.status_code} {resp.text[:500]}")
        return resp

    def list_passwords(self, company_id: str | None = None) -> list[PasswordRecord]:
        """List all asset_passwords, optionally scoped to one company. Pages
        until a short page is returned, matching Hudu's pagination contract."""
        records: list[PasswordRecord] = []
        page = 1
        while True:
            params: dict[str, Any] = {"page": page, "page_size": PAGE_SIZE}
            if company_id is not None:
                params["company_id"] = company_id
            resp = self._request("GET", "/api/v1/asset_passwords", params=params)
            batch = resp.json().get("asset_passwords", [])
            records.extend(_to_record(item) for item in batch)
            if len(batch) < PAGE_SIZE:
                break
            page += 1
        return records

    def get_password(self, password_id: str) -> PasswordRecord:
        resp = self._request("GET", f"/api/v1/asset_passwords/{password_id}")
        body = resp.json()
        item = body.get("asset_password", body)
        return _to_record(item)

    def create_password(self, record: PasswordRecord) -> PasswordRecord:
        payload = {
            "asset_password": {
                "name": record.title,
                "company_id": record.scope,
                "username": record.username,
                "password": record.password,
                "url": record.url,
                "description": record.notes,
                "in_portal": False,
            }
        }
        resp = self._request("POST", "/api/v1/asset_passwords", json=payload)
        body = resp.json()
        item = body.get("asset_password", body)
        return _to_record(item)

    def update_password(self, password_id: str, record: PasswordRecord) -> PasswordRecord:
        payload = {
            "asset_password": {
                "name": record.title,
                "username": record.username,
                "password": record.password,
                "url": record.url,
                "description": record.notes,
            }
        }
        resp = self._request("PUT", f"/api/v1/asset_passwords/{password_id}", json=payload)
        body = resp.json()
        item = body.get("asset_password", body)
        updated = _to_record(item)
        if not updated.scope:
            # company_id is immutable and always present on a fetched record;
            # if this particular API response omitted it, don't let the
            # record silently lose its scope -- fetch it instead.
            updated = dataclasses.replace(updated, scope=self.get_password(password_id).scope)
        return updated


def _to_record(item: dict[str, Any]) -> PasswordRecord:
    return PasswordRecord(
        source="hudu",
        source_id=str(item["id"]),
        scope=str(item.get("company_id", "")),
        title=item.get("name") or "",
        username=item.get("username") or "",
        password=item.get("password") or "",
        url=item.get("url") or "",
        notes=item.get("description") or "",
        updated_at=item.get("updated_at") or "",
    )
