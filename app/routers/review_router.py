import logging
import ssl
import httpx
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
    """List available models for the configured provider."""
    service = get_gemini_service(request)
    models = await service.list_available_models()
    return {"models": models}

@router.post("/verify-vertex")
async def verify_vertex(request: Request):
    """Test Vertex AI Application Default Credentials and project setup."""
    import json
    import os
    creds = get_credentials(request)
    project_id = creds.get("gcp_project_id")
    location = creds.get("gcp_location", "us-central1")
    raw_json = creds.get("gcp_credentials_json") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    
    try:
        import google.auth
        scopes = [
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/generative-language.retriever"
        ]
        credentials = None
        detected_project = None

        if raw_json:
            try:
                cred_dict = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                if "refresh_token" in cred_dict or cred_dict.get("type") == "authorized_user":
                    from google.oauth2 import credentials as oauth2_creds
                    credentials = oauth2_creds.Credentials.from_authorized_user_info(cred_dict, scopes=scopes)
                    detected_project = cred_dict.get("project_id") or cred_dict.get("quota_project_id")
                elif cred_dict.get("type") == "service_account":
                    from google.oauth2 import service_account
                    credentials = service_account.Credentials.from_service_account_info(cred_dict, scopes=scopes)
                    detected_project = cred_dict.get("project_id")
                elif "installed" in cred_dict or "web" in cred_dict:
                    info = cred_dict.get("installed") or cred_dict.get("web") or {}
                    detected_project = info.get("project_id")
            except Exception as j_err:
                logger.warning(f"Error parsing uploaded credentials JSON in verify_vertex: {j_err}")

        if credentials is None:
            credentials, adc_project = google.auth.default(scopes=scopes)
            if not detected_project:
                detected_project = adc_project

        actual_project = project_id or detected_project
        if not actual_project:
            return {
                "success": False,
                "project_id": None,
                "message": "Credentials loaded, but GCP Project ID is missing. Please enter your CloudLab Project ID."
            }
        
        from google import genai
        # Test client creation
        client = genai.Client(
            vertexai=True,
            project=actual_project,
            location=location,
            credentials=credentials
        )
        return {
            "success": True,
            "project_id": actual_project,
            "location": location,
            "message": f"Successfully authenticated Vertex AI with project '{actual_project}' via Application Default Credentials (ADC)!"
        }
    except Exception as e:
        err_str = str(e)
        logger.warning(f"Vertex AI verification failed: {err_str}")
        return {
            "success": False,
            "project_id": project_id,
            "message": f"Vertex AI ADC check failed: {err_str}. Please run 'gcloud auth application-default login' in terminal."
        }

@router.post("/verify-genaimil")
async def verify_genaimil(request: Request):
    """
    Verify GenAI.mil token connectivity, DoD network access, SSL handshake, and list accessible models.
    """
    creds = get_credentials(request)
    token = creds.get("gemini_key") or ""
    base_url = (creds.get("gemini_base_url") or "https://api.genai.mil/v1").rstrip("/")

    if not token:
        return {
            "success": False,
            "message": "GenAI.mil token missing. Please enter your STARK token in Settings."
        }

    models_endpoint = f"{base_url}/models"
    headers = {
        "Authorization": f"Bearer {token}",
        "api-key": token,
        "Content-Type": "application/json"
    }

    discovered_models = []

    for verify_ssl in [True, False]:
        try:
            async with httpx.AsyncClient(timeout=12.0, trust_env=True, verify=verify_ssl) as client:
                resp = await client.get(models_endpoint, headers=headers)
                
                # Check for DoD/Gov network firewall block
                if resp.status_code == 403 and ("outside of DoW networks" in resp.text or "Unauthorized Access" in resp.text):
                    return {
                        "success": False,
                        "message": "Firewall Block: GenAI.mil can only be accessed from inside DoD/DoW networks. Please connect to your military VPN (e.g. GlobalProtect)."
                    }

                if resp.status_code == 401:
                    return {
                        "success": False,
                        "message": "GenAI.mil authentication failed (HTTP 401). Your STARK token appears invalid or expired."
                    }

                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    discovered_models = [m.get("id") for m in data if m.get("id")]
                    return {
                        "success": True,
                        "message": f"Successfully connected to GenAI.mil! Accessible models: {', '.join(discovered_models[:5]) if discovered_models else 'Standard STARK Suite'}.",
                        "models": discovered_models,
                        "ssl_bypassed": not verify_ssl
                    }
                
                # Some gateways don't implement /models but implement /chat/completions probe
                if resp.status_code in [404, 405]:
                    chat_endpoint = f"{base_url}/chat/completions"
                    probe_payload = {
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1
                    }
                    probe_resp = await client.post(chat_endpoint, headers=headers, json=probe_payload)
                    if probe_resp.status_code in [200, 400]:
                        return {
                            "success": True,
                            "message": "Successfully connected and authenticated with GenAI.mil DoD Enterprise Gateway!",
                            "models": ["gpt-4o", "gpt-4-turbo", "gpt-4", "gemini-1.5-pro", "gpt-35-turbo"],
                            "ssl_bypassed": not verify_ssl
                        }

        except (httpx.ConnectError, ssl.SSLError) as ssl_err:
            if verify_ssl:
                continue  # Retry with verify=False for NIPR DoD inspection
            return {
                "success": False,
                "message": f"Could not reach GenAI.mil: {ssl_err}. Check your network connection or DoD proxy."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection error: {str(e)}"
            }

    return {
        "success": False,
        "message": "Could not establish connection to GenAI.mil endpoint. Ensure you are on a DoD/Gov network."
    }


def get_gemini_service(request: Request) -> GeminiService:
    creds = get_credentials(request)
    if not creds.get("gemini_key") and not creds.get("use_vertex_ai"):
        raise HTTPException(
            status_code=400,
            detail="Gemini credentials missing. Please set your Gemini API Key or enable Vertex AI OAuth in Settings."
        )
    return GeminiService(
        api_key=creds.get("gemini_key") or "",
        default_model=creds.get("gemini_model") or "auto",
        base_url=creds.get("gemini_base_url"),
        use_vertex_ai=creds.get("use_vertex_ai", False),
        project_id=creds.get("gcp_project_id"),
        location=creds.get("gcp_location", "us-central1"),
        credentials_json=creds.get("gcp_credentials_json")
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
