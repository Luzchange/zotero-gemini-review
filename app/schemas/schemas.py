from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# -------------------------------------------------------------
# Zotero Schemas
# -------------------------------------------------------------

class ZoteroCreator(BaseModel):
    creator_type: str = "author"
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.last_name and self.first_name:
            return f"{self.last_name}, {self.first_name}"
        if self.last_name:
            return self.last_name
        return "Unknown Author"

class PaperItem(BaseModel):
    key: str
    version: int = 0
    item_type: str = "journalArticle"
    title: str = "Untitled"
    creators: List[str] = Field(default_factory=list)
    abstract_note: Optional[str] = ""
    publication_title: Optional[str] = ""
    date: Optional[str] = ""
    year: Optional[str] = ""
    doi: Optional[str] = ""
    url: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)
    collections: List[str] = Field(default_factory=list)
    has_pdf: bool = False
    pdf_attachment_key: Optional[str] = None

class CollectionItem(BaseModel):
    key: str
    version: int = 0
    name: str
    parent_collection: Optional[str] = None
    num_items: int = 0

class ZoteroStatusResponse(BaseModel):
    connected: bool
    library_type: str
    user_id: Optional[str] = None
    total_collections: int = 0
    message: str

# -------------------------------------------------------------
# Literature Review Request / Response Schemas
# -------------------------------------------------------------

class SinglePaperReviewRequest(BaseModel):
    item_key: str
    custom_focus: Optional[str] = Field(
        default=None,
        description="Optional custom focus, e.g., 'critique statistical power and validity threats' or 'extract ML model architectures'"
    )
    include_pdf: bool = Field(
        default=True,
        description="If True and a PDF attachment exists in Zotero, send the full PDF to Gemini"
    )
    model: Optional[str] = None

class SinglePaperReviewResponse(BaseModel):
    item_key: str
    title: str
    citation: str
    research_question: str
    theoretical_background: str
    methodology: str
    key_findings: List[str]
    limitations_and_critique: List[str]
    future_directions: List[str]
    key_quotes: List[str] = Field(default_factory=list)
    review_markdown: str
    zotero_html_note: str

class CollectionSynthesisRequest(BaseModel):
    item_keys: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of Zotero item keys. If omitted and collection_key is given, all papers in collection are synthesized."
    )
    collection_key: Optional[str] = Field(
        default=None,
        description="Optional Zotero collection key to fetch papers from"
    )
    research_theme: Optional[str] = Field(
        default=None,
        description="Specific question or theme to synthesize across the papers"
    )
    model: Optional[str] = None

class SynthesisMatrixRow(BaseModel):
    paper_key: str
    citation: str
    methodology: str
    key_findings: str
    perspective_or_stance: str

class CollectionSynthesisResponse(BaseModel):
    theme: str
    num_papers_analyzed: int
    papers_analyzed: List[Dict[str, str]]
    synthesis_matrix: List[SynthesisMatrixRow]
    thematic_summary: str
    areas_of_consensus: List[str]
    divergent_views_or_debates: List[str]
    methodological_evolution: str
    synthesis_markdown: str
    zotero_html_note: str

class ResearchGapRequest(BaseModel):
    item_keys: Optional[List[str]] = None
    collection_key: Optional[str] = None
    target_domain: Optional[str] = None
    model: Optional[str] = None

class IdentifiedGap(BaseModel):
    gap_title: str
    description: str
    affected_areas: str
    suggested_study_design: str

class ResearchGapResponse(BaseModel):
    analyzed_papers_count: int
    identified_gaps: List[IdentifiedGap]
    novel_research_questions: List[str]
    markdown: str
    zotero_html_note: str

class SaveNoteRequest(BaseModel):
    item_key: str
    note_html: str
    tags: List[str] = Field(default_factory=lambda: ["gemini-reviewed", "literature-review"])

class SaveNoteResponse(BaseModel):
    success: bool
    note_key: Optional[str] = None
    message: str

class LiteratureChatRequest(BaseModel):
    query: str
    item_keys: Optional[List[str]] = None
    collection_key: Optional[str] = None
    chat_history: Optional[List[Dict[str, str]]] = Field(default_factory=list)
    model: Optional[str] = None

class LiteratureChatResponse(BaseModel):
    answer: str
    cited_paper_keys: List[str] = Field(default_factory=list)
