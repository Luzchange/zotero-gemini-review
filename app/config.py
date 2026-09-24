import urllib.parse
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
    GOOGLE_APPLICATION_CREDENTIALS_JSON: Optional[str] = None

    # Institutional / School Proxy (Troy University defaults)
    DEFAULT_SCHOOL_PROXY: str = "https://www-jstor-org.libproxy.troy.edu/"
    DEFAULT_SCHOOL_USERNAME: str = "mgakuria"
    DEFAULT_SCHOOL_PASSWORD: str = "JOYngami28!!"

    # Zotero Settings
    ZOTERO_API_KEY: Optional[str] = "qoszWMinOK1os3M4T9OTQLbH"
    ZOTERO_USER_ID: Optional[str] = "5425893"
    ZOTERO_LIBRARY_TYPE: str = "user"  # 'user' or 'group'
    DEFAULT_ZOTERO_COLLECTION: str = "GResearch"
    
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
    gcp_credentials_json = settings.GOOGLE_APPLICATION_CREDENTIALS_JSON
    zotero_key = settings.ZOTERO_API_KEY
    zotero_user_id = settings.ZOTERO_USER_ID
    zotero_library_type = settings.ZOTERO_LIBRARY_TYPE
    zotero_collection = settings.DEFAULT_ZOTERO_COLLECTION
    school_proxy = settings.DEFAULT_SCHOOL_PROXY
    school_user = settings.DEFAULT_SCHOOL_USERNAME
    school_pass = settings.DEFAULT_SCHOOL_PASSWORD

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

        req_gcp_creds_json = request.headers.get("x-gcp-credentials-json")
        if req_gcp_creds_json:
            try:
                gcp_credentials_json = urllib.parse.unquote(req_gcp_creds_json)
                use_vertex_ai = True
            except Exception:
                gcp_credentials_json = req_gcp_creds_json
                use_vertex_ai = True

        req_auth_provider = request.headers.get("x-auth-provider")
        if req_auth_provider:
            prov = req_auth_provider.lower().strip()
            if prov == "vertex":
                use_vertex_ai = True
            elif prov == "genaimil":
                use_vertex_ai = False
                if not gemini_base_url:
                    gemini_base_url = "https://api.genai.mil/v1"
            elif prov in ("aistudio", "gemini"):
                use_vertex_ai = False

        req_zotero_key = request.headers.get("x-zotero-key")
        if req_zotero_key:
            zotero_key = req_zotero_key

        req_zotero_user_id = request.headers.get("x-zotero-user-id")
        if req_zotero_user_id:
            zotero_user_id = req_zotero_user_id

        req_zotero_lib_type = request.headers.get("x-zotero-library-type")
        if req_zotero_lib_type:
            zotero_library_type = req_zotero_lib_type

        req_zotero_col = request.headers.get("x-zotero-collection")
        if req_zotero_col:
            zotero_collection = req_zotero_col

        req_school_proxy = request.headers.get("x-school-proxy")
        if req_school_proxy:
            school_proxy = req_school_proxy

        req_school_user = request.headers.get("x-school-username")
        if req_school_user:
            school_user = req_school_user

        req_school_pass = request.headers.get("x-school-password")
        if req_school_pass:
            school_pass = req_school_pass

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
        "gemini_model": gemini_model or "auto",
        "gemini_base_url": cleaned_base_url,
        "use_vertex_ai": use_vertex_ai,
        "gcp_project_id": cleaned_project_id,
        "gcp_location": clean_val(gcp_location) or "us-central1",
        "gcp_credentials_json": gcp_credentials_json,
        "zotero_key": clean_val(zotero_key),
        "zotero_user_id": clean_val(zotero_user_id),
        "zotero_library_type": zotero_library_type or "user",
        "zotero_collection": clean_val(zotero_collection) or "GResearch",
        "school_proxy": clean_val(school_proxy) or "https://www-jstor-org.libproxy.troy.edu/",
        "school_user": clean_val(school_user) or "mgakuria",
        "school_pass": clean_val(school_pass) or "JOYngami28!!",
    }
