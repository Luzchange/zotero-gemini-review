import logging
from typing import List, Dict, Any, Optional, Tuple
import httpx
from app.schemas.schemas import PaperItem, CollectionItem

logger = logging.getLogger(__name__)

class ZoteroService:
    """Client for interacting with the Zotero Web API v3."""

    BASE_URL = "https://api.zotero.org"

    def __init__(self, api_key: str, user_id: str, library_type: str = "user"):
        self.api_key = api_key.strip() if api_key else ""
        self.user_id = user_id.strip() if user_id else ""
        self.library_type = library_type.lower().strip() if library_type else "user"
        
        prefix = "users" if self.library_type == "user" else "groups"
        self.library_url = f"{self.BASE_URL}/{prefix}/{self.user_id}"
        
        self.headers = {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
            "User-Agent": "GResearch/1.0",
        }

    async def test_connection(self) -> Dict[str, Any]:
        """Verify API key and user ID by pinging the collections endpoint."""
        if not self.api_key or not self.user_id:
            return {
                "connected": False,
                "message": "Zotero API Key and User ID are required. Please configure them in .env or the dashboard."
            }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"{self.library_url}/collections",
                    headers=self.headers,
                    params={"limit": 1}
                )
                if resp.status_code == 200:
                    total_results = int(resp.headers.get("Total-Results", 0))
                    return {
                        "connected": True,
                        "library_type": self.library_type,
                        "user_id": self.user_id,
                        "total_collections": total_results,
                        "message": "Successfully connected to Zotero API."
                    }
                elif resp.status_code == 403:
                    return {
                        "connected": False,
                        "message": "Zotero Authentication failed (403 Forbidden). Verify your API key has library read/write permissions."
                    }
                elif resp.status_code == 404:
                    return {
                        "connected": False,
                        "message": f"Zotero library not found (404). Verify your {self.library_type.capitalize()} ID: '{self.user_id}'."
                    }
                else:
                    return {
                        "connected": False,
                        "message": f"Zotero API error: {resp.status_code} - {resp.text}"
                    }
            except Exception as e:
                logger.error(f"Error testing Zotero connection: {e}")
                return {
                    "connected": False,
                    "message": f"Network error connecting to Zotero API: {str(e)}"
                }

    async def get_collections(self) -> List[CollectionItem]:
        """Fetch all collections belonging to the user/group."""
        collections: List[CollectionItem] = []
        start = 0
        limit = 100

        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                resp = await client.get(
                    f"{self.library_url}/collections",
                    headers=self.headers,
                    params={"limit": limit, "start": start, "sort": "title"}
                )
                if resp.status_code != 200:
                    logger.error(f"Failed to fetch collections: {resp.status_code} {resp.text}")
                    break

                data = resp.json()
                if not data:
                    break

                for item in data:
                    c_data = item.get("data", {})
                    meta = item.get("meta", {})
                    collections.append(
                        CollectionItem(
                            key=c_data.get("key", ""),
                            version=c_data.get("version", 0),
                            name=c_data.get("name", "Unnamed Collection"),
                            parent_collection=c_data.get("parentCollection") or None,
                            num_items=meta.get("numItems", 0),
                        )
                    )

                total_results = int(resp.headers.get("Total-Results", len(collections)))
                start += len(data)
                if start >= total_results:
                    break

        return collections

    async def get_items(
        self,
        collection_key: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50,
        start: int = 0
    ) -> Tuple[List[PaperItem], int]:
        """
        Fetch primary paper items (excluding standalone notes and attachments).
        If collection_key is specified, retrieves items in that collection.
        """
        url = f"{self.library_url}/collections/{collection_key}/items/top" if collection_key else f"{self.library_url}/items/top"
        
        params: Dict[str, Any] = {
            "limit": limit,
            "start": start,
            "sort": "dateModified",
            "direction": "desc"
        }
        if query:
            params["q"] = query

        papers: List[PaperItem] = []
        total_count = 0

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code != 200:
                logger.error(f"Failed to fetch items from {url}: {resp.status_code} {resp.text}")
                return [], 0

            total_count = int(resp.headers.get("Total-Results", 0))
            items_data = resp.json()

            for item in items_data:
                data = item.get("data", {})
                meta = item.get("meta", {})

                # Skip any standalone notes or attachments if present
                if data.get("itemType") in ["attachment", "note"]:
                    continue

                # Extract creators/authors
                creators_raw = data.get("creators", [])
                creator_names = []
                for c in creators_raw:
                    if c.get("name"):
                        creator_names.append(c["name"])
                    elif c.get("lastName"):
                        first = c.get("firstName", "")
                        creator_names.append(f"{c['lastName']}, {first}".strip(", "))
                    else:
                        creator_names.append("Unknown")

                # Extract date/year
                date_str = data.get("date", "")
                year = ""
                if date_str:
                    # Match 4 consecutive digits
                    import re
                    year_match = re.search(r"\b(19\d\d|20\d\d)\b", date_str)
                    if year_match:
                        year = year_match.group(1)

                tags = [t.get("tag") for t in data.get("tags", []) if t.get("tag")]
                has_pdf = meta.get("numChildren", 0) > 0  # Likely has attachment child

                papers.append(
                    PaperItem(
                        key=data.get("key", ""),
                        version=data.get("version", 0),
                        item_type=data.get("itemType", "journalArticle"),
                        title=data.get("title", "Untitled"),
                        creators=creator_names,
                        abstract_note=data.get("abstractNote", ""),
                        publication_title=data.get("publicationTitle") or data.get("bookTitle") or data.get("proceedingsTitle") or "",
                        date=date_str,
                        year=year,
                        doi=data.get("DOI", ""),
                        url=data.get("url", ""),
                        tags=tags,
                        collections=data.get("collections", []),
                        has_pdf=has_pdf
                    )
                )

        return papers, total_count

    async def get_item(self, item_key: str) -> Optional[PaperItem]:
        """Fetch details of a single item and check for attached PDF."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.library_url}/items/{item_key}",
                headers=self.headers
            )
            if resp.status_code != 200:
                return None

            item = resp.json()
            data = item.get("data", {})

            creators_raw = data.get("creators", [])
            creator_names = []
            for c in creators_raw:
                if c.get("name"):
                    creator_names.append(c["name"])
                elif c.get("lastName"):
                    creator_names.append(f"{c['lastName']}, {c.get('firstName', '')}".strip(", "))

            import re
            date_str = data.get("date", "")
            year_match = re.search(r"\b(19\d\d|20\d\d)\b", date_str) if date_str else None
            year = year_match.group(1) if year_match else ""

            # Check child attachments for PDF
            pdf_key = await self.find_pdf_attachment_key(item_key, client)

            return PaperItem(
                key=data.get("key", ""),
                version=data.get("version", 0),
                item_type=data.get("itemType", "journalArticle"),
                title=data.get("title", "Untitled"),
                creators=creator_names,
                abstract_note=data.get("abstractNote", ""),
                publication_title=data.get("publicationTitle") or data.get("bookTitle") or "",
                date=date_str,
                year=year,
                doi=data.get("DOI", ""),
                url=data.get("url", ""),
                tags=[t.get("tag") for t in data.get("tags", []) if t.get("tag")],
                collections=data.get("collections", []),
                has_pdf=pdf_key is not None,
                pdf_attachment_key=pdf_key
            )

    async def find_pdf_attachment_key(self, item_key: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
        """Find the child attachment key corresponding to an application/pdf file."""
        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            should_close = True

        try:
            resp = await client.get(
                f"{self.library_url}/items/{item_key}/children",
                headers=self.headers
            )
            if resp.status_code != 200:
                return None

            children = resp.json()
            for child in children:
                c_data = child.get("data", {})
                if c_data.get("itemType") == "attachment":
                    content_type = c_data.get("contentType", "")
                    filename = c_data.get("filename", "").lower()
                    if content_type == "application/pdf" or filename.endswith(".pdf"):
                        return c_data.get("key")
            return None
        finally:
            if should_close:
                await client.aclose()

    async def download_attachment_pdf(self, attachment_key: str) -> Optional[bytes]:
        """
        Download PDF binary from Zotero storage if available.
        Returns None if not stored on Zotero Web Storage.
        """
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{self.library_url}/items/{attachment_key}/file",
                headers=self.headers
            )
            if resp.status_code == 200 and len(resp.content) > 100:
                return resp.content
            logger.info(f"Could not download attachment {attachment_key} from Zotero: status {resp.status_code}")
            return None

    async def create_child_note(self, parent_item_key: str, note_html: str, tags: Optional[List[str]] = None) -> Tuple[bool, Optional[str], str]:
        """
        Save a review note directly as a child note under parent_item_key.
        """
        tag_objects = [{"tag": t} for t in (tags or ["gemini-reviewed", "literature-review"])]
        payload = [
            {
                "itemType": "note",
                "parentItem": parent_item_key,
                "note": note_html,
                "tags": tag_objects
            }
        ]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.library_url}/items",
                headers=self.headers,
                json=payload
            )
            if resp.status_code in (200, 201):
                res_data = resp.json()
                successful = res_data.get("successful", {})
                if successful:
                    created_key = list(successful.values())[0].get("key")
                    return True, created_key, "Note created successfully in Zotero."
                return True, None, "Note saved, but key was not returned."
            else:
                return False, None, f"Zotero API error creating note: {resp.status_code} - {resp.text}"

    async def add_tags_to_item(self, item_key: str, tags: List[str]) -> bool:
        """Add tags to an existing item."""
        if not tags:
            return True

        tag_objects = [{"tag": t} for t in tags]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.library_url}/items/{item_key}/tags",
                headers=self.headers,
                json=tag_objects
            )
            return resp.status_code in (200, 201, 204)

    async def create_document_item(
        self,
        title: str,
        abstract_note: str = "",
        collection_key: Optional[str] = None,
        creators: Optional[List[str]] = None,
        tags: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str], str]:
        """
        Create a new document/report item in the user's Zotero library.
        Returns (success, item_key, message).
        """
        creator_objs = []
        if creators:
            for c in creators:
                creator_objs.append({"creatorType": "author", "name": c})
        else:
            creator_objs.append({"creatorType": "author", "name": "Work Document / Report"})

        tag_objs = [{"tag": t} for t in (tags or ["work-document", "gemini-reviewed"])]

        item_data: Dict[str, Any] = {
            "itemType": "report",
            "title": title or "Untitled Work Document",
            "creators": creator_objs,
            "abstractNote": abstract_note[:2000] if abstract_note else "",
            "tags": tag_objs
        }
        if collection_key:
            item_data["collections"] = [collection_key]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.library_url}/items",
                headers=self.headers,
                json=[item_data]
            )
            if resp.status_code in (200, 201):
                res_data = resp.json()
                successful = res_data.get("successful", {})
                if successful:
                    created_key = list(successful.values())[0].get("key")
                    return True, created_key, "Document item created in Zotero."
                return True, None, "Document saved in Zotero, but key not returned."
            else:
                return False, None, f"Zotero API error creating item: {resp.status_code} - {resp.text}"

    async def create_journal_article_item(
        self,
        title: str,
        creators: Optional[List[str]] = None,
        journal: Optional[str] = None,
        publication_year: Optional[str] = None,
        doi: Optional[str] = None,
        url: Optional[str] = None,
        pmid: Optional[str] = None,
        abstract_note: Optional[str] = None,
        collection_key: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str], str]:
        """
        Creates a journalArticle bibliographic item in Zotero for PubMed or JSTOR entries.
        Returns (success, item_key, message).
        """
        creator_objs = []
        if creators:
            for c in creators:
                parts = c.split(" ", 1)
                if len(parts) == 2:
                    creator_objs.append({"creatorType": "author", "firstName": parts[0], "lastName": parts[1]})
                else:
                    creator_objs.append({"creatorType": "author", "name": c})
        else:
            creator_objs.append({"creatorType": "author", "name": "Unknown Author"})

        tag_objs = [{"tag": t} for t in (tags or ["literature-search"])]

        extra_parts = []
        if pmid:
            extra_parts.append(f"PMID: {pmid}")
        if doi:
            extra_parts.append(f"DOI: {doi}")

        item_data: Dict[str, Any] = {
            "itemType": "journalArticle",
            "title": title or "Untitled Article",
            "creators": creator_objs,
            "publicationTitle": journal or "",
            "date": publication_year or "",
            "DOI": doi or "",
            "url": url or "",
            "extra": "\n".join(extra_parts),
            "abstractNote": (abstract_note[:3000] if abstract_note else ""),
            "tags": tag_objs
        }
        if collection_key:
            item_data["collections"] = [collection_key]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.library_url}/items",
                headers=self.headers,
                json=[item_data]
            )
            if resp.status_code in (200, 201):
                res_data = resp.json()
                successful = res_data.get("successful", {})
                if successful:
                    created_key = list(successful.values())[0].get("key")
                    return True, created_key, "Journal article created in Zotero."
                return True, None, "Saved in Zotero, but key was not returned."
            else:
                return False, None, f"Zotero API error creating journal article: {resp.status_code} - {resp.text}"


