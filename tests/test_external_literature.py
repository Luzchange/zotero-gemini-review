import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.services.pubmed_service import PubMedService
from app.services.jstor_service import JSTORService
from app.schemas.schemas import ExternalArticle

client = TestClient(app)

SAMPLE_PUBMED_XML = """<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2024//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_240101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <PMID Version="1">38123456</PMID>
      <Article PubModel="Print-Electronic">
        <Journal>
          <Title>Nature Biotechnology</Title>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
        <ArticleTitle>High-fidelity CRISPR prime editing in human cells.</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">CRISPR base and prime editing enables precise modifications.</AbstractText>
          <AbstractText Label="RESULTS">We demonstrated high efficacy with minimal off-target edits.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Chen</LastName>
            <ForeName>Alice</ForeName>
          </Author>
          <Author ValidYN="Y">
            <LastName>Liu</LastName>
            <ForeName>David</ForeName>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38123456</ArticleId>
        <ArticleId IdType="doi">10.1038/s41587-024-00123-x</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

@pytest.mark.asyncio
async def test_pubmed_xml_parser():
    service = PubMedService()
    articles = service._parse_pubmed_xml(SAMPLE_PUBMED_XML)
    assert len(articles) == 1
    art = articles[0]
    assert art.pmid == "38123456"
    assert art.title == "High-fidelity CRISPR prime editing in human cells."
    assert art.journal == "Nature Biotechnology"
    assert art.publication_year == "2024"
    assert "Alice Chen" in art.authors
    assert "David Liu" in art.authors
    assert "CRISPR base and prime editing" in art.abstract
    assert art.doi == "10.1038/s41587-024-00123-x"
    assert "38123456" in art.url

def test_jstor_proxy_url_builder():
    service_raw = JSTORService(proxy_prefix="")
    raw_url = "https://www.jstor.org/stable/2539123"
    assert service_raw.build_proxied_url(raw_url) == raw_url

    service_ezproxy = JSTORService(proxy_prefix="https://proxy.lib.harvard.edu/login?url=")
    proxied = service_ezproxy.build_proxied_url(raw_url)
    assert proxied == "https://proxy.lib.harvard.edu/login?url=https://www.jstor.org/stable/2539123"

    service_suffix = JSTORService(proxy_prefix="proxy.lib.school.edu")
    proxied_suffix = service_suffix.build_proxied_url(raw_url)
    assert "www-jstor-org.proxy.lib.school.edu" in proxied_suffix

@pytest.mark.asyncio
async def test_pubmed_search_mocked(monkeypatch):
    class MockSearchResponse:
        status_code = 200
        def json(self):
            return {"esearchresult": {"count": "1", "idlist": ["38123456"]}}
        def raise_for_status(self):
            pass

    class MockFetchResponse:
        status_code = 200
        text = SAMPLE_PUBMED_XML

    import httpx
    async def mock_get(self, url, params=None, **kwargs):
        if "esearch.fcgi" in url:
            return MockSearchResponse()
        elif "efetch.fcgi" in url:
            return MockFetchResponse()
        return MockSearchResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    response = client.post(
        "/api/external/pubmed/search",
        json={"query": "CRISPR editing", "retmax": 5}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "pubmed"
    assert len(data["articles"]) == 1
    assert data["articles"][0]["pmid"] == "38123456"

@pytest.mark.asyncio
async def test_jstor_search_mocked(monkeypatch):
    class MockCrossRefResponse:
        status_code = 200
        def json(self):
            return {
                "message": {
                    "total-results": 1,
                    "items": [{
                        "title": ["The Strategy of Conflict: A Reappraisal"],
                        "author": [{"given": "Thomas", "family": "Schelling"}],
                        "container-title": ["Journal of Conflict Resolution"],
                        "published-print": {"date-parts": [[1960]]},
                        "DOI": "10.2307/172605",
                        "abstract": "<jats:p>A seminal analysis of game theory and bargaining.</jats:p>"
                    }]
                }
            }
        def raise_for_status(self):
            pass

    import httpx
    async def mock_get(self, url, **kwargs):
        return MockCrossRefResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    response = client.post(
        "/api/external/jstor/search",
        json={"query": "game theory", "rows": 5, "proxy_prefix": "https://proxy.lib.umich.edu/login?url="}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "jstor"
    assert len(data["articles"]) == 1
    art = data["articles"][0]
    assert art["title"] == "The Strategy of Conflict: A Reappraisal"
    assert "Thomas Schelling" in art["authors"]
    assert art["publication_year"] == "1960"
    assert art["doi"] == "10.2307/172605"
    assert "https://www.jstor.org/stable/172605" in art["url"]
    assert "proxy.lib.umich.edu" in art["proxied_url"]

@pytest.mark.asyncio
async def test_import_external_to_zotero_mocked(monkeypatch):
    from app.services.zotero_service import ZoteroService
    async def mock_create_journal(self, **kwargs):
        return True, "ZOTERO_NEW_ART_1", "Created"

    monkeypatch.setattr(ZoteroService, "create_journal_article_item", mock_create_journal)

    sample_article = {
        "id": "pmid_38123456",
        "source": "pubmed",
        "title": "High-fidelity CRISPR prime editing",
        "authors": ["Alice Chen", "David Liu"],
        "journal": "Nature Biotechnology",
        "publication_year": "2024",
        "abstract": "We demonstrate precision base editing.",
        "doi": "10.1038/s41587-024-00123-x",
        "pmid": "38123456",
        "url": "https://pubmed.ncbi.nlm.nih.gov/38123456/",
        "proxied_url": "https://pubmed.ncbi.nlm.nih.gov/38123456/"
    }

    response = client.post(
        "/api/external/import-to-zotero",
        json={"article": sample_article},
        headers={"x-zotero-key": "fake_z_key", "x-zotero-user-id": "5425893"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["item_key"] == "ZOTERO_NEW_ART_1"

@pytest.mark.asyncio
async def test_review_external_article_mocked(monkeypatch):
    from app.services.gemini_service import GeminiService
    from app.services.zotero_service import ZoteroService

    async def mock_review(self, *args, **kwargs):
        return "## Synthesis\nHigh-impact findings.", "<p>Zotero Review Note</p>"

    async def mock_create_journal(self, **kwargs):
        return True, "ZOTERO_ITEM_99", "Created"

    async def mock_create_note(self, **kwargs):
        return True, "ZOTERO_NOTE_99", "Attached"

    monkeypatch.setattr(GeminiService, "review_work_document", mock_review)
    monkeypatch.setattr(ZoteroService, "create_journal_article_item", mock_create_journal)
    monkeypatch.setattr(ZoteroService, "create_child_note", mock_create_note)

    sample_article = {
        "id": "jstor_10.2307_172605",
        "source": "jstor",
        "title": "The Strategy of Conflict",
        "authors": ["Thomas Schelling"],
        "journal": "Journal of Conflict Resolution",
        "publication_year": "1960",
        "abstract": "Analysis of deterrence and strategic moves.",
        "doi": "10.2307/172605",
        "url": "https://www.jstor.org/stable/172605"
    }

    response = client.post(
        "/api/external/review",
        json={
            "article": sample_article,
            "profile": "technical_critique",
            "import_to_zotero": True
        },
        headers={
            "x-gemini-key": "fake_g_key",
            "x-zotero-key": "fake_z_key",
            "x-zotero-user-id": "5425893"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "High-impact findings" in data["review_markdown"]
    assert data["zotero_saved"] is True
    assert data["zotero_item_key"] == "ZOTERO_ITEM_99"
    assert data["zotero_note_key"] == "ZOTERO_NOTE_99"
