# 🎓 GResearch - AI Literature Review Studio & API

An intelligent academic literature review platform connecting the **Google Gemini API** (`gemini-2.5-flash` / `gemini-2.5-pro`) with the **Zotero Web API v3**.

Designed for researchers, PhD students, and research teams to automate deep paper critiques, synthesize comparative literature matrices across entire collections, uncover unexplored research gaps, and sync findings directly back into Zotero as rich child notes.

---

## 🌟 Key Capabilities

1. **📄 Single-Paper Deep Dive & Peer Critique**:
   - Analyzes theoretical grounding, methodology, sample characteristics, empirical claims, and limitations.
   - **Native PDF Understanding**: Automatically downloads attached PDFs from your Zotero cloud storage and feeds them into Gemini's multi-million token context window. Falls back seamlessly to abstracts when PDFs are unavailable.
   - Customizable analytical focus (e.g. *focus on statistical power*, *critique validity threats*, *extract ML architectures*).

2. **📚 Multi-Paper Thematic Synthesis Matrix**:
   - Synthesizes across multiple papers or an entire collection folder.
   - Formats a comparative matrix table (Paper Citation, Research Objective, Methodology/Sample, Primary Findings, Theoretical Stance).
   - Identifies areas of consensus, active debates, and chronological methodological evolution.

3. **🔍 Research Gap & Opportunity Finder**:
   - Detects empirical, methodological, and theoretical blind spots across your literature library.
   - Formulates concrete, high-impact novel research questions and proposes viable study designs.

4. **💬 Interactive Literature Q&A**:
   - Ask evidence-based questions across your library (e.g., *"Which papers evaluate on healthcare datasets?"*, *"Compare the sample sizes of Smith 2021 and Doe 2023"*).

5. **⚡ Direct Zotero Sync**:
   - One-click push to save generated reviews as formatted HTML child notes directly under papers in Zotero, automatically tagged (`#gemini-reviewed`, `#literature-review`).

6. **🖥️ Dual Interface**:
   - Modern, responsive **Web Dashboard** at `http://127.0.0.1:8000/`.
   - Full REST API with auto-generated **Swagger OpenAPI Docs** at `http://127.0.0.1:8000/docs`.

---

## 🚀 Quickstart

### 1. Requirements
- Python 3.10+ (Tested on Python 3.12)
- Google Gemini API Key
- Zotero Account (User ID & API Key)

### 2. Installation

Navigate to the project directory:
```powershell
cd C:\Users\mgaku\.gemini\antigravity\scratch\zotero-gemini-review
```

Create and activate a virtual environment:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:
```powershell
pip install -r requirements.txt
```

### 3. Configure Credentials

Copy `.env.example` to `.env`:
```powershell
copy .env.example .env
```

Open `.env` and configure your keys:
```env
# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Zotero Web API
ZOTERO_API_KEY=your_zotero_api_key_here
ZOTERO_USER_ID=your_zotero_user_id_here
ZOTERO_LIBRARY_TYPE=user
```

> **Tip**: You can also enter and switch API keys directly in the Web Dashboard via the **API Settings** modal.

#### How to get your API Keys:
1. **Google Gemini Key**:
   - Visit [Google AI Studio](https://aistudio.google.com/).
   - Click **Get API key** -> **Create API key**.
2. **Zotero User ID & API Key**:
   - Log in at [zotero.org/settings/keys](https://www.zotero.org/settings/keys).
   - Your **User ID** is shown at the top of the page (*"Your userID for use in API calls is XXXXXXX"*).
   - Click **Create new private key**, check **Allow library access** (Read/Write) and **Allow notes access**, then save the key.

---

### 4. Running the Application

Start the FastAPI server:
```powershell
.\.venv\Scripts\uvicorn app.main:app --reload --port 8000
```
Or directly:
```powershell
.\.venv\Scripts\python -m app.main
```

Open your browser to:
- **Interactive Web Studio**: `http://127.0.0.1:8000`
- **Swagger REST API Docs**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

---

## 📡 REST API Reference

All endpoints accept standard credentials from `.env` or custom request headers:
- `X-Gemini-Key`: Google Gemini API key
- `X-Gemini-Model`: Gemini model name (`gemini-2.5-flash` or `gemini-2.5-pro`)
- `X-Zotero-Key`: Zotero API key
- `X-Zotero-User-Id`: Zotero User ID
- `X-Zotero-Library-Type`: `user` or `group`

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health status and credential verification |
| `GET` | `/api/zotero/verify` | Test connection to Zotero API |
| `GET` | `/api/zotero/collections` | List all collections in library |
| `GET` | `/api/zotero/items` | List academic papers with pagination and filters |
| `GET` | `/api/zotero/items/{key}` | Get full metadata & PDF attachment status for a paper |
| `POST` | `/api/zotero/items/{key}/save-note` | Save review HTML as child note in Zotero |
| `POST` | `/api/review/paper` | Generate single paper critique & literature review |
| `POST` | `/api/review/synthesize` | Thematic literature synthesis across papers |
| `POST` | `/api/review/gaps` | Uncover research gaps and novel study designs |
| `POST` | `/api/review/chat` | Evidence-based interactive Q&A over library |

### Example API Request (Single Paper Review)

```bash
curl -X POST "http://127.0.0.1:8000/api/review/paper" \
     -H "Content-Type: application/json" \
     -d '{
       "item_key": "YOUR_ZOTERO_ITEM_KEY",
       "custom_focus": "Focus on methodological rigor and validity threats",
       "include_pdf": true
     }'
```

### Example API Request (Multi-Paper Synthesis)

```bash
curl -X POST "http://127.0.0.1:8000/api/review/synthesize" \
     -H "Content-Type: application/json" \
     -d '{
       "collection_key": "YOUR_COLLECTION_KEY",
       "research_theme": "How do attention mechanisms compare to recurrent networks for long sequences?"
     }'
```

---

## 🧪 Running Automated Tests

Run the test suite using `pytest`:

```powershell
.\.venv\Scripts\pytest -v
```

Tests cover:
- Zotero client connection, header formatting, and child note payload construction.
- Gemini prompt construction and Markdown-to-Zotero HTML conversion.
- API endpoints with mocked Zotero and Gemini services.
