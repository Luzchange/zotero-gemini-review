import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.gemini_service import GeminiService
from app.services.zotero_service import ZoteroService
from app.schemas.schemas import SinglePaperReviewResponse, PaperItem

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "gemini_configured" in data
    assert "zotero_configured" in data

def test_home_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Zotero + Gemini Literature Review Studio" in response.text

def test_zotero_verify_missing_creds():
    response = client.get("/api/zotero/verify")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert "Credentials missing" in data["message"]

def test_review_paper_missing_gemini_key():
    response = client.post(
        "/api/review/paper",
        json={"item_key": "ITEM123"},
        headers={"x-zotero-key": "fake_z_key", "x-zotero-user-id": "12345"}
    )
    # Gemini key is missing, should return 400
    assert response.status_code == 400
    assert "Gemini API Key is missing" in response.json()["detail"]

@pytest.mark.asyncio
async def test_review_paper_flow_mocked(monkeypatch, sample_paper):
    # Mock Zotero get_item
    async def mock_get_item(self, item_key):
        return sample_paper

    monkeypatch.setattr(ZoteroService, "get_item", mock_get_item)

    # Mock Gemini review_single_paper
    async def mock_review_single(self, paper, pdf_bytes=None, custom_focus=None, model_override=None):
        return SinglePaperReviewResponse(
            item_key=paper.key,
            title=paper.title,
            citation="Vaswani et al. (2017)",
            research_question="Can attention replace recurrent networks?",
            theoretical_background="Transformer architecture without recurrence",
            methodology="WMT translation benchmarks",
            key_findings=["SOTA BLEU score", "Trained in 3.5 days"],
            limitations_and_critique=["Quadratic memory complexity with sequence length"],
            future_directions=["Pretrained language models"],
            key_quotes=["Attention is all you need"],
            review_markdown="# Attention Review\nGreat paper.",
            zotero_html_note="<p>Attention Review: Great paper.</p>"
        )

    monkeypatch.setattr(GeminiService, "review_single_paper", mock_review_single)

    response = client.post(
        "/api/review/paper",
        json={"item_key": "ITEM123", "include_pdf": False},
        headers={
            "x-gemini-key": "mock_gemini_key",
            "x-zotero-key": "mock_zotero_key",
            "x-zotero-user-id": "12345"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["item_key"] == "ITEM123"
    assert data["title"] == "Attention Is All You Need"
    assert "Attention Review" in data["review_markdown"]
    assert len(data["key_findings"]) == 2
