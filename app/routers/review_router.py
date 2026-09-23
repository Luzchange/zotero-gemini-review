import logging
from typing import List
from fastapi import APIRouter, Request, HTTPException

from app.config import get_credentials
from app.services.zotero_service import ZoteroService
from app.services.gemini_service import GeminiService
from app.schemas.schemas import (
    PaperItem,
    SinglePaperReviewRequest,
    SinglePaperReviewResponse,
    CollectionSynthesisRequest,
    CollectionSynthesisResponse,
    ResearchGapRequest,
    ResearchGapResponse,
    LiteratureChatRequest,
    LiteratureChatResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["Literature Review"])

@router.get("/models")
async def list_models(request: Request):
    """List available models for the configured Gemini key."""
    service = get_gemini_service(request)
    models = await service.list_available_models()
    return {"models": models}

def get_gemini_service(request: Request) -> GeminiService:
    creds = get_credentials(request)
    if not creds["gemini_key"]:
        raise HTTPException(
            status_code=400,
            detail="Gemini API Key is missing. Set GEMINI_API_KEY in .env or pass X-Gemini-Key header."
        )
    return GeminiService(
        api_key=creds["gemini_key"],
        default_model=creds["gemini_model"],
        base_url=creds.get("gemini_base_url")
    )

def get_zotero_service(request: Request) -> ZoteroService:
    creds = get_credentials(request)
    if not creds["zotero_key"] or not creds["zotero_user_id"]:
        raise HTTPException(
            status_code=400,
            detail="Zotero credentials missing. Set ZOTERO_API_KEY and ZOTERO_USER_ID in .env or pass headers."
        )
    return ZoteroService(
        api_key=creds["zotero_key"],
        user_id=creds["zotero_user_id"],
        library_type=creds["zotero_library_type"]
    )

async def _fetch_target_papers(
    zotero: ZoteroService,
    item_keys: list[str] | None,
    collection_key: str | None
) -> List[PaperItem]:
    """Helper to retrieve papers specified either by a list of keys or a collection key."""
    papers: List[PaperItem] = []
    
    if item_keys and len(item_keys) > 0:
        for key in item_keys:
            paper = await zotero.get_item(key)
            if paper:
                papers.append(paper)
    elif collection_key:
        items, _ = await zotero.get_items(collection_key=collection_key, limit=100)
        papers = items
    else:
        # Default fallback: fetch recent items
        items, _ = await zotero.get_items(limit=25)
        papers = items

    return papers

@router.post("/paper", response_model=SinglePaperReviewResponse)
async def review_single_paper(payload: SinglePaperReviewRequest, request: Request):
    """
    Perform a comprehensive academic review of a single paper.
    If the paper has a PDF attachment in Zotero, it will be downloaded and sent to Gemini.
    """
    zotero = get_zotero_service(request)
    gemini = get_gemini_service(request)

    paper = await zotero.get_item(payload.item_key)
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper with key '{payload.item_key}' not found.")

    pdf_bytes = None
    if payload.include_pdf and paper.pdf_attachment_key:
        try:
            logger.info(f"Downloading PDF attachment for paper {paper.key} (attachment: {paper.pdf_attachment_key})...")
            pdf_bytes = await zotero.download_attachment_pdf(paper.pdf_attachment_key)
        except Exception as e:
            logger.warning(f"Could not download PDF attachment: {e}. Proceeding with abstract and metadata.")

    return await gemini.review_single_paper(
        paper=paper,
        pdf_bytes=pdf_bytes,
        custom_focus=payload.custom_focus,
        model_override=payload.model
    )

@router.post("/synthesize", response_model=CollectionSynthesisResponse)
async def synthesize_collection(payload: CollectionSynthesisRequest, request: Request):
    """
    Synthesize multiple papers into a cohesive literature review matrix,
    identifying commonalities, disagreements, and methodological evolution.
    """
    zotero = get_zotero_service(request)
    gemini = get_gemini_service(request)

    papers = await _fetch_target_papers(zotero, payload.item_keys, payload.collection_key)
    if not papers:
        raise HTTPException(status_code=400, detail="No papers found for the provided keys or collection.")

    return await gemini.synthesize_collection(
        papers=papers,
        research_theme=payload.research_theme,
        model_override=payload.model
    )

@router.post("/gaps", response_model=ResearchGapResponse)
async def analyze_research_gaps(payload: ResearchGapRequest, request: Request):
    """
    Critically analyze selected papers to uncover empirical, methodological,
    and theoretical research gaps, proposing novel high-impact research questions.
    """
    zotero = get_zotero_service(request)
    gemini = get_gemini_service(request)

    papers = await _fetch_target_papers(zotero, payload.item_keys, payload.collection_key)
    if not papers:
        raise HTTPException(status_code=400, detail="No papers found for the provided keys or collection.")

    return await gemini.identify_research_gaps(
        papers=papers,
        target_domain=payload.target_domain,
        model_override=payload.model
    )

@router.post("/chat", response_model=LiteratureChatResponse)
async def chat_with_papers(payload: LiteratureChatRequest, request: Request):
    """
    Ask an evidence-based question across your Zotero library papers.
    """
    zotero = get_zotero_service(request)
    gemini = get_gemini_service(request)

    papers = await _fetch_target_papers(zotero, payload.item_keys, payload.collection_key)
    if not papers:
        raise HTTPException(status_code=400, detail="No papers found to answer this question.")

    return await gemini.chat_with_literature(
        papers=papers,
        query=payload.query,
        chat_history=payload.chat_history,
        model_override=payload.model
    )
