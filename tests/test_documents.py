import io
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app.main import app
from app.routers.documents_router import UPLOADED_DOCUMENTS

client = TestClient(app)

def create_sample_pdf_bytes() -> bytes:
    """Generate a valid minimal in-memory PDF for testing."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

@pytest.fixture(autouse=True)
def clean_documents():
    """Clear uploaded documents between tests."""
    UPLOADED_DOCUMENTS.clear()
    yield
    UPLOADED_DOCUMENTS.clear()

def test_upload_non_pdf_fails():
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("notes.txt", b"plain text", "text/plain")}
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]

def test_upload_valid_pdf_succeeds():
    pdf_bytes = create_sample_pdf_bytes()
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("annual_defense_strategy.pdf", pdf_bytes, "application/pdf")}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"].startswith("doc_")
    assert data["filename"] == "annual_defense_strategy.pdf"
    assert data["page_count"] == 1
    assert data["file_size_bytes"] > 0

    # Test list endpoint
    list_resp = client.get("/api/documents/list")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["id"] == data["document_id"]

def test_delete_document():
    pdf_bytes = create_sample_pdf_bytes()
    up = client.post(
        "/api/documents/upload",
        files={"file": ("memo.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = up["document_id"]

    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Deleting again should 404
    del_resp2 = client.delete(f"/api/documents/{doc_id}")
    assert del_resp2.status_code == 404

def test_review_document_without_key():
    pdf_bytes = create_sample_pdf_bytes()
    up = client.post(
        "/api/documents/upload",
        files={"file": ("memo.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = up["document_id"]

    resp = client.post(
        "/api/documents/review",
        json={"document_id": doc_id, "profile": "executive_bluf"}
    )
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_review_document_with_mocked_gemini_and_zotero(monkeypatch):
    from app.services.gemini_service import GeminiService
    from app.services.zotero_service import ZoteroService

    # Mock Gemini review
    async def mock_review(self, title, text, pdf_bytes, profile, custom_focus, model_override=None):
        return (f"# BLUF Brief: {title}\n\nTop line takeaways.", f"<div><h1>BLUF Brief: {title}</h1></div>")

    monkeypatch.setattr(GeminiService, "review_work_document", mock_review)

    # Mock Zotero creation
    async def mock_create_item(self, title, abstract_note, collection_key=None, creators=None, tags=None, **kwargs):
        return True, "ZOTERO_ITEM_123", "Item created"

    async def mock_create_note(self, parent_item_key, note_html, tags=None):
        return True, "ZOTERO_NOTE_456", "Note created"

    monkeypatch.setattr(ZoteroService, "create_document_item", mock_create_item)
    monkeypatch.setattr(ZoteroService, "create_child_note", mock_create_note)

    # Upload doc
    pdf_bytes = create_sample_pdf_bytes()
    up = client.post(
        "/api/documents/upload",
        files={"file": ("special_ops_report.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = up["document_id"]

    headers = {
        "X-Gemini-Key": "fake_gemini_key",
        "X-Zotero-Key": "fake_zotero_key",
        "X-Zotero-User-Id": "123456"
    }

    resp = client.post(
        "/api/documents/review",
        headers=headers,
        json={
            "document_id": doc_id,
            "profile": "executive_bluf",
            "import_to_zotero": True
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "BLUF Brief" in data["review_markdown"]
    assert data["zotero_saved"] is True
    assert data["zotero_item_key"] == "ZOTERO_ITEM_123"
    assert data["zotero_note_key"] == "ZOTERO_NOTE_456"

@pytest.mark.asyncio
async def test_work_document_chat(monkeypatch):
    from app.services.gemini_service import GeminiService

    async def mock_chat(self, documents, query, chat_history=None, model_override=None):
        return f"Based on {documents[0]['title']}, the answer is affirmative."

    monkeypatch.setattr(GeminiService, "chat_with_work_documents", mock_chat)

    pdf_bytes = create_sample_pdf_bytes()
    up = client.post(
        "/api/documents/upload",
        files={"file": ("cyber_policy.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = up["document_id"]

    resp = client.post(
        "/api/documents/chat",
        headers={"X-Gemini-Key": "fake_key"},
        json={
            "document_ids": [doc_id],
            "query": "Is multifactor authentication required?"
        }
    )
    assert resp.status_code == 200
    assert "Cyber Policy" in resp.json()["answer"]

@pytest.mark.asyncio
async def test_save_to_zotero_explicit(monkeypatch):
    from app.services.zotero_service import ZoteroService

    async def mock_create_item(self, title, abstract_note, collection_key=None, creators=None, tags=None, **kwargs):
        return True, "ITEM_KEY_EXPLICIT", "Success"

    async def mock_create_note(self, parent_item_key, note_html, tags=None):
        return True, "NOTE_KEY_EXPLICIT", "Success"

    monkeypatch.setattr(ZoteroService, "create_document_item", mock_create_item)
    monkeypatch.setattr(ZoteroService, "create_child_note", mock_create_note)

    pdf_bytes = create_sample_pdf_bytes()
    up = client.post(
        "/api/documents/upload",
        files={"file": ("briefing.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = up["document_id"]

    resp = client.post(
        "/api/documents/save-to-zotero",
        headers={"X-Zotero-Key": "fake_z_key", "X-Zotero-User-Id": "12345"},
        json={
            "document_id": doc_id,
            "review_markdown": "# Title\n\nSome review contents."
        }
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["item_key"] == "ITEM_KEY_EXPLICIT"

