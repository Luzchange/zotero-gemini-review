import pytest
from app.services.zotero_service import ZoteroService

@pytest.mark.asyncio
async def test_zotero_service_init():
    service = ZoteroService(api_key="test_key", user_id="12345", library_type="user")
    assert service.library_url == "https://api.zotero.org/users/12345"
    assert service.headers["Zotero-API-Key"] == "test_key"
    assert service.headers["Zotero-API-Version"] == "3"

@pytest.mark.asyncio
async def test_zotero_service_group():
    service = ZoteroService(api_key="test_key", user_id="9999", library_type="group")
    assert service.library_url == "https://api.zotero.org/groups/9999"

@pytest.mark.asyncio
async def test_zotero_missing_creds():
    service = ZoteroService(api_key="", user_id="")
    res = await service.test_connection()
    assert res["connected"] is False
    assert "required" in res["message"].lower()

@pytest.mark.asyncio
async def test_create_child_note_payload(monkeypatch):
    service = ZoteroService(api_key="dummy_key", user_id="12345")

    captured_requests = []

    class MockResponse:
        status_code = 200
        def json(self):
            return {"successful": {"0": {"key": "NOTE_NEW_1"}}}

    async def mock_post(url, headers=None, json=None):
        captured_requests.append({"url": url, "headers": headers, "json": json})
        return MockResponse()

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", lambda self, url, **kwargs: mock_post(url, **kwargs))

    success, key, msg = await service.create_child_note(
        parent_item_key="ITEM123",
        note_html="<p>Test note review</p>",
        tags=["gemini-reviewed"]
    )

    assert success is True
    assert key == "NOTE_NEW_1"
    assert len(captured_requests) == 1
    post_payload = captured_requests[0]["json"]
    assert post_payload[0]["itemType"] == "note"
    assert post_payload[0]["parentItem"] == "ITEM123"
    assert post_payload[0]["note"] == "<p>Test note review</p>"
    assert post_payload[0]["tags"] == [{"tag": "gemini-reviewed"}]

@pytest.mark.asyncio
async def test_get_or_create_collection_existing(monkeypatch):
    service = ZoteroService(api_key="dummy_key", user_id="12345")

    async def mock_get_collections():
        from app.schemas.schemas import CollectionItem
        return [
            CollectionItem(key="GRESEARCH_KEY_1", name="GResearch", num_items=5),
            CollectionItem(key="OTHER_KEY_2", name="Biomedical", num_items=2)
        ]

    monkeypatch.setattr(service, "get_collections", mock_get_collections)
    col_key = await service.get_or_create_collection("GResearch")
    assert col_key == "GRESEARCH_KEY_1"

@pytest.mark.asyncio
async def test_get_or_create_collection_creates_new(monkeypatch):
    service = ZoteroService(api_key="dummy_key", user_id="12345")

    async def mock_get_collections():
        return []

    captured_post = []

    class MockPostResp:
        status_code = 200
        def json(self):
            return {"successful": {"0": {"key": "NEWLY_CREATED_GRESEARCH"}}}

    import httpx
    async def mock_post(url, headers=None, json=None):
        captured_post.append({"url": url, "json": json})
        return MockPostResp()

    monkeypatch.setattr(service, "get_collections", mock_get_collections)
    monkeypatch.setattr(httpx.AsyncClient, "post", lambda self, url, **kwargs: mock_post(url, **kwargs))

    col_key = await service.get_or_create_collection("GResearch")
    assert col_key == "NEWLY_CREATED_GRESEARCH"
    assert len(captured_post) == 1
    assert captured_post[0]["json"][0]["name"] == "GResearch"

