from __future__ import annotations

from hudu_keeper_sync.hudu_client import HuduClient
from hudu_keeper_sync.models import PasswordRecord


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Records every call and serves canned responses in order, standing in
    for requests.Session so HuduClient can be tested without the network."""

    def __init__(self) -> None:
        self.headers: dict = {}
        self.calls: list[tuple] = []
        self._responses: list[FakeResponse] = []

    def queue(self, response: FakeResponse) -> None:
        self._responses.append(response)

    def request(self, method, url, timeout=None, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


def make_client() -> tuple[HuduClient, FakeSession]:
    session = FakeSession()
    client = HuduClient(base_url="https://example.huducloud.com", api_key="key", session=session)
    return client, session


def test_list_passwords_pages_until_short_page():
    client, session = make_client()
    full_page = [{"id": i, "name": f"pw{i}", "company_id": "1"} for i in range(100)]
    short_page = [{"id": 100, "name": "pw100", "company_id": "1"}]
    session.queue(FakeResponse(200, {"asset_passwords": full_page}))
    session.queue(FakeResponse(200, {"asset_passwords": short_page}))

    records = client.list_passwords(company_id="1")

    assert len(records) == 101
    assert len(session.calls) == 2
    assert session.calls[0][2]["params"] == {"page": 1, "page_size": 100, "company_id": "1"}
    assert session.calls[1][2]["params"] == {"page": 2, "page_size": 100, "company_id": "1"}


def test_list_passwords_stops_after_single_short_page():
    client, session = make_client()
    session.queue(FakeResponse(200, {"asset_passwords": [{"id": 1, "name": "only", "company_id": "1"}]}))

    records = client.list_passwords(company_id="1")

    assert len(records) == 1
    assert len(session.calls) == 1


def test_update_password_uses_response_scope_when_present():
    client, session = make_client()
    session.queue(
        FakeResponse(
            200,
            {"asset_password": {"id": 5, "name": "Updated", "company_id": "42", "username": "u", "password": "p", "url": ""}},
        )
    )

    result = client.update_password("5", PasswordRecord(source="hudu", source_id="5", scope="42", title="Updated"))

    assert result.scope == "42"
    assert len(session.calls) == 1  # no fallback GET needed


def test_update_password_falls_back_to_get_when_response_omits_company_id():
    client, session = make_client()
    # PUT response omits company_id entirely.
    session.queue(
        FakeResponse(200, {"asset_password": {"id": 5, "name": "Updated", "username": "u", "password": "p", "url": ""}})
    )
    # Fallback GET provides it.
    session.queue(
        FakeResponse(200, {"asset_password": {"id": 5, "name": "Updated", "company_id": "42", "username": "u", "password": "p", "url": ""}})
    )

    result = client.update_password("5", PasswordRecord(source="hudu", source_id="5", scope="42", title="Updated"))

    assert result.scope == "42"
    assert len(session.calls) == 2
    assert session.calls[1][0] == "GET"


def test_request_error_raises_hudu_client_error():
    from hudu_keeper_sync.hudu_client import HuduClientError

    client, session = make_client()
    session.queue(FakeResponse(404, {"error": "not found"}))

    try:
        client.get_password("missing")
        raised = False
    except HuduClientError:
        raised = True
    assert raised
