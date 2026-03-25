"""
Web Skills - Search the web and fetch/parse web pages.

Provides:
- web_fetch: Fetch a URL and extract clean, readable content
- web_search: Search the web using DuckDuckGo (no API key needed)
"""

import re
import json
import httpx
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urljoin, quote_plus
from loguru import logger

from ..base import BaseSkill

# Try to import BeautifulSoup
try:
    from bs4 import BeautifulSoup, Comment
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("beautifulsoup4 not installed - web_fetch will return raw HTML")


class WebFetchSkill(BaseSkill):
    """Fetch and parse web pages - like Claude Code's WebFetch tool."""

    name = "web_fetch"
    description = """Fetch a web page and extract its content as clean, readable text.
- Automatically converts HTML to readable text (removes scripts, styles, ads)
- Extracts metadata (title, description, author)
- Handles JSON responses natively
- Follows redirects automatically
- Use 'selector' param to extract specific elements (CSS selector)

Examples:
- web_fetch(url="https://example.com") - get full page content
- web_fetch(url="https://api.example.com/data") - fetch JSON API
- web_fetch(url="https://docs.example.com", selector="article") - extract article only"""
    version = "2.0.0"

    # Elements to remove from HTML (noise)
    REMOVE_TAGS = [
        'script', 'style', 'noscript', 'iframe', 'svg', 'canvas',
        'nav', 'footer', 'aside', 'header', 'form', 'button',
        'advertisement', 'ads', 'ad-container'
    ]

    # Classes/IDs that typically contain ads or noise
    NOISE_PATTERNS = [
        r'ad[s]?[-_]?', r'advertisement', r'banner', r'sidebar',
        r'comment', r'share', r'social', r'related', r'recommend',
        r'newsletter', r'subscribe', r'popup', r'modal', r'cookie'
    ]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.timeout = 30
        self.max_content_length = 100000  # 100KB max

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                },
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector to extract specific elements (e.g., 'article', 'main', '.content')"
                },
                "include_links": {
                    "type": "boolean",
                    "description": "Include links in markdown format (default: false)",
                    "default": False
                },
                "raw": {
                    "type": "boolean",
                    "description": "Return raw HTML without parsing (default: false)",
                    "default": False
                }
            },
            "required": ["url"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch and parse a web page."""
        url = params.get('url', '').strip()
        selector = params.get('selector')
        include_links = params.get('include_links', False)
        raw = params.get('raw', False)

        if not url:
            return {"success": False, "error": "No URL provided"}

        # Validate URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return {"success": False, "error": f"Invalid URL: {url}"}
        except Exception:
            return {"success": False, "error": f"Invalid URL: {url}"}

        try:
            logger.info(f"Fetching URL: {url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                final_url = str(response.url)
                content_type = response.headers.get('content-type', '').lower()

                # Check for redirect to different host
                original_host = urlparse(url).netloc
                final_host = urlparse(final_url).netloc
                if original_host != final_host:
                    logger.info(f"Redirected to different host: {final_url}")

                # Handle JSON responses
                if 'application/json' in content_type:
                    try:
                        json_data = response.json()
                        return {
                            "success": True,
                            "result": {
                                "type": "json",
                                "data": json_data,
                                "url": final_url
                            }
                        }
                    except json.JSONDecodeError:
                        pass

                # Reject binary content (PDF, images, archives, etc.)
                binary_types = [
                    'application/pdf', 'application/zip', 'application/gzip',
                    'application/octet-stream', 'application/msword',
                    'application/vnd.', 'image/', 'audio/', 'video/',
                    'font/', 'application/x-tar', 'application/x-rar',
                ]
                if any(bt in content_type for bt in binary_types):
                    # Guess type from URL if content-type is generic
                    ext = url.rsplit('.', 1)[-1].lower() if '.' in url.split('/')[-1] else ''
                    return {
                        "success": False,
                        "error": f"Binary content detected ({content_type}). Cannot extract text from {ext.upper() or 'binary'} files. Try a different URL."
                    }

                # Get text content
                text = response.text

                # Safety check: detect binary content that slipped through
                # (e.g., PDF served as text/html, or missing content-type)
                if text[:20].startswith('%PDF') or '\x00' in text[:1000]:
                    ext = url.rsplit('.', 1)[-1].lower() if '.' in url.split('/')[-1] else 'binary'
                    return {
                        "success": False,
                        "error": f"Binary content detected in response body ({ext.upper()} file). Cannot extract text. Try a different URL."
                    }

                # Return raw if requested or if BeautifulSoup not available
                if raw or not BS4_AVAILABLE:
                    return {
                        "success": True,
                        "result": {
                            "type": "raw",
                            "content": text[:self.max_content_length],
                            "url": final_url,
                            "truncated": len(text) > self.max_content_length
                        }
                    }

                # Parse HTML
                soup = BeautifulSoup(text, 'lxml' if 'lxml' in str(type(text)) else 'html.parser')

                # Extract metadata
                metadata = self._extract_metadata(soup, final_url)

                # If selector provided, extract only that element
                if selector:
                    elements = soup.select(selector)
                    if not elements:
                        return {
                            "success": False,
                            "error": f"No elements found matching selector: {selector}",
                            "url": final_url
                        }
                    # Create new soup with just selected elements
                    soup = BeautifulSoup('<div></div>', 'html.parser')
                    container = soup.div
                    for el in elements:
                        container.append(el)

                # Clean and extract text
                content = self._extract_content(soup, include_links, final_url)

                # Truncate if too long
                truncated = len(content) > self.max_content_length
                if truncated:
                    content = content[:self.max_content_length] + "\n\n[Content truncated...]"

                logger.info(f"Fetched {len(content)} chars from {final_url}")

                return {
                    "success": True,
                    "result": {
                        "type": "html",
                        "title": metadata.get('title', ''),
                        "description": metadata.get('description', ''),
                        "content": content,
                        "url": final_url,
                        "truncated": truncated
                    }
                }

        except httpx.TimeoutException:
            return {"success": False, "error": f"Request timed out after {self.timeout}s"}
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"}
        except Exception as e:
            logger.error(f"Web fetch failed: {e}")
            return {"success": False, "error": f"Fetch failed: {str(e)}"}

    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, str]:
        """Extract page metadata."""
        metadata = {}

        # Title
        if soup.title:
            metadata['title'] = soup.title.get_text(strip=True)

        # Meta description
        desc_tag = soup.find('meta', attrs={'name': 'description'}) or \
                   soup.find('meta', attrs={'property': 'og:description'})
        if desc_tag and desc_tag.get('content'):
            metadata['description'] = desc_tag['content']

        # Author
        author_tag = soup.find('meta', attrs={'name': 'author'})
        if author_tag and author_tag.get('content'):
            metadata['author'] = author_tag['content']

        return metadata

    def _extract_content(self, soup: BeautifulSoup, include_links: bool, base_url: str) -> str:
        """Extract clean text content from HTML."""
        # Remove unwanted tags
        for tag in self.REMOVE_TAGS:
            for element in soup.find_all(tag):
                element.decompose()

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove elements with noisy classes/IDs
        for pattern in self.NOISE_PATTERNS:
            for element in soup.find_all(class_=re.compile(pattern, re.I)):
                element.decompose()
            for element in soup.find_all(id=re.compile(pattern, re.I)):
                element.decompose()

        # Try to find main content area
        main_content = soup.find('main') or soup.find('article') or \
                       soup.find(class_=re.compile(r'content|article|post|entry', re.I)) or \
                       soup.find('body') or soup

        # Convert to text
        if include_links:
            content = self._html_to_markdown(main_content, base_url)
        else:
            content = self._html_to_text(main_content)

        # Clean up whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' +', ' ', content)
        content = content.strip()

        return content

    def _html_to_text(self, soup) -> str:
        """Convert HTML to plain text."""
        # Get text with newlines for block elements
        text_parts = []

        for element in soup.descendants:
            if isinstance(element, str):
                text = element.strip()
                if text:
                    text_parts.append(text)
            elif element.name in ['p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr']:
                text_parts.append('\n')
            elif element.name in ['h1', 'h2', 'h3']:
                text_parts.append('\n\n')

        return ' '.join(text_parts)

    def _html_to_markdown(self, soup, base_url: str) -> str:
        """Convert HTML to markdown-like text with links."""
        result = []

        for element in soup.descendants:
            if isinstance(element, str):
                text = element.strip()
                if text:
                    result.append(text)
            elif element.name == 'a' and element.get('href'):
                href = element.get('href')
                if href.startswith('/'):
                    href = urljoin(base_url, href)
                text = element.get_text(strip=True)
                if text and href:
                    result.append(f'[{text}]({href})')
            elif element.name in ['h1']:
                result.append(f'\n\n# {element.get_text(strip=True)}\n')
            elif element.name in ['h2']:
                result.append(f'\n\n## {element.get_text(strip=True)}\n')
            elif element.name in ['h3']:
                result.append(f'\n\n### {element.get_text(strip=True)}\n')
            elif element.name == 'p':
                result.append('\n\n')
            elif element.name == 'br':
                result.append('\n')
            elif element.name == 'li':
                result.append('\n- ')

        return ''.join(result)


class WebSearchSkill(BaseSkill):
    """Search the web using DuckDuckGo - no API key needed."""

    name = "web_search"
    description = """Search the web for information using DuckDuckGo.
Returns search results with titles, URLs, and snippets.
No API key required.

Examples:
- web_search(query="python async tutorial")
- web_search(query="latest AI news", num_results=5)"""
    version = "2.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.timeout = 15

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 10, max: 20)",
                    "default": 10
                }
            },
            "required": ["query"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a web search using DuckDuckGo."""
        query = params.get('query', '').strip()
        num_results = min(params.get('num_results', 10), 20)

        if not query:
            return {"success": False, "error": "No search query provided"}

        try:
            logger.info(f"Searching: {query}")

            # DuckDuckGo HTML search (no API key needed)
            search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html',
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(search_url, headers=headers)
                response.raise_for_status()

                if not BS4_AVAILABLE:
                    return {
                        "success": False,
                        "error": "beautifulsoup4 not installed - cannot parse search results"
                    }

                soup = BeautifulSoup(response.text, 'html.parser')
                results = []

                # Parse DuckDuckGo HTML results
                for result in soup.select('.result'):
                    if len(results) >= num_results:
                        break

                    title_elem = result.select_one('.result__title a')
                    snippet_elem = result.select_one('.result__snippet')

                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        url = title_elem.get('href', '')

                        # DuckDuckGo wraps URLs, extract actual URL
                        if 'uddg=' in url:
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                            url = parsed.get('uddg', [url])[0]

                        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''

                        if title and url:
                            results.append({
                                'title': title,
                                'url': url,
                                'snippet': snippet
                            })

                if not results:
                    # Fallback: try alternative parsing
                    for link in soup.select('a.result__a'):
                        if len(results) >= num_results:
                            break
                        title = link.get_text(strip=True)
                        url = link.get('href', '')
                        if title and url and url.startswith('http'):
                            results.append({
                                'title': title,
                                'url': url,
                                'snippet': ''
                            })

                logger.info(f"Found {len(results)} results for '{query}'")

                return {
                    "success": True,
                    "result": {
                        "query": query,
                        "results": results,
                        "count": len(results)
                    }
                }

        except httpx.TimeoutException:
            return {"success": False, "error": "Search request timed out"}
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"success": False, "error": f"Search failed: {str(e)}"}
