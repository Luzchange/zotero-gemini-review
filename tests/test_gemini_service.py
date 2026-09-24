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
    from fastapi import HTTPException
    service = GeminiService(api_key="")
    with pytest.raises(HTTPException) as exc_info:
        service._get_client()
    assert exc_info.value.status_code == 401

def test_gemini_service_genai_mil_auto_detect():
    service = GeminiService(api_key="STARK_test12345")
    assert service._is_openai_compatible() is True
    assert service.base_url == "https://api.genai.mil/v1"

def test_gemini_service_custom_base_url():
    service = GeminiService(api_key="my_custom_key", base_url="https://api.example.com/v1")
    assert service._is_openai_compatible() is True
    assert service.base_url == "https://api.example.com/v1"

@pytest.mark.asyncio
async def test_gemini_service_openai_generation_mocked(monkeypatch):
    import httpx
    service = GeminiService(api_key="STARK_123", base_url="https://api.genai.mil/v1")

    class MockResponse:
        status_code = 200
        is_error = False

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "# Mock GenAI.mil Review\nSuccess!"
                        }
                    }
                ]
            }

    async def mock_post(self, url, headers=None, json=None):
        assert "chat/completions" in url
        assert headers["Authorization"] == "Bearer STARK_123"
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await service._generate_openai_compatible(
        model="gemini-2.5-flash",
        system_instruction="System prompt",
        user_prompt="Hello GenAI",
        temperature=0.2
    )

    assert "# Mock GenAI.mil Review" in result

@pytest.mark.asyncio
async def test_gemini_service_openai_ssl_inspection_recovery(monkeypatch):
    import httpx
    service = GeminiService(api_key="STARK_nipr_token", base_url="https://api.genai.mil/v1")

    attempts = []

    class MockResponse:
        status_code = 200
        is_error = False

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "# NIPR SSL Recovery Success"
                        }
                    }
                ]
            }

    async def mock_post(self, url, headers=None, json=None):
        attempts.append(self._transport)
        # First attempt with standard verify fails due to NIPR SSL interception
        if len(attempts) == 1:
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate")
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await service._generate_openai_compatible(
        model="gpt-4o",
        system_instruction="System prompt",
        user_prompt="NIPR test",
        temperature=0.2
    )

    assert "# NIPR SSL Recovery Success" in result
    assert len(attempts) >= 2  # Proves auto-retry with verify=False succeeded

@pytest.mark.asyncio
async def test_gemini_service_openai_model_cascade(monkeypatch):
    import httpx
    service = GeminiService(api_key="STARK_nipr_token", base_url="https://api.genai.mil/v1")

    tried_models = []

    class MockResponse:
        def __init__(self, model_name):
            self.model_name = model_name
            self.status_code = 200
            self.is_error = False
            self.text = '{"choices":[{"message":{"content":"# Cascade Review: ' + model_name + '"}}]}'

        def json(self):
            return {"choices": [{"message": {"content": f"# Cascade Review: {self.model_name}"}}]}

    class MockFailResponse:
        status_code = 404
        is_error = True
        text = '{"error": {"message": "The model gemini-2.5-flash does not exist on this gateway", "code": "model_not_found"}}'

        def json(self):
            return {"error": {"message": "The model gemini-2.5-flash does not exist on this gateway", "code": "model_not_found"}}

    async def mock_post(self, url, headers=None, json=None):
        m = json.get("model")
        tried_models.append(m)
        if m == "gemini-2.5-flash":
            return MockFailResponse()
        return MockResponse(m)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await service._generate_openai_compatible(
        model="gemini-2.5-flash",
        system_instruction="System",
        user_prompt="Cascade test"
    )

    assert "Cascade Review" in result
    assert "gpt-4o" in tried_models  # Successfully fell back to gpt-4o!


def test_gemini_service_default_model():
    service = GeminiService(api_key="fake_key")
    assert service.model == "auto"

@pytest.mark.asyncio
async def test_gemini_service_503_fallback(monkeypatch):
    service = GeminiService(api_key="fake_key")

    calls = []
    class MockGenerated:
        text = "Fallback Success Review"

    def mock_generate_content(model, contents, config):
        calls.append(model)
        if model == "gemini-2.5-flash":
            raise Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
        return MockGenerated()

    class MockClient:
        class models:
            generate_content = staticmethod(mock_generate_content)

    monkeypatch.setattr(service, "_get_client", lambda: MockClient())

    result = await service._generate_gemini_content(
        model="gemini-2.5-flash",
        contents=["test prompt"],
        config={}
    )
    assert result == "Fallback Success Review"
    assert "gemini-2.5-flash" in calls
    assert "gemini-2.0-flash" in calls

