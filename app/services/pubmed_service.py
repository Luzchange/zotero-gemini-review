import logging
from typing import List, Optional, Dict, Any
import xml.etree.ElementTree as ET
import httpx
from app.schemas.schemas import ExternalArticle, LiteratureSearchResponse

logger = logging.getLogger("gresearch.pubmed")

class PubMedService:
    """Service to search biomedical literature via NCBI Entrez E-Utilities."""

    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    async def search(self, query: str, retmax: int = 10) -> LiteratureSearchResponse:
        """Search PubMed articles by keyword, term, or author."""
        clean_query = query.strip()
        if not clean_query:
            return LiteratureSearchResponse(source="pubmed", total_results=0, articles=[])

        params = {
            "db": "pubmed",
            "term": clean_query,
            "retmode": "json",
            "retmax": str(min(max(retmax, 1), 50)),
            "sort": "relevance"
        }
        if self.api_key:
            params["api_key"] = self.api_key

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                search_res = await client.get(self.ESEARCH_URL, params=params)
                search_res.raise_for_status()
                data = search_res.json()
            except Exception as e:
                logger.error(f"PubMed search failed: {e}")
                return LiteratureSearchResponse(source="pubmed", total_results=0, articles=[])

        id_list = data.get("esearchresult", {}).get("idlist", [])
        total = int(data.get("esearchresult", {}).get("count", 0))

        if not id_list:
            return LiteratureSearchResponse(source="pubmed", total_results=total, articles=[])

        articles = await self.fetch_details(id_list)
        return LiteratureSearchResponse(
            source="pubmed",
            total_results=total,
            articles=articles
        )

    async def fetch_details(self, pmids: List[str]) -> List[ExternalArticle]:
        """Fetch rich article metadata and abstracts for given PMIDs using efetch XML."""
        if not pmids:
            return []

        articles = []
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml"
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.get(self.EFETCH_URL, params=params)
                if res.status_code == 200:
                    articles = self._parse_pubmed_xml(res.text)
        except Exception as e:
            logger.warning(f"PubMed XML fetch failed, trying JSON summary fallback: {e}")

        # If XML parsing didn't return all articles, fallback to esummary
        if not articles:
            articles = await self._fetch_summary_json(pmids)

        return articles

    def _parse_pubmed_xml(self, xml_content: str) -> List[ExternalArticle]:
        """Parses NCBI PubMedArticleSet XML into ExternalArticle schemas."""
        results = []
        try:
            root = ET.fromstring(xml_content)
        except Exception as e:
            logger.error(f"Failed to parse XML: {e}")
            return []

        for article_tag in root.findall(".//PubmedArticle"):
            try:
                medline = article_tag.find("MedlineCitation")
                if medline is None:
                    continue

                pmid_tag = medline.find("PMID")
                pmid = pmid_tag.text.strip() if pmid_tag is not None and pmid_tag.text else ""

                art = medline.find("Article")
                if art is None:
                    continue

                title_tag = art.find("ArticleTitle")
                title = "".join(title_tag.itertext()).strip() if title_tag is not None else "Untitled"

                # Journal & Date
                journal_tag = art.find(".//Journal/Title")
                journal = journal_tag.text.strip() if journal_tag is not None and journal_tag.text else None

                pub_year = None
                year_tag = art.find(".//JournalIssue/PubDate/Year")
                if year_tag is not None and year_tag.text:
                    pub_year = year_tag.text.strip()
                else:
                    medline_date = art.find(".//JournalIssue/PubDate/MedlineDate")
                    if medline_date is not None and medline_date.text:
                        pub_year = medline_date.text.strip()[:4]

                # Authors
                authors = []
                for author in art.findall(".//AuthorList/Author"):
                    last = author.find("LastName")
                    fore = author.find("ForeName")
                    if last is not None and last.text:
                        name = last.text.strip()
                        if fore is not None and fore.text:
                            name = f"{fore.text.strip()} {name}"
                        authors.append(name)
                    else:
                        collab = author.find("CollectiveName")
                        if collab is not None and collab.text:
                            authors.append(collab.text.strip())

                # Abstract
                abstract_parts = []
                for abs_text in art.findall(".//Abstract/AbstractText"):
                    label = abs_text.get("Label")
                    text = "".join(abs_text.itertext()).strip()
                    if label and text:
                        abstract_parts.append(f"{label}: {text}")
                    elif text:
                        abstract_parts.append(text)
                abstract = "\n\n".join(abstract_parts) if abstract_parts else None

                # DOI
                doi = None
                for article_id in article_tag.findall(".//PubmedData/ArticleIdList/ArticleId"):
                    if article_id.get("IdType") == "doi" and article_id.text:
                        doi = article_id.text.strip()
                        break

                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else None)

                results.append(
                    ExternalArticle(
                        id=f"pmid_{pmid}" if pmid else f"ext_{len(results)}",
                        source="pubmed",
                        title=title,
                        authors=authors,
                        journal=journal,
                        publication_year=pub_year,
                        abstract=abstract,
                        doi=doi,
                        pmid=pmid,
                        url=url,
                        proxied_url=url
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing article node: {e}")
                continue

        return results

    async def _fetch_summary_json(self, pmids: List[str]) -> List[ExternalArticle]:
        """Fallback to esummary JSON if XML fetch encounters an issue."""
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json"
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(self.ESUMMARY_URL, params=params)
                if res.status_code != 200:
                    return []
                data = res.json().get("result", {})
                
                results = []
                for pmid in pmids:
                    item = data.get(pmid)
                    if not item or not isinstance(item, dict):
                        continue
                    title = item.get("title", "").rstrip(".")
                    authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
                    journal = item.get("source")
                    pubdate = item.get("pubdate", "")
                    year = pubdate[:4] if pubdate else None
                    
                    doi = None
                    for aid in item.get("articleids", []):
                        if aid.get("idtype") == "doi":
                            doi = aid.get("value")

                    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                    results.append(
                        ExternalArticle(
                            id=f"pmid_{pmid}",
                            source="pubmed",
                            title=title,
                            authors=authors,
                            journal=journal,
                            publication_year=year,
                            abstract=None,
                            doi=doi,
                            pmid=pmid,
                            url=url,
                            proxied_url=url
                        )
                    )
                return results
        except Exception as e:
            logger.error(f"Fallback JSON summary failed: {e}")
            return []
