import json
import logging
import io
from typing import List, Dict, Any, Optional, Tuple
import httpx
import markdown
import asyncio
from fastapi import HTTPException

from app.schemas.schemas import (
    PaperItem,
    SinglePaperReviewResponse,
    CollectionSynthesisResponse,
    SynthesisMatrixRow,
    ResearchGapResponse,
    IdentifiedGap,
    LiteratureChatResponse
)

logger = logging.getLogger(__name__)

class GeminiService:
    """Service handling literature analysis via Google Gemini API, Google Cloud Vertex AI (OAuth / ADC), and OpenAI-compatible gateways (e.g. GenAI.mil)."""

    def __init__(
        self,
        api_key: Optional[str] = "",
        default_model: str = "auto",
        base_url: Optional[str] = None,
        use_vertex_ai: bool = False,
        project_id: Optional[str] = None,
        location: str = "us-central1"
    ):
        self.api_key = api_key.strip() if api_key else ""
        self.model = default_model or "auto"
        self.base_url = base_url.strip() if base_url else ""
        self.use_vertex_ai = use_vertex_ai
        self.project_id = project_id.strip() if project_id else None
        self.location = location.strip() if location else "us-central1"

        # If project_id is provided and no key is given, default to Vertex AI mode
        if self.project_id and not self.api_key and not self.base_url:
            self.use_vertex_ai = True

        # Auto-detect GenAI.mil DoD token
        if self.api_key.startswith("STARK_") and not self.base_url:
            self.base_url = "https://api.genai.mil/v1"
        self._client = None

    def _is_openai_compatible(self) -> bool:
        return bool(self.base_url) or self.api_key.startswith("STARK_")

    async def _generate_openai_compatible(
        self,
        model: str,
        system_instruction: str,
        user_prompt: str,
        temperature: float = 0.2
    ) -> str:
        """Call an OpenAI-compatible endpoint such as GenAI.mil (/v1/chat/completions)."""
        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": user_prompt})

        actual_model = model
        if not actual_model or actual_model == "auto":
            actual_model = "gemini-2.5-flash"

        payload = {
            "model": actual_model,
            "messages": messages,
            "temperature": temperature
        }

        logger.info(f"Dispatching request to GenAI endpoint: {endpoint} (model: {actual_model})")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(endpoint, headers=headers, json=payload)
                if resp.is_error:
                    if "outside of DoW networks" in resp.text or "Unauthorized Access - GenAI.mil" in resp.text:
                        error_detail = (
                            "GenAI.mil Network Firewall Block: "
                            "GenAI.mil can only be accessed from inside DoD/DoW networks. "
                            "Please connect to your military/command VPN (e.g. GlobalProtect) to use this token, "
                            "or switch to a standard Google AI Studio key if working off-network."
                        )
                    else:
                        try:
                            err_json = resp.json()
                            error_detail = err_json.get("error", {}).get("message") or err_json.get("detail") or resp.text
                        except Exception:
                            if "<html" in resp.text.lower():
                                error_detail = f"Endpoint returned an HTML page instead of JSON (HTTP {resp.status_code})"
                            else:
                                error_detail = resp.text

                    raise HTTPException(
                        status_code=resp.status_code if resp.status_code >= 400 else 502,
                        detail=error_detail
                    )
                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    raise HTTPException(status_code=502, detail=f"No response choices returned by GenAI: {data}")
                return choices[0]["message"]["content"]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error connecting to GenAI endpoint ({endpoint}): {e}")
            raise HTTPException(status_code=502, detail=f"Failed to connect to GenAI endpoint: {str(e)}")

    def _get_client(self):
        """Lazy load google-genai client, supporting both Vertex AI (OAuth / ADC) and Google AI Studio (API Key)."""
        if self._client is not None:
            return self._client

        from google import genai

        if self.use_vertex_ai:
            try:
                import google.auth
                credentials, detected_project = google.auth.default(
                    scopes=[
                        "https://www.googleapis.com/auth/cloud-platform",
                        "https://www.googleapis.com/auth/generative-language.retriever"
                    ]
                )
                project = self.project_id or detected_project
                if not project:
                    raise ValueError(
                        "GCP Project ID is required for Vertex AI. Please configure it in Settings or set via 'gcloud config set project <PROJECT_ID>'."
                    )
                self._client = genai.Client(
                    vertexai=True,
                    project=project,
                    location=self.location,
                    credentials=credentials
                )
                logger.info(f"Initialized google-genai Vertex AI client (project={project}, location={self.location})")
                return self._client
            except Exception as e:
                logger.error(f"Failed to initialize google-genai Vertex AI client: {e}")
                err_msg = str(e)
                if "could not automatically determine credentials" in err_msg.lower() or "defaultcredentialserror" in err_msg.lower():
                    raise HTTPException(
                        status_code=401,
                        detail=(
                            "Vertex AI Application Default Credentials (ADC) not found. "
                            "Please run the following 3 commands in your terminal to authorize your OAuth credentials:\n"
                            "1) gcloud auth login\n"
                            f"2) gcloud config set project {self.project_id or 'PROJECT_ID'}\n"
                            "3) gcloud auth application-default login --client-id-file=CLIENT_SECRET.json --scopes=\"https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/generative-language.retriever\""
                        )
                    )
                raise HTTPException(status_code=500, detail=f"Vertex AI initialization failed: {err_msg}")

        # AI Studio API Key mode
        if not self.api_key:
            raise HTTPException(
                status_code=401,
                detail="Gemini API Key or Vertex AI OAuth is required. Please configure credentials in Settings."
            )
        try:
            self._client = genai.Client(api_key=self.api_key)
            return self._client
        except Exception as e:
            logger.error(f"Failed to initialize google-genai client: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to initialize Gemini client: {str(e)}")

    async def list_available_models(self) -> List[Dict[str, Any]]:
        """List available models for this provider."""
        auto_entry = {"id": "auto", "display_name": "⚡ Auto (Best Available Model - Recommended)"}
        if self._is_openai_compatible():
            return [
                auto_entry,
                {"id": "gemini-2.5-flash", "display_name": "gemini-2.5-flash (GenAI.mil Recommended)"},
                {"id": "gemini-2.0-flash", "display_name": "gemini-2.0-flash"},
            ]

        if self.use_vertex_ai:
            return [
                auto_entry,
                {"id": "gemini-2.5-flash", "display_name": "gemini-2.5-flash (Vertex AI / CloudLab Recommended)"},
                {"id": "gemini-2.5-pro", "display_name": "gemini-2.5-pro (Vertex AI Deep Reasoning)"},
                {"id": "gemini-2.0-flash", "display_name": "gemini-2.0-flash (Vertex AI General Purpose)"},
            ]

        try:
            client = self._get_client()
            models_pager = client.models.list()
            available = [auto_entry]
            for m in models_pager:
                model_id = m.name.replace("models/", "") if getattr(m, "name", None) else ""
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions or not actions:
                    if not any(x in model_id.lower() for x in ["embedding", "imagen", "aqa", "bison"]):
                        available.append({
                            "id": model_id,
                            "display_name": getattr(m, "display_name", "") or model_id,
                            "description": getattr(m, "description", "") or ""
                        })
            return available
        except Exception as e:
            logger.warning(f"Failed to list models dynamically from Gemini API: {e}")
            return [
                auto_entry,
                {"id": "gemini-2.5-flash", "display_name": "gemini-2.5-flash (Recommended)"},
                {"id": "gemini-2.0-flash", "display_name": "gemini-2.0-flash"},
                {"id": "gemini-2.0-flash-lite", "display_name": "gemini-2.0-flash-lite"},
                {"id": "gemini-2.5-pro", "display_name": "gemini-2.5-pro"},
            ]

    async def _generate_gemini_content(
        self,
        model: str,
        contents: List[Any],
        config: Dict[str, Any]
    ) -> str:
        """Call client.models.generate_content with self-healing model cascade and 404/503 auto-recovery."""
        client = self._get_client()

        # Build candidate cascade based on environment
        if self.use_vertex_ai:
            default_cascade = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
        else:
            default_cascade = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-pro"]

        requested_model = (model or "").strip()
        if not requested_model or requested_model == "auto":
            models_to_try = list(default_cascade)
        else:
            models_to_try = [requested_model]
            for m in default_cascade:
                if m not in models_to_try:
                    models_to_try.append(m)

        last_error = None
        for candidate_model in models_to_try:
            # Skip models known to trigger 404 on Google AI Studio v1beta
            if not self.use_vertex_ai and candidate_model in ("gemini-1.5-flash", "models/gemini-1.5-flash", "gemini-3.6-flash"):
                logger.info(f"Skipping legacy/deprecated model {candidate_model} on v1beta API")
                continue

            for attempt in range(2):
                try:
                    logger.info(f"Generating content with model: {candidate_model} (attempt {attempt + 1})")
                    response = client.models.generate_content(
                        model=candidate_model,
                        contents=contents,
                        config=config
                    )
                    return response.text or "No response generated."
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    err_lower = err_str.lower()

                    # 1. Vertex AI 403 Permission Denied
                    if self.use_vertex_ai and ("403" in err_str or "permissiondenied" in err_lower):
                        raise HTTPException(
                            status_code=403,
                            detail=(
                                f"Vertex AI Permission Denied for project '{self.project_id}'. "
                                "Please verify: 1) Vertex AI API is enabled in GCP Console, "
                                "and 2) your account has the 'Vertex AI User' role on this project."
                            )
                        )

                    # 2. 404 NOT_FOUND / unsupported model: immediately switch to next model in cascade
                    is_not_found = (
                        "404" in err_str or 
                        "not found" in err_lower or 
                        "not supported for generatecontent" in err_lower or
                        "call modelservice.listmodels" in err_lower
                    )
                    if is_not_found:
                        logger.warning(
                            f"Model '{candidate_model}' is not supported or not found on this API version ({e}). "
                            "Auto-switching to next available model in cascade..."
                        )
                        break

                    # 3. 503 High Demand / 429 Rate Limit: retry with backoff
                    is_transient = (
                        "503" in err_str or 
                        "429" in err_str or 
                        "high demand" in err_lower or 
                        "unavailable" in err_lower or
                        "resourceexhausted" in err_lower
                    )
                    if is_transient:
                        logger.warning(f"Model {candidate_model} busy/high demand ({e}), retrying in {attempt + 1.5}s...")
                        await asyncio.sleep(attempt + 1.5)
                        continue
                    else:
                        logger.warning(f"Model {candidate_model} encountered non-transient error: {e}. Trying fallback model...")
                        break

            logger.info(f"Model {candidate_model} unavailable or exhausted; cascading to next candidate model...")

        # If all predefined models failed with 404/transient errors, try dynamic discovery via client.models.list()
        try:
            logger.info("Attempting dynamic fallback discovery via client.models.list()...")
            available_pager = client.models.list()
            for m in available_pager:
                m_id = m.name.replace("models/", "") if getattr(m, "name", None) else ""
                actions = getattr(m, "supported_actions", None) or []
                if m_id and m_id not in models_to_try and ("generateContent" in actions or not actions):
                    if not any(x in m_id.lower() for x in ["embedding", "imagen", "aqa", "bison"]):
                        logger.info(f"Dynamically discovered fallback model: {m_id}. Attempting generation...")
                        try:
                            response = client.models.generate_content(
                                model=m_id,
                                contents=contents,
                                config=config
                            )
                            return response.text or "No response generated."
                        except Exception as dyn_err:
                            logger.warning(f"Dynamic fallback model {m_id} also failed: {dyn_err}")
                            continue
        except Exception as list_err:
            logger.debug(f"Could not list models dynamically: {list_err}")

        logger.error(f"Gemini API generation failed after retries and automatic fallbacks: {last_error}")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini generation failed: {str(last_error)}. You can set Model to 'Auto' in Settings for automatic model selection."
        )

    def _build_paper_summary_text(self, paper: PaperItem) -> str:
        """Format paper metadata and abstract into clean textual context."""
        authors = ", ".join(paper.creators) if paper.creators else "Unknown Authors"
        year_str = f" ({paper.year})" if paper.year else ""
        pub = f" in {paper.publication_title}" if paper.publication_title else ""
        doi_str = f" | DOI: {paper.doi}" if paper.doi else ""
        
        abstract = paper.abstract_note.strip() if paper.abstract_note else "No abstract provided in Zotero."
        tags = ", ".join(paper.tags) if paper.tags else "None"

        return (
            f"### [Paper ID: {paper.key}] {paper.title}\n"
            f"- Authors: {authors}{year_str}{pub}{doi_str}\n"
            f"- Tags: {tags}\n"
            f"- Abstract / Notes:\n{abstract}\n"
        )

    def _markdown_to_zotero_html(self, md_content: str, title: str) -> str:
        """
        Convert markdown content into Zotero-compatible HTML note format.
        Zotero notes support standard HTML tags: h1, h2, h3, p, ul, ol, li, blockquote, strong, em, table, etc.
        """
        html_body = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
        header = f"<p><strong>🤖 Gemini Literature Review: {title}</strong></p><hr/>"
        return f"{header}\n{html_body}"

    async def review_single_paper(
        self,
        paper: PaperItem,
        pdf_bytes: Optional[bytes] = None,
        custom_focus: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> SinglePaperReviewResponse:
        """Perform a rigorous, structured academic critique and deep dive on a single paper."""
        active_model = model_override or self.model

        authors = ", ".join(paper.creators) if paper.creators else "Unknown Authors"
        citation = f"{authors} ({paper.year or 'n.d.'}). {paper.title}."

        system_instruction = (
            "You are an elite academic peer reviewer and principal researcher. "
            "Analyze the provided academic paper with maximum scholarly rigor, precision, and objectivity. "
            "Evaluate theoretical grounding, methodology, empirical findings, threats to validity, and limitations. "
            "Provide structured, comprehensive output in clean Markdown."
        )

        focus_prompt = f"\nSpecial analytical focus: {custom_focus}\n" if custom_focus else ""

        user_prompt = f"""
Please perform an in-depth academic literature review and critique for the following paper:

Paper Citation: {citation}
Publication: {paper.publication_title}
Abstract: {paper.abstract_note}
{focus_prompt}

Please structure your review using the following standard sections:
1. **Academic Citation & Overview**: Formal citation and 2-3 sentence executive summary of the paper's thesis.
2. **Core Research Question & Theoretical Framework**: The central problem addressed, underlying theories, and conceptual foundations.
3. **Methodology & Research Design**: Data sources, sample size/characteristics, experimental setup, or qualitative methodology.
4. **Key Empirical Findings & Contributions**: Specific findings, metrics, and theoretical or practical claims made by the authors.
5. **Critical Evaluation & Methodological Limitations**: Methodological strengths, sample biases, confounding variables, threats to internal/external validity, and theoretical shortcomings.
6. **Future Directions & Open Questions**: Unanswered questions and fruitful paths for subsequent research.
7. **Key Quotes / Excerpts**: 2-4 impactful quotes or direct formulations from the paper.

Output format:
Respond in rich, professional Markdown with clear headings.
"""

        if self._is_openai_compatible():
            if pdf_bytes:
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(pdf_bytes))
                    pages_text = [page.extract_text() or "" for page in reader.pages[:40]]
                    pdf_text = "\n".join(pages_text).strip()
                    if pdf_text:
                        logger.info(f"Extracted {len(pdf_text)} characters from PDF for GenAI analysis.")
                        user_prompt += f"\n\n---\nFULL EXTRACTED PAPER TEXT FROM PDF:\n{pdf_text[:80000]}\n---"
                except Exception as e:
                    logger.warning(f"Could not extract text from PDF: {e}")
            review_md = await self._generate_openai_compatible(
                model=active_model,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                temperature=0.2
            )
        else:
            client = self._get_client()
            contents: List[Any] = []
            if pdf_bytes:
                from google.genai import types
                logger.info(f"Including full PDF attachment ({len(pdf_bytes)} bytes) in Gemini prompt.")
                contents.append(
                    types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type="application/pdf"
                    )
                )
            contents.append(user_prompt)

            review_md = await self._generate_gemini_content(
                model=active_model,
                contents=contents,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.2,
                }
            )

        zotero_html = self._markdown_to_zotero_html(review_md, paper.title)

        # Basic section parsing for structured response
        return SinglePaperReviewResponse(
            item_key=paper.key,
            title=paper.title,
            citation=citation,
            research_question="Extracted in review markdown",
            theoretical_background="Extracted in review markdown",
            methodology="Extracted in review markdown",
            key_findings=["Detailed in review markdown"],
            limitations_and_critique=["Detailed in review markdown"],
            future_directions=["Detailed in review markdown"],
            key_quotes=[],
            review_markdown=review_md,
            zotero_html_note=zotero_html
        )

    async def synthesize_collection(
        self,
        papers: List[PaperItem],
        research_theme: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> CollectionSynthesisResponse:
        """
        Perform a thematic literature synthesis across multiple papers,
        producing a comparative matrix, consensus points, and debates.
        """
        if not papers:
            raise ValueError("No papers provided for synthesis.")

        active_model = model_override or self.model

        theme_text = f"Research Theme: '{research_theme}'" if research_theme else "General Thematic Review across Collection"

        papers_context = "\n---\n".join([self._build_paper_summary_text(p) for p in papers])

        system_instruction = (
            "You are a distinguished research scholar authoring a comprehensive, publication-grade Literature Review synthesis. "
            "You critically synthesize multiple academic sources, map debates, contrast methodological paradigms, "
            "and create structured comparative analysis."
        )

        user_prompt = f"""
Perform a comprehensive Literature Review synthesis across the following {len(papers)} papers.
{theme_text}

Here is the library of papers to synthesize:
{papers_context}

Please provide your synthesis in structured Markdown with these specific sections:

## 1. Synthesis Overview & Thematic Framing
A high-level synthesis defining the scope, unifying questions, and how this body of work addresses the theme.

## 2. Comparative Synthesis Matrix
Create a detailed Markdown Table with columns:
| Paper (Citation) | Research Objective | Methodology / Sample | Primary Findings | Theoretical Stance / Perspective |

## 3. Areas of Academic Consensus
Key points, empirical findings, or theoretical principles where these studies align and reinforce each other.

## 4. Divergences, Debates & Conflicting Findings
Specific contradictions, differing interpretations, or empirical disagreements between the papers, explaining why these differences likely occur (e.g., differing sample demographics, methodological assumptions, operationalizations).

## 5. Methodological & Chronological Evolution
How research methods and questions have evolved across these works over time.

## 6. Synthesis Narrative & Implications
A cohesive narrative synthesizing the current state of knowledge and implications for researchers.
"""

        if self._is_openai_compatible():
            synthesis_md = await self._generate_openai_compatible(
                model=active_model,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                temperature=0.3
            )
        else:
            synthesis_md = await self._generate_gemini_content(
                model=active_model,
                contents=[user_prompt],
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.3,
                }
            )

        zotero_html = self._markdown_to_zotero_html(synthesis_md, f"Synthesis ({len(papers)} papers)")

        papers_meta = [
            {"key": p.key, "title": p.title, "authors": ", ".join(p.creators), "year": p.year or ""}
            for p in papers
        ]

        return CollectionSynthesisResponse(
            theme=research_theme or "General Thematic Literature Synthesis",
            num_papers_analyzed=len(papers),
            papers_analyzed=papers_meta,
            synthesis_matrix=[],
            thematic_summary=synthesis_md[:300] + "...",
            areas_of_consensus=["See synthesis document for comprehensive consensus points."],
            divergent_views_or_debates=["See synthesis document for debates and conflicts."],
            methodological_evolution="Detailed in synthesis markdown.",
            synthesis_markdown=synthesis_md,
            zotero_html_note=zotero_html
        )

    async def identify_research_gaps(
        self,
        papers: List[PaperItem],
        target_domain: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> ResearchGapResponse:
        """Analyze a collection to spot empirical, methodological, and theoretical gaps."""
        if not papers:
            raise ValueError("No papers provided for gap analysis.")

        active_model = model_override or self.model

        domain_prompt = f"Target Domain/Context: '{target_domain}'\n" if target_domain else ""
        papers_context = "\n---\n".join([self._build_paper_summary_text(p) for p in papers])

        system_instruction = (
            "You are a senior principal scientist identifying novel research opportunities and unexplored research gaps. "
            "You examine what existing literature collectively assumes, overlooks, or fails to rigorously test."
        )

        user_prompt = f"""
Conduct an academic Research Gap and Opportunity Analysis on the following {len(papers)} papers.
{domain_prompt}

Papers:
{papers_context}

Please structure your response in Markdown with:
1. **Executive Summary of the State of the Art**: What is already well-established.
2. **Identified Research Gaps**:
   - **Empirical Gaps**: Under-investigated populations, settings, datasets, or boundary conditions.
   - **Methodological Gaps**: Limitations of current tools, measurements, metrics, or study designs.
   - **Theoretical / Conceptual Gaps**: Incomplete models, untested mechanisms, or rival hypotheses.
3. **High-Impact Novel Research Questions**: 3-5 concrete, actionable research questions that would advance the field.
4. **Proposed Study Designs**: For each proposed question, outline a viable methodology (sample, variables, experimental/empirical strategy).
"""

        if self._is_openai_compatible():
            gaps_md = await self._generate_openai_compatible(
                model=active_model,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                temperature=0.4
            )
        else:
            gaps_md = await self._generate_gemini_content(
                model=active_model,
                contents=[user_prompt],
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.4,
                }
            )

        zotero_html = self._markdown_to_zotero_html(gaps_md, f"Research Gaps Analysis ({len(papers)} papers)")

        return ResearchGapResponse(
            analyzed_papers_count=len(papers),
            identified_gaps=[],
            novel_research_questions=[],
            markdown=gaps_md,
            zotero_html_note=zotero_html
        )

    async def chat_with_literature(
        self,
        papers: List[PaperItem],
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        model_override: Optional[str] = None
    ) -> LiteratureChatResponse:
        """Answer queries grounded in the selected literature corpus."""
        active_model = model_override or self.model

        corpus_text = "\n\n".join([
            f"Paper Key: {p.key}\nTitle: {p.title}\nAuthors: {', '.join(p.creators)}\nYear: {p.year or 'n.d.'}\nAbstract: {p.abstract_note}"
            for p in papers[:20]
        ])

        prompt = f"""
You are a knowledgeable literature assistant answering research questions based on the following library corpus:

{corpus_text}

User Question: {query}

Instructions:
- Provide an evidence-grounded answer citing the papers where appropriate (e.g. [Vaswani et al. 2017]).
- Be concise, direct, and academically rigorous.
"""

        if self._is_openai_compatible():
            answer = await self._generate_openai_compatible(
                model=active_model,
                system_instruction="",
                user_prompt=prompt,
                temperature=0.2
            )
        else:
            answer = await self._generate_gemini_content(
                model=active_model,
                contents=[prompt],
                config={
                    "temperature": 0.2,
                }
            )

        # Find cited papers by key
        cited_keys = [p.key for p in papers if p.key.lower() in answer.lower() or any(c.split()[0].lower() in answer.lower() for c in p.creators if c)]

        return LiteratureChatResponse(
            answer=answer,
            cited_paper_keys=cited_keys
        )

    async def review_work_document(
        self,
        title: str,
        text: str,
        pdf_bytes: Optional[bytes] = None,
        profile: str = "executive_bluf",
        custom_focus: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Perform tailored analysis of an uploaded work document based on the requested profile:
        - executive_bluf: Decision brief with Bottom Line Up Front, impacts, and recommendations.
        - red_team: Critical adversarial review exposing assumptions, vulnerabilities, and failure modes.
        - policy_compliance: Regulatory, policy, and mandate alignment.
        - technical_critique: Methodological and architectural deep-dive.
        """
        active_model = model_override or self.model

        profile_prompts = {
            "executive_bluf": """
You are a senior executive advisor and intelligence analyst producing a high-level Decision Brief.
Format your review with clear Markdown headers:
# Executive Briefing & Decision Memo: {title}

## 1. Bottom Line Up Front (BLUF)
A direct, authoritative 2-3 sentence executive synthesis of the core message, primary conclusion, and necessary action.

## 2. Strategic Context & Objective
Why this document was written, what critical problem or mandate it addresses, and its operational scope.

## 3. Key Findings & Essential Facts
Bulleted list of high-impact discoveries, verified data points, or milestone findings.

## 4. Actionable Recommendations & Decisions Required
Specific, prioritized recommendations for leadership. Clearly designate who needs to decide what.

## 5. Operational, Budget & Resource Impacts
Projected implications for workforce, technical systems, timelines, and financial investment.

## 6. Risk Assessment & Key Assumptions
Major assumptions underpinning the document, potential failure points, and suggested mitigation controls.
""",
            "red_team": """
You are an adversarial Red Team analyst and rigorous critical evaluator. Your role is to stress-test this document, uncover blind spots, and challenge conclusions.
Format your review with clear Markdown headers:
# Red Team / Critical Vulnerability Analysis: {title}

## 1. Executive Challenge & Core Vulnerabilities
Summary of the 3 most significant weaknesses, flaws in logic, or unexamined risks in this document.

## 2. Unstated Assumptions & Implicit Biases
Assumptions the authors rely on without empirical validation or justification.

## 3. Evidential & Methodological Vulnerabilities
Questionable data sources, cherry-picked findings, measurement limitations, or lack of counter-evidence.

## 4. Operational & Implementation Failure Modes
Where this plan, policy, or technical proposal is most likely to fail in real-world conditions.

## 5. Competing Hypotheses & Adversarial Perspectives
Strongest counter-arguments or alternative interpretations that the document fails to address.

## 6. Stress-Testing & Hardening Recommendations
Concrete recommendations to remediate these vulnerabilities and harden the proposal.
""",
            "policy_compliance": """
You are a senior policy and compliance analyst evaluating institutional alignment, regulatory governance, and standard adherence.
Format your review with clear Markdown headers:
# Policy & Governance Review: {title}

## 1. Governance Overview & Policy Alignment
Summary of relevant mandates, standards, legal frameworks, or operational doctrines applicable to this document.

## 2. Compliance Evaluation Matrix
- Fully Compliant Areas
- Partially Addressed / Ambiguous Areas
- Non-Compliant Gaps or Unaddressed Requirements

## 3. Accountability & Procedural Oversight
Reporting mechanisms, audit trails, chain-of-custody, and supervisory responsibilities.

## 4. Compliance Remediation Checklist
Actionable steps required to achieve complete regulatory and institutional alignment.
""",
            "technical_critique": """
You are a distinguished technical reviewer and principal research scientist.
Format your review with clear Markdown headers:
# Technical & Architectural Critique: {title}

## 1. Technical Summary & System Architecture
High-level architectural overview, technical methodology, or experimental setup.

## 2. Technical Rigor & Empirical Evidence
Evaluation of data integrity, mathematical/algorithmic soundness, and validation criteria.

## 3. Constraints, Scalability & Bottlenecks
Technical limits, compute/bandwidth requirements, latency, edge-case vulnerability, or throughput constraints.

## 4. Engineering & Research Recommendations
Concrete technical modifications to optimize efficiency, security, reliability, or scientific validity.
"""
        }

        template = profile_prompts.get(profile, profile_prompts["executive_bluf"]).format(title=title)

        focus_instruction = f"\n\nSpecial User Focus / Priority Area:\n{custom_focus}" if custom_focus else ""

        system_instruction = f"""
You are an expert document analyst operating within GResearch.
Analyze the provided work document thoroughly and produce an academically and professionally rigorous report.
Maintain objective, evidence-based language and cite specific sections or page contents where available.
{template}
{focus_instruction}
"""

        user_prompt = f"Document Title: {title}\n\nDocument Full Text Excerpt:\n{text[:60000]}"

        if self._is_openai_compatible():
            review_md = await self._generate_openai_compatible(
                model=active_model,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                temperature=0.2
            )
        else:
            contents: List[Any] = []
            if pdf_bytes:
                from google.genai import types
                logger.info(f"Passing raw PDF bytes ({len(pdf_bytes)} bytes) to Gemini for work document review.")
                contents.append(
                    types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type="application/pdf"
                    )
                )
            contents.append(user_prompt)

            review_md = await self._generate_gemini_content(
                model=active_model,
                contents=contents,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.2,
                }
            )

        zotero_html = self._markdown_to_zotero_html(review_md, title)
        return review_md, zotero_html

    async def chat_with_work_documents(
        self,
        documents: List[Dict[str, str]],
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        model_override: Optional[str] = None
    ) -> str:
        """
        Answer questions grounded in one or more uploaded work documents.
        """
        active_model = model_override or self.model

        corpus_text = "\n\n===\n\n".join([
            f"Document Title: {doc.get('title', 'Untitled')}\nFilename: {doc.get('filename', '')}\nContent:\n{doc.get('text', '')[:30000]}"
            for doc in documents[:5]
        ])

        system_instruction = """
You are an expert analytical research assistant answering questions about the user's uploaded work documents.
- Rely strictly on facts stated in the provided document corpus.
- If information is not in the documents, state so clearly.
- Cite specific document titles, sections, or numbers when quoting evidence.
"""

        prompt = f"""
Uploaded Document Corpus:
{corpus_text}

User Question: {query}
"""

        if self._is_openai_compatible():
            answer = await self._generate_openai_compatible(
                model=active_model,
                system_instruction=system_instruction,
                user_prompt=prompt,
                temperature=0.2
            )
        else:
            answer = await self._generate_gemini_content(
                model=active_model,
                contents=[prompt],
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.2,
                }
            )

        return answer