@pytest.mark.asyncio
async def test_gemini_service_404_not_found_auto_recovery(monkeypatch):
    """Verify that a 404 NOT_FOUND error immediately auto-cascades to the next working model."""
    service = GeminiService(api_key="fake_key")

    calls = []
    class MockGenerated:
        text = "Auto Cascaded Success Review"

    def mock_generate_content(model, contents, config):
        calls.append(model)
        if model == "custom-unsupported-model":
            raise Exception("404 NOT_FOUND. {'error': {'code': 404, 'message': 'models/custom-unsupported-model is not found for API version v1beta, or is not supported for generateContent. Call ModelService.ListModels to see the list of available models and their supported methods.'}}")
        return MockGenerated()

    class MockClient:
        class models:
            generate_content = staticmethod(mock_generate_content)

    monkeypatch.setattr(service, "_get_client", lambda: MockClient())

    result = await service._generate_gemini_content(
        model="custom-unsupported-model",
        contents=["test prompt"],
        config={}
    )
    assert result == "Auto Cascaded Success Review"
    assert "custom-unsupported-model" in calls
    assert "gemini-2.5-flash" in calls

@pytest.mark.asyncio
async def test_gemini_service_auto_mode(monkeypatch):
    """Verify that model='auto' automatically selects the best available model."""
    service = GeminiService(api_key="fake_key")

    calls = []
    class MockGenerated:
        text = "Auto Mode Review"

    def mock_generate_content(model, contents, config):
        calls.append(model)
        return MockGenerated()

    class MockClient:
        class models:
            generate_content = staticmethod(mock_generate_content)

    monkeypatch.setattr(service, "_get_client", lambda: MockClient())

    result = await service._generate_gemini_content(
        model="auto",
        contents=["test prompt"],
        config={}
    )
    assert result == "Auto Mode Review"
    assert calls[0] == "gemini-2.5-flash"

def test_vertex_ai_auto_detect_from_project_id():
    service = GeminiService(project_id="afrl-sandbox-12345")
    assert service.use_vertex_ai is True
    assert service.project_id == "afrl-sandbox-12345"
    assert service.location == "us-central1"

@pytest.mark.asyncio
async def test_vertex_ai_list_available_models():
    service = GeminiService(use_vertex_ai=True, project_id="my-project")
    models = await service.list_available_models()
    model_ids = [m["id"] for m in models]
    assert "gemini-2.5-flash" in model_ids
    assert "gemini-2.5-pro" in model_ids
    assert "gemini-2.0-flash" in model_ids

def test_vertex_ai_client_initialization_mocked(monkeypatch):
    import google.auth
    from google import genai

    captured_kwargs = {}

    class MockCredentials:
        pass

    def mock_default(scopes=None):
        return MockCredentials(), "detected-proj-999"

    class MockGenAIClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(google.auth, "default", mock_default)
    monkeypatch.setattr(genai, "Client", MockGenAIClient)

    service = GeminiService(use_vertex_ai=True, project_id="afrl-cloudlab-project", location="us-east4")
    client = service._get_client()

    assert captured_kwargs.get("vertexai") is True
    assert captured_kwargs.get("project") == "afrl-cloudlab-project"
    assert captured_kwargs.get("location") == "us-east4"
    assert isinstance(captured_kwargs.get("credentials"), MockCredentials)

def test_vertex_ai_missing_adc_error(monkeypatch):
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from fastapi import HTTPException

    def mock_default_err(scopes=None):
        raise DefaultCredentialsError("Could not automatically determine credentials.")

    monkeypatch.setattr(google.auth, "default", mock_default_err)

    service = GeminiService(use_vertex_ai=True, project_id="afrl-sandbox")
    with pytest.raises(HTTPException) as exc_info:
        service._get_client()

    assert exc_info.value.status_code == 401
    assert "gcloud auth application-default login" in exc_info.value.detail

def test_vertex_ai_with_credentials_json(monkeypatch):
    import json
    from google import genai
    from google.oauth2 import credentials as oauth2_creds

    captured_kwargs = {}

    class MockOAuthCreds:
        def __init__(self, **kwargs):
            pass

    def mock_from_info(info, scopes=None):
        return MockOAuthCreds()

    class MockGenAIClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(oauth2_creds.Credentials, "from_authorized_user_info", mock_from_info)
    monkeypatch.setattr(genai, "Client", MockGenAIClient)

    sample_json = json.dumps({
        "type": "authorized_user",
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "refresh_token": "test-refresh-token",
        "project_id": "afrl-il4-rch-usafsamoe-aewa"
    })

    service = GeminiService(credentials_json=sample_json)
    service._get_client()

    assert captured_kwargs.get("vertexai") is True
    assert captured_kwargs.get("project") == "afrl-il4-rch-usafsamoe-aewa"
    assert isinstance(captured_kwargs.get("credentials"), MockOAuthCreds)




