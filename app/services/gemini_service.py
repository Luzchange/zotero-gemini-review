import json
import logging
from typing import List, Dict, Any, Optional
import markdown

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
    """Service handling literature analysis via Google Gemini API."""

    def __init__(self, api_key: str, default_model: str = "gemini-2.5-flash"):
        self.api_key = api_key.strip() if api_key else ""
        self.model = default_model or "gemini-2.5-flash"
        self._client = None

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
        client = self._get_client()
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

        try:
            response = client.models.generate_content(
                model=active_model,
                contents=contents,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.2,
                }
            )
            review_md = response.text or "No review generated."
        except Exception as e:
            logger.error(f"Gemini API error during single paper review: {e}")
            raise RuntimeError(f"Gemini API generation failed: {str(e)}")

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

        client = self._get_client()
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

        try:
            response = client.models.generate_content(
                model=active_model,
                contents=[user_prompt],
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.3,
                }
            )
            synthesis_md = response.text or "No synthesis generated."
        except Exception as e:
            logger.error(f"Gemini API error during synthesis: {e}")
            raise RuntimeError(f"Gemini API synthesis failed: {str(e)}")

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

        client = self._get_client()
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

        try:
            response = client.models.generate_content(
                model=active_model,
                contents=[user_prompt],
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.4,
                }
            )
            gaps_md = response.text or "No gap analysis generated."
        except Exception as e:
            logger.error(f"Gemini API error during gap analysis: {e}")
            raise RuntimeError(f"Gemini API gap analysis failed: {str(e)}")

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
        """Interactive Q&A answering questions grounded in the provided papers."""
        client = self._get_client()
        active_model = model_override or self.model

        papers_context = "\n---\n".join([self._build_paper_summary_text(p) for p in papers])

        history_context = ""
        if chat_history:
            for turn in chat_history[-6:]:  # Keep recent history
                role = turn.get("role", "user")
                content = turn.get("content", "")
                history_context += f"{role.upper()}: {content}\n"

        prompt = f"""
You are a research assistant answering questions strictly based on the researcher's Zotero library papers below.

LIBRARY PAPERS:
{papers_context}

PREVIOUS CONVERSATION:
{history_context}

RESEARCHER'S QUESTION:
{query}

Instructions:
- Provide an evidence-grounded answer based on the papers above.
- Cite the relevant papers explicitly using author and year (e.g., [Vaswani et al., 2017]).
- If the papers in the library do not contain enough information to answer, state clearly what is missing from the library.
- Be concise, direct, and academically rigorous.
"""

        try:
            response = client.models.generate_content(
                model=active_model,
                contents=[prompt],
                config={
                    "temperature": 0.2,
                }
            )
            answer = response.text or "No response generated."
        except Exception as e:
            logger.error(f"Gemini API error during literature chat: {e}")
            raise RuntimeError(f"Gemini API chat failed: {str(e)}")

        # Find cited papers by key
        cited_keys = [p.key for p in papers if p.key.lower() in answer.lower() or any(c.split()[0].lower() in answer.lower() for c in p.creators if c)]

        return LiteratureChatResponse(
            answer=answer,
            cited_paper_keys=cited_keys
        )
