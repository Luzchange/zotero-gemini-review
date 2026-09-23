import pytest
from app.services.gemini_service import GeminiService
from app.schemas.schemas import PaperItem

def test_paper_summary_text(sample_paper):
    service = GeminiService(api_key="fake_key")
    text = service._build_paper_summary_text(sample_paper)
    
    assert "ITEM123" in text
    assert "Attention Is All You Need" in text
    assert "Vaswani, Ashish" in text
    assert "2017" in text
    assert "10.48550/arXiv.1706.03762" in text

def test_markdown_to_zotero_html():
    service = GeminiService(api_key="fake_key")
    md = """# Summary of Paper
## Key Findings
- Finding 1: Transformers scale effectively.
- Finding 2: Self-attention replaces recurrence.

| Metric | Score |
|---|---|
| BLEU | 28.4 |
"""
    html = service._markdown_to_zotero_html(md, "Attention Is All You Need")
    assert "🤖 Gemini Literature Review: Attention Is All You Need" in html
    assert "<h1>Summary of Paper</h1>" in html
    assert "<h2>Key Findings</h2>" in html
    assert "<li>Finding 1: Transformers scale effectively.</li>" in html
    assert "<table>" in html

@pytest.mark.asyncio
async def test_gemini_service_missing_key():
    service = GeminiService(api_key="")
    with pytest.raises(ValueError, match="Gemini API Key is not set"):
        service._get_client()

def test_gemini_service_genai_mil_auto_detect():
    service = GeminiService(api_key="STARK_test12345")
    assert service._is_openai_compatible() is True
    assert service.base_url == "https://api.genai.mil/v1"

def test_gemini_service_custom_base_url():
    service = GeminiService(api_key="my_custom_key", base_url="https://api.example.com/v1")
    assert service._is_openai_compatible() is True
    assert service.base_url == "https://api.example.com/v1"

@pytest.mark.asyncio
async def test_gemini_service_openai_generation_mocked(monkeypatch):
    import httpx
    service = GeminiService(api_key="STARK_123", base_url="https://api.genai.mil/v1")

    class MockResponse:
        status_code = 200
        is_error = False

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "# Mock GenAI.mil Review\nSuccess!"
                        }
                    }
                ]
            }

    async def mock_post(self, url, headers=None, json=None):
        assert "chat/completions" in url
        assert headers["Authorization"] == "Bearer STARK_123"
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await service._generate_openai_compatible(
        model="gemini-2.5-flash",
        system_instruction="System prompt",
        user_prompt="Hello GenAI",
        temperature=0.2
    )

    assert "# Mock GenAI.mil Review" in result

