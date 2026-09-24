import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request

from app.config import get_credentials
from app.schemas.schemas import (
    PubMedSearchRequest,
    JSTORSearchRequest,
    LiteratureSearchResponse,
    ImportExternalToZoteroRequest,
    ImportExternalToZoteroResponse,
    ReviewExternalArticleRequest,
    WorkDocumentReviewResponse,
    ExternalArticle,
)
from app.services.pubmed_service import PubMedService
from app.services.jstor_service import JSTORService
from app.services.zotero_service import ZoteroService
from app.services.gemini_service import GeminiService

logger = logging.getLogger("gresearch.external_router")
router = APIRouter(prefix="/api/external", tags=["External Literature"])

@router.post("/pubmed/search", response_model=LiteratureSearchResponse)
async def search_pubmed_endpoint(req: PubMedSearchRequest, request: Request):
    """Search biomedical literature on PubMed via NCBI E-Utilities."""
    ncbi_key = req.api_key or request.headers.get("x-ncbi-key")
    service = PubMedService(api_key=ncbi_key)
    results = await service.search(query=req.query, retmax=req.retmax)
    return results

@router.post("/jstor/search", response_model=LiteratureSearchResponse)
async def search_jstor_endpoint(req: JSTORSearchRequest, request: Request):
    """Search academic articles across JSTOR and format institutional proxy URLs."""
    proxy = req.proxy_prefix or request.headers.get("x-school-proxy")
    service = JSTORService(proxy_prefix=proxy)
    results = await service.search(query=req.query, rows=req.rows)
    return results

@router.post("/import-to-zotero", response_model=ImportExternalToZoteroResponse)
async def import_external_article_to_zotero(payload: ImportExternalToZoteroRequest, request: Request):
    """Import an external literature article (PubMed or JSTOR) directly into the user's Zotero library."""
    creds = get_credentials(request)
    zotero_key = creds.get("zotero_key")
    user_id = creds.get("zotero_user_id")

    if not zotero_key or not user_id:
        raise HTTPException(
            status_code=400,
            detail="Zotero credentials missing. Please configure your Zotero API Key and User ID."
        )

    zotero_service = ZoteroService(
        api_key=zotero_key,
        user_id=user_id,
        library_type=creds.get("zotero_library_type", "user")
    )

    art = payload.article
    tags = [art.source, "literature-import"]
    if art.pmid:
        tags.append(f"pmid:{art.pmid}")
    if art.doi:
        tags.append(f"doi:{art.doi}")

    success, item_key, msg = await zotero_service.create_journal_article_item(
        title=art.title,
        creators=art.authors,
        journal=art.journal,
        publication_year=art.publication_year,
        doi=art.doi,
        url=art.url,
        pmid=art.pmid,
        abstract_note=art.abstract,
        collection_key=payload.collection_key,
        tags=tags,
        collection_name=creds.get("zotero_collection", "GResearch")
    )

    if not success:
        raise HTTPException(status_code=500, detail=msg)

    return ImportExternalToZoteroResponse(
        success=True,
        item_key=item_key,
        message=f"Successfully imported '{art.title[:50]}...' into your Zotero library."
    )

@router.post("/review", response_model=WorkDocumentReviewResponse)
async def review_external_article(payload: ReviewExternalArticleRequest, request: Request):
    """Synthesize and critique an external literature article with Gemini."""
    creds = get_credentials(request)
    if not creds.get("gemini_key") and not creds.get("use_vertex_ai"):
        raise HTTPException(
            status_code=401,
            detail="Gemini API Key or Vertex AI OAuth is required. Please set it in Settings."
        )

    art = payload.article
    use_vertex = creds.get("use_vertex_ai", False)
    base_url = creds.get("gemini_base_url")
    if payload.provider:
        prov = payload.provider.lower().strip()
        if prov == "vertex":
            use_vertex = True
        elif prov == "genaimil":
            use_vertex = False
            base_url = "https://api.genai.mil/v1"
        elif prov in ("aistudio", "gemini"):
            use_vertex = False

    gemini_svc = GeminiService(
        api_key=creds.get("gemini_key") or "",
        default_model=payload.model or creds["gemini_model"],
        base_url=base_url,
        use_vertex_ai=use_vertex,
        project_id=creds.get("gcp_project_id"),
        location=creds.get("gcp_location", "us-central1"),
        credentials_json=creds.get("gcp_credentials_json")
    )

    formatted_text = f"""
TITLE: {art.title}
AUTHORS: {", ".join(art.authors) if art.authors else "Unknown"}
SOURCE / JOURNAL: {art.journal or "Academic Journal"}
YEAR: {art.publication_year or "N/A"}
DOI: {art.doi or "N/A"}
PMID: {art.pmid or "N/A"}
URL: {art.url or "N/A"}

ABSTRACT:
{art.abstract or "No abstract provided in bibliographic index."}
"""

    profile = payload.profile or "technical_critique"
    review_md, zotero_html = await gemini_svc.review_work_document(
        title=art.title,
        document_text=formatted_text,
        profile=profile,
        custom_focus=payload.custom_focus
    )

    zotero_saved = False
    zotero_item_key = None
    zotero_note_key = None
    zotero_msg = ""

    if payload.import_to_zotero and creds.get("zotero_key") and creds.get("zotero_user_id"):
        try:
            zotero_service = ZoteroService(
                api_key=creds["zotero_key"],
                user_id=creds["zotero_user_id"],
                library_type=creds.get("zotero_library_type", "user")
            )

            tags = [art.source, "gemini-reviewed"]
            if art.pmid:
                tags.append(f"pmid:{art.pmid}")
            if art.doi:
                tags.append(f"doi:{art.doi}")

            success_item, item_key, msg_item = await zotero_service.create_journal_article_item(
                title=art.title,
                creators=art.authors,
                journal=art.journal,
                publication_year=art.publication_year,
                doi=art.doi,
                url=art.url,
                pmid=art.pmid,
                abstract_note=art.abstract,
                collection_key=payload.collection_key,
                tags=tags,
                collection_name=creds.get("zotero_collection", "GResearch")
            )

            if success_item and item_key:
                zotero_item_key = item_key
                success_note, note_key, msg_note = await zotero_service.create_child_note(
                    parent_item_key=item_key,
                    note_html=zotero_html,
                    tags=[f"gemini-{profile}", "external-literature"]
                )
                if success_note:
                    zotero_saved = True
                    zotero_note_key = note_key
                    zotero_msg = "Saved article & attached Gemini review note to Zotero."
        except Exception as e:
            logger.warning(f"Error auto-syncing external article to Zotero: {e}")

    return WorkDocumentReviewResponse(
        document_id=art.id,
        title=art.title,
        profile=profile,
        review_markdown=review_md,
        zotero_saved=zotero_saved,
        zotero_item_key=zotero_item_key,
        zotero_note_key=zotero_note_key,
        message=f"Review generated successfully. {zotero_msg}".strip()
    )

