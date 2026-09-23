import re
import logging
from typing import List, Optional, Dict, Any
import httpx
from app.schemas.schemas import ExternalArticle, LiteratureSearchResponse

logger = logging.getLogger("gresearch.jstor")

class JSTORService:
    """Service to search JSTOR literature and route access via institutional school credentials."""

    CROSSREF_API = "https://api.crossref.org/works"
    JSTOR_MEMBER_ID = "374"  # ITHAKA / JSTOR CrossRef Member ID
    JSTOR_INSTITUTION_LOGIN_URL = "https://www.jstor.org/institutionSearch"

    def __init__(self, proxy_prefix: Optional[str] = None):
        self.proxy_prefix = proxy_prefix.strip() if proxy_prefix else None

    def build_proxied_url(self, jstor_url: str) -> str:
        """
        Wraps a JSTOR article URL with the user's institutional/school proxy prefix.
        Examples of common proxy configurations:
        - Prefix style: 'https://proxy.lib.edu/login?url=' -> 'https://proxy.lib.edu/login?url=https://www.jstor.org/stable/12345'
        - Domain suffix style: '.proxy.lib.edu' -> 'https://www-jstor-org.proxy.lib.edu/stable/12345'
        """
        if not jstor_url:
            return ""

        if not self.proxy_prefix:
            return jstor_url

        prefix = self.proxy_prefix.strip()

        # Handle prefix that ends with = or /
        if prefix.endswith("=") or "login?url=" in prefix.lower():
            return f"{prefix}{jstor_url}"

        if prefix.startswith("http://") or prefix.startswith("https://"):
            if not prefix.endswith("/"):
                prefix += "/"
            # If it's something like https://ezproxy.school.edu/login?qurl=
            if "?" in prefix:
                return f"{prefix}{jstor_url}"
            return f"{prefix}login?url={jstor_url}"

        # If it's a hostname suffix like 'proxy.lib.school.edu'
        if "jstor.org" in jstor_url:
            # Replace www.jstor.org with www-jstor-org.<proxy>
            return re.sub(r'https?://(www\.)?jstor\.org', f"https://www-jstor-org.{prefix}", jstor_url)

        return jstor_url

    async def search(self, query: str, rows: int = 10) -> LiteratureSearchResponse:
        """Searches JSTOR publications via CrossRef index filtered for JSTOR / ITHAKA repository."""
        clean_query = query.strip()
        if not clean_query:
            return LiteratureSearchResponse(source="jstor", total_results=0, articles=[])

        params = {
            "query": clean_query,
            "filter": f"member:{self.JSTOR_MEMBER_ID}",
            "rows": str(min(max(rows, 1), 50)),
            "sort": "relevance"
        }

        headers = {
            "User-Agent": "GResearchLiteratureStudio/1.0 (mailto:support@gresearch.studio; academic research tool)"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.get(self.CROSSREF_API, params=params, headers=headers)
                res.raise_for_status()
                data = res.json().get("message", {})
            except Exception as e:
                logger.error(f"JSTOR/CrossRef search failed: {e}")
                return LiteratureSearchResponse(source="jstor", total_results=0, articles=[])

        total = data.get("total-results", 0)
        items = data.get("items", [])
        articles = []

        for item in items:
            try:
                titles = item.get("title", [])
                title = titles[0].strip() if titles else "Untitled"

                # Authors
                authors = []
                for a in item.get("author", []):
                    given = a.get("given", "").strip()
                    family = a.get("family", "").strip()
                    name = f"{given} {family}".strip() if given or family else a.get("name", "").strip()
                    if name:
                        authors.append(name)

                # Journal / Publication
                containers = item.get("container-title", [])
                journal = containers[0].strip() if containers else None

                # Publication Year
                pub_year = None
                date_parts = item.get("published-print", {}).get("date-parts") or item.get("created", {}).get("date-parts")
                if date_parts and len(date_parts) > 0 and len(date_parts[0]) > 0:
                    pub_year = str(date_parts[0][0])

                # DOI & URL
                doi = item.get("DOI", "").strip() if item.get("DOI") else None
                
                # Format clean JSTOR URL
                if doi and "10.2307" in doi:
                    doi_suffix = doi.split("10.2307/")[-1]
                    jstor_url = f"https://www.jstor.org/stable/{doi_suffix}"
                elif doi:
                    jstor_url = f"https://doi.org/{doi}"
                else:
                    jstor_url = item.get("URL", "")

                proxied_url = self.build_proxied_url(jstor_url)

                # Abstract clean-up (strip JATS tags if present)
                raw_abstract = item.get("abstract")
                abstract = None
                if raw_abstract:
                    clean_abs = re.sub(r'<[^>]+>', ' ', raw_abstract)
                    abstract = re.sub(r'\s+', ' ', clean_abs).strip()

                ext_id = f"jstor_{doi.replace('/', '_')}" if doi else f"jstor_{len(articles)}"

                articles.append(
                    ExternalArticle(
                        id=ext_id,
                        source="jstor",
                        title=title,
                        authors=authors,
                        journal=journal,
                        publication_year=pub_year,
                        abstract=abstract,
                        doi=doi,
                        pmid=None,
                        url=jstor_url,
                        proxied_url=proxied_url
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing JSTOR item: {e}")
                continue

        return LiteratureSearchResponse(
            source="jstor",
            total_results=total,
            articles=articles
        )
