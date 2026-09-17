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
