from typing import List, Optional
from fastapi import APIRouter, Request, HTTPException, Query
from app.config import get_credentials
from app.services.zotero_service import ZoteroService
from app.schemas.schemas import (
    CollectionItem,
    PaperItem,
    ZoteroStatusResponse,
    SaveNoteRequest,
    SaveNoteResponse
)

router = APIRouter(prefix="/api/zotero", tags=["Zotero"])

def get_zotero_service(request: Request) -> ZoteroService:
    creds = get_credentials(request)
    if not creds["zotero_key"] or not creds["zotero_user_id"]:
        raise HTTPException(
            status_code=400,
            detail="Missing Zotero credentials. Please set ZOTERO_API_KEY and ZOTERO_USER_ID in .env or pass X-Zotero-Key and X-Zotero-User-Id headers."
        )
    return ZoteroService(
        api_key=creds["zotero_key"],
        user_id=creds["zotero_user_id"],
        library_type=creds["zotero_library_type"]
    )

@router.get("/verify", response_model=ZoteroStatusResponse)
async def verify_zotero(request: Request):
    """Verify connection to Zotero API and check permissions."""
    creds = get_credentials(request)
    if not creds["zotero_key"] or not creds["zotero_user_id"]:
        return ZoteroStatusResponse(
            connected=False,
            library_type=creds.get("zotero_library_type", "user"),
            user_id=creds.get("zotero_user_id"),
            total_collections=0,
            message="Credentials missing. Provide ZOTERO_API_KEY and ZOTERO_USER_ID."
        )

    service = ZoteroService(
        api_key=creds["zotero_key"],
        user_id=creds["zotero_user_id"],
        library_type=creds["zotero_library_type"]
    )
    result = await service.test_connection()
    return ZoteroStatusResponse(
        connected=result.get("connected", False),
        library_type=result.get("library_type", creds["zotero_library_type"]),
        user_id=result.get("user_id"),
        total_collections=result.get("total_collections", 0),
        message=result.get("message", "")
    )

@router.get("/collections", response_model=List[CollectionItem])
async def list_collections(request: Request):
    """Retrieve all collections in the user's or group's Zotero library."""
    service = get_zotero_service(request)
    return await service.get_collections()

@router.get("/items", response_model=dict)
async def list_items(
    request: Request,
    collection_key: Optional[str] = Query(None, description="Optional collection key"),
    query: Optional[str] = Query(None, description="Search keyword"),
    limit: int = Query(50, ge=1, le=100),
    start: int = Query(0, ge=0)
):
    """Fetch academic papers / items from library or a specific collection."""
    service = get_zotero_service(request)
    items, total = await service.get_items(
        collection_key=collection_key,
        query=query,
        limit=limit,
        start=start
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "start": start
    }

@router.get("/items/{item_key}", response_model=PaperItem)
async def get_item(item_key: str, request: Request):
    """Fetch details and attachment status of a single paper."""
    service = get_zotero_service(request)
    paper = await service.get_item(item_key)
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper with key '{item_key}' not found.")
    return paper

@router.post("/items/{item_key}/save-note", response_model=SaveNoteResponse)
async def save_note(item_key: str, payload: SaveNoteRequest, request: Request):
    """Save an AI literature review note directly under the specified paper in Zotero."""
    service = get_zotero_service(request)
    success, note_key, message = await service.create_child_note(
        parent_item_key=item_key,
        note_html=payload.note_html,
        tags=payload.tags
    )
    if not success:
        raise HTTPException(status_code=500, detail=message)

    return SaveNoteResponse(
        success=True,
        note_key=note_key,
        message=message
    )
