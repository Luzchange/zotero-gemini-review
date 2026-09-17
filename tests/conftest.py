import pytest
from app.schemas.schemas import PaperItem

@pytest.fixture
def sample_paper():
    return PaperItem(
        key="ITEM123",
        version=1,
        item_type="journalArticle",
        title="Attention Is All You Need",
        creators=["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"],
        abstract_note="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
        publication_title="NeurIPS 2017",
        date="2017-12-06",
        year="2017",
        doi="10.48550/arXiv.1706.03762",
        tags=["deep-learning", "transformers", "attention"],
        has_pdf=True,
        pdf_attachment_key="ATTACH999"
    )

@pytest.fixture
def sample_papers_list(sample_paper):
    paper2 = PaperItem(
        key="ITEM456",
        version=1,
        item_type="journalArticle",
        title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        creators=["Devlin, Jacob", "Chang, Ming-Wei"],
        abstract_note="We introduce a new language representation model called BERT...",
        publication_title="NAACL 2019",
        date="2019-06-02",
        year="2019",
        doi="10.18653/v1/N19-1423",
        tags=["nlp", "transformers", "pre-training"],
        has_pdf=False
    )
    return [sample_paper, paper2]
