import io
import uuid
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Form

from pypdf import PdfReader

from app.config import get_credentials
from app.services.gemini_service import GeminiService
from app.services.zotero_service import ZoteroService
from app.schemas.schemas import (
    WorkDocument,
    WorkDocumentUploadResponse,
    WorkDocumentReviewRequest,
    WorkDocumentReviewResponse,
    WorkDocumentChatRequest,
    WorkDocumentChatResponse,
    SaveDocumentToZoteroRequest
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["Work Documents"])

# In-memory document storage for session
# document_id -> { "id", "filename", "title", "page_count", "file_size_bytes", "text", "pdf_bytes" }
UPLOADED_DOCUMENTS: Dict[str, Dict[str, Any]] = {}

@router.post("/upload", response_model=WorkDocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a local PDF work document for instant research and review."""
    filename = file.filename or "uploaded_document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are currently supported for work document review.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=413, detail="File too large. Maximum supported size is 50MB.")

    # Extract text and page count via pypdf
    try:
        reader = PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
        extracted_text_chunks = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                extracted_text_chunks.append(f"--- [Page {i + 1}] ---\n{page_text.strip()}")
        full_text = "\n\n".join(extracted_text_chunks)
    except Exception as e:
        logger.error(f"Failed to parse PDF {filename}: {e}")
        raise HTTPException(status_code=422, detail=f"Could not parse PDF content: {str(e)}")

    if not full_text.strip():
        full_text = f"[Scanned/Image PDF - Text extraction empty for {filename}]"

    # Infer a title: either from PDF metadata or clean filename
    title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
    try:
        if reader.metadata and reader.metadata.title:
            meta_title = reader.metadata.title.strip()
            if len(meta_title) > 3:
                title = meta_title
    except Exception:
        pass

    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    UPLOADED_DOCUMENTS[doc_id] = {
        "id": doc_id,
        "filename": filename,
        "title": title,
        "page_count": page_count,
        "file_size_bytes": len(content),
        "text": full_text,
        "pdf_bytes": content
    }

    logger.info(f"Successfully processed uploaded document {doc_id} ('{title}', {page_count} pages)")

    return WorkDocumentUploadResponse(
        document_id=doc_id,
        filename=filename,
        title=title,
        page_count=page_count,
        file_size_bytes=len(content),
        message=f"Successfully extracted {page_count} pages from {filename}."
    )

@router.get("/list", response_model=List[WorkDocument])
async def list_documents():
    """List all documents currently available in this session."""
    return [
        WorkDocument(
            id=d["id"],
            filename=d["filename"],
            title=d["title"],
            page_count=d["page_count"],
            file_size_bytes=d["file_size_bytes"],
            text_preview=d["text"][:300] + ("..." if len(d["text"]) > 300 else "")
        )
        for d in UPLOADED_DOCUMENTS.values()
    ]

@router.delete("/{document_id}")
async def delete_document(document_id: str):
    """Remove an uploaded document from the current session."""
    if document_id in UPLOADED_DOCUMENTS:
        del UPLOADED_DOCUMENTS[document_id]
        return {"success": True, "message": f"Document {document_id} removed."}
    raise HTTPException(status_code=404, detail="Document not found.")

@router.post("/review", response_model=WorkDocumentReviewResponse)
async def review_document(request: Request, body: WorkDocumentReviewRequest):
    """
    Generate tailored analysis (BLUF, Red Team, Policy, Technical) of an uploaded document.
    By default, automatically imports document and attaches review note to Zotero if credentials exist.
    """
    creds = get_credentials(request)
    if not creds.get("gemini_key") and not creds.get("use_vertex_ai"):
        raise HTTPException(
            status_code=401,
            detail="Gemini API Key or Vertex AI OAuth is required. Please configure it in Settings."
        )

    doc = UPLOADED_DOCUMENTS.get(body.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or session expired. Please re-upload.")

    gemini_svc = GeminiService(
        api_key=creds.get("gemini_key") or "",
        default_model=body.model or creds["gemini_model"],
        base_url=creds.get("gemini_base_url"),
        use_vertex_ai=creds.get("use_vertex_ai", False),
        project_id=creds.get("gcp_project_id"),
        location=creds.get("gcp_location", "us-central1")
    )

    review_md, zotero_html = await gemini_svc.review_work_document(
        title=doc["title"],
        text=doc["text"],
        pdf_bytes=doc.get("pdf_bytes"),
        profile=body.profile,
        custom_focus=body.custom_focus,
        model_override=body.model
    )

    zotero_saved = False
    zotero_item_key = None
    zotero_note_key = None
    message = "Review generated successfully."

    # Automatically import into Zotero if requested (default=True)
    if body.import_to_zotero:
        if creds.get("zotero_key") and creds.get("zotero_user_id"):
            try:
                zotero_svc = ZoteroService(
                    api_key=creds["zotero_key"],
                    user_id=creds["zotero_user_id"],
                    library_type=creds.get("zotero_library_type", "user")
                )
                success, item_key, item_msg = await zotero_svc.create_document_item(
                    title=doc["title"],
                    abstract_note=f"Imported work document ({doc['page_count']} pages). Reviewed via GResearch.",
                    collection_key=body.collection_key,
                    tags=["work-document", f"profile-{body.profile}"]
                )
                if success and item_key:
                    zotero_item_key = item_key
                    note_success, note_key, _ = await zotero_svc.create_child_note(
                        parent_item_key=item_key,
                        note_html=zotero_html,
                        tags=["gemini-reviewed", f"profile-{body.profile}"]
                    )
                    zotero_saved = True
                    zotero_note_key = note_key
                    message = f"Review generated and saved to Zotero as item '{doc['title']}' (Key: {item_key})."
                else:
                    message = f"Review generated. Zotero item creation notice: {item_msg}"
            except Exception as e:
                logger.warning(f"Failed to auto-import document to Zotero: {e}")
                message = f"Review generated. (Zotero auto-import failed: {str(e)})"
        else:
            message = "Review generated. (Configure Zotero in Settings to automatically sync reviews to your library)."

    return WorkDocumentReviewResponse(
        document_id=body.document_id,
        title=doc["title"],
        profile=body.profile,
        review_markdown=review_md,
        zotero_saved=zotero_saved,
        zotero_item_key=zotero_item_key,
        zotero_note_key=zotero_note_key,
        message=message
    )

@router.post("/chat", response_model=WorkDocumentChatResponse)
async def chat_documents(request: Request, body: WorkDocumentChatRequest):
    """Grounded interactive Q&A against one or more uploaded work documents."""
    creds = get_credentials(request)
    if not creds.get("gemini_key") and not creds.get("use_vertex_ai"):
        raise HTTPException(status_code=401, detail="Gemini API Key or Vertex AI OAuth is required.")

    selected_docs = [UPLOADED_DOCUMENTS[d_id] for d_id in body.document_ids if d_id in UPLOADED_DOCUMENTS]
    if not selected_docs:
        raise HTTPException(status_code=400, detail="No valid uploaded documents selected.")

    gemini_svc = GeminiService(
        api_key=creds.get("gemini_key") or "",
        default_model=body.model or creds["gemini_model"],
        base_url=creds.get("gemini_base_url"),
        use_vertex_ai=creds.get("use_vertex_ai", False),
        project_id=creds.get("gcp_project_id"),
        location=creds.get("gcp_location", "us-central1")
    )

    answer = await gemini_svc.chat_with_work_documents(
        documents=selected_docs,
        query=body.query,
        chat_history=body.chat_history,
        model_override=body.model
    )

    cited = [d["title"] for d in selected_docs if d["title"].lower() in answer.lower()]

    return WorkDocumentChatResponse(
        answer=answer,
        cited_documents=cited
    )

@router.post("/save-to-zotero")
async def save_to_zotero(request: Request, body: SaveDocumentToZoteroRequest):
    """Explicitly save an uploaded work document and its review note to Zotero."""
    creds = get_credentials(request)
    if not creds.get("zotero_key") or not creds.get("zotero_user_id"):
        raise HTTPException(status_code=401, detail="Zotero API key and User ID must be configured in Settings.")

    doc = UPLOADED_DOCUMENTS.get(body.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in current session.")

    zotero_svc = ZoteroService(
        api_key=creds["zotero_key"],
        user_id=creds["zotero_user_id"],
        library_type=creds.get("zotero_library_type", "user")
    )

    # Convert review markdown to HTML
    gemini_svc = GeminiService(api_key="fake")
    zotero_html = gemini_svc._markdown_to_zotero_html(body.review_markdown, doc["title"])

    success, item_key, item_msg = await zotero_svc.create_document_item(
        title=doc["title"],
        abstract_note=f"Work document ({doc['page_count']} pages). Reviewed via GResearch.",
        collection_key=body.collection_key,
        tags=["work-document", "gemini-reviewed"]
    )

    if not success or not item_key:
        raise HTTPException(status_code=502, detail=f"Failed to create Zotero item: {item_msg}")

    note_success, note_key, note_msg = await zotero_svc.create_child_note(
        parent_item_key=item_key,
        note_html=zotero_html,
        tags=["gemini-reviewed", "work-document-review"]
    )

    return {
        "success": True,
        "item_key": item_key,
        "note_key": note_key,
        "message": f"Successfully created Zotero item '{doc['title']}' and attached review note."
    }
