from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi import Request

class Settings(BaseSettings):
    """Application configuration and credentials settings."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "auto"
    GEMINI_BASE_URL: Optional[str] = None
    
    # Google Cloud Vertex AI / CloudLab Settings
    USE_VERTEX_AI: bool = False
    GCP_PROJECT_ID: Optional[str] = None
    GCP_LOCATION: str = "us-central1"
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

    ZOTERO_API_KEY: Optional[str] = "qoszWMinOK1os3M4T9OTQLbH"
    ZOTERO_USER_ID: Optional[str] = "5425893"
    ZOTERO_LIBRARY_TYPE: str = "user"  # 'user' or 'group'
    
    HOST: str = "127.0.0.1"
    PORT: int = 8000

settings = Settings()

def get_credentials(request: Optional[Request] = None):
    """
    Resolves credentials with priority:
    1. HTTP Request headers (X-Gemini-Key, X-Use-Vertex-Ai, X-Gcp-Project-Id, X-Gcp-Location, etc.)
    2. Environment variables / .env file
    """
    gemini_key = settings.GEMINI_API_KEY
    gemini_model = settings.GEMINI_MODEL
    gemini_base_url = settings.GEMINI_BASE_URL
    use_vertex_ai = settings.USE_VERTEX_AI
    gcp_project_id = settings.GCP_PROJECT_ID
    gcp_location = settings.GCP_LOCATION
    zotero_key = settings.ZOTERO_API_KEY
    zotero_user_id = settings.ZOTERO_USER_ID
    zotero_library_type = settings.ZOTERO_LIBRARY_TYPE

    if request:
        req_gemini_key = request.headers.get("x-gemini-key")
        if req_gemini_key:
            gemini_key = req_gemini_key

        req_gemini_model = request.headers.get("x-gemini-model")
        if req_gemini_model:
            gemini_model = req_gemini_model

        req_gemini_base_url = request.headers.get("x-gemini-base-url")
        if req_gemini_base_url:
            gemini_base_url = req_gemini_base_url

        req_use_vertex = request.headers.get("x-use-vertex-ai")
        if req_use_vertex is not None:
            use_vertex_ai = req_use_vertex.lower() in ("true", "1", "yes")

        req_gcp_project = request.headers.get("x-gcp-project-id")
        if req_gcp_project:
            gcp_project_id = req_gcp_project

        req_gcp_location = request.headers.get("x-gcp-location")
        if req_gcp_location:
            gcp_location = req_gcp_location

        req_zotero_key = request.headers.get("x-zotero-key")
        if req_zotero_key:
            zotero_key = req_zotero_key

        req_zotero_user_id = request.headers.get("x-zotero-user-id")
        if req_zotero_user_id:
            zotero_user_id = req_zotero_user_id

        req_zotero_lib_type = request.headers.get("x-zotero-library-type")
        if req_zotero_lib_type:
            zotero_library_type = req_zotero_lib_type

    def clean_val(v: Optional[str]) -> Optional[str]:
        if not v or "your_" in v.lower() or "here" in v.lower():
            return None
        return v.strip()

    # Automatically set GenAI.mil base URL if STARK token is provided and base URL is not set
    cleaned_key = clean_val(gemini_key)
    cleaned_base_url = clean_val(gemini_base_url)
    if cleaned_key and cleaned_key.startswith("STARK_") and not cleaned_base_url:
        cleaned_base_url = "https://api.genai.mil/v1"

    # If project ID is provided and no key is given, default to Vertex AI mode
    cleaned_project_id = clean_val(gcp_project_id)
    if cleaned_project_id and not cleaned_key:
        use_vertex_ai = True

    return {
        "gemini_key": cleaned_key,
        "gemini_model": gemini_model or "gemini-3.6-flash",
        "gemini_base_url": cleaned_base_url,
        "use_vertex_ai": use_vertex_ai,
        "gcp_project_id": cleaned_project_id,
        "gcp_location": clean_val(gcp_location) or "us-central1",
        "zotero_key": clean_val(zotero_key),
        "zotero_user_id": clean_val(zotero_user_id),
        "zotero_library_type": zotero_library_type or "user",
    }
