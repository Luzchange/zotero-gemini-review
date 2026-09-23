import json
import logging
import io
from typing import List, Dict, Any, Optional
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
    """Service handling literature analysis via Google Gemini API and OpenAI-compatible gateways (e.g. GenAI.mil)."""

    def __init__(self, api_key: str, default_model: str = "gemini-3.6-flash", base_url: Optional[str] = None):
        self.api_key = api_key.strip() if api_key else ""
        self.model = default_model or "gemini-3.6-flash"
        self.base_url = base_url.strip() if base_url else ""
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

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }

        logger.info(f"Dispatching request to GenAI endpoint: {endpoint} (model: {model})")
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
        """Lazy load google-genai client."""
        if not self.api_key:
            raise ValueError("Gemini API Key is not set. Please provide it in .env or via X-Gemini-Key header.")
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize google-genai client: {e}")
                raise e
        return self._client

    async def list_available_models(self) -> List[Dict[str, Any]]:
        """List available models for this API key that support generateContent."""
        if self._is_openai_compatible():
            return [
                {"id": "gemini-2.5-flash", "display_name": "gemini-2.5-flash (GenAI.mil)"},
                {"id": "gemini-2.0-flash", "display_name": "gemini-2.0-flash"},
                {"id": "gemini-1.5-flash", "display_name": "gemini-1.5-flash"},
            ]

        try:
            client = self._get_client()
            models_pager = client.models.list()
            available = []
            for m in models_pager:
                model_id = m.name.replace("models/", "") if m.name else ""
                actions = getattr(m, "supported_actions", None) or []
                if not actions or "generateContent" in actions:
                    available.append({
                        "id": model_id,
                        "display_name": m.display_name or model_id,
                        "description": m.description or ""
                    })
            return available
        except Exception as e:
            logger.warning(f"Failed to list models from Gemini API: {e}")
            raise HTTPException(status_code=502, detail=f"Failed to fetch model list from Gemini: {str(e)}")

    async def _generate_gemini_content(
        self,
        model: str,
        contents: List[Any],
        config: Dict[str, Any]
    ) -> str:
        """Call client.models.generate_content with retry logic and fallback for 503 high demand spikes."""
        client = self._get_client()

        # Fallback cascade if primary model hits 503 high demand
        models_to_try = [model]
        for fallback in ("gemini-2.0-flash", "gemini-1.5-flash"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_error = None
        for candidate_model in models_to_try:
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
                    is_transient = (
                        "503" in err_str or 
                        "429" in err_str or 
                        "high demand" in err_str.lower() or 
                        "unavailable" in err_str.lower() or
                        "resourceexhausted" in err_str.lower()
                    )
                    if is_transient:
                        logger.warning(f"Model {candidate_model} busy/high demand ({e}), retrying in {attempt + 1.5}s...")
                        await asyncio.sleep(attempt + 1.5)
                        continue
                    else:
                        # Non-transient error (e.g. 400 invalid argument or 404 not found)
                        break

            logger.warning(f"Model {candidate_model} busy or unavailable, attempting fallback model if available...")

        logger.error(f"Gemini API generation failed after retries/fallbacks: {last_error}")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API generation failed: {str(last_error)}. If you are seeing 503 High Demand, try selecting gemini-2.0-flash or gemini-1.5-flash in Settings."
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
