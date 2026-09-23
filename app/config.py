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
    GEMINI_MODEL: str = "gemini-2.5-flash"
    
    ZOTERO_API_KEY: Optional[str] = None
    ZOTERO_USER_ID: Optional[str] = None
    ZOTERO_LIBRARY_TYPE: str = "user"  # 'user' or 'group'
    
    HOST: str = "127.0.0.1"
    PORT: int = 8000

settings = Settings()

def get_credentials(request: Optional[Request] = None):
    """
    Resolves credentials with priority:
    1. HTTP Request headers (X-Gemini-Key, X-Zotero-Key, X-Zotero-User-Id, X-Zotero-Library-Type)
    2. Environment variables / .env file
    """
    gemini_key = settings.GEMINI_API_KEY
    gemini_model = settings.GEMINI_MODEL
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

    return {
        "gemini_key": clean_val(gemini_key),
        "gemini_model": gemini_model or "gemini-2.5-flash",
        "zotero_key": clean_val(zotero_key),
        "zotero_user_id": clean_val(zotero_user_id),
        "zotero_library_type": zotero_library_type or "user",
    }
