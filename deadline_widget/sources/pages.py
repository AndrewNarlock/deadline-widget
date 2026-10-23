"""pages.py - plain code (no model). Fetch course web pages and reduce them to plain text.

The text is untrusted. It only ever reaches Claude as data, and Claude's answers are validated.
"""

import requests
from bs4 import BeautifulSoup

DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "footer"]
BLOCK_TAGS = [
    "p", "div", "section", "article", "li", "ul", "ol", "dt", "dd", "tr", "table",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote",
]


def fetch_page(url: str) -> tuple[str, str]:
    """(title, text) of a web page. Raises requests.RequestException if it can't be fetched."""
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return page_text(response.text, fallback_title=url)


def page_text(html: str, fallback_title: str = "") -> tuple[str, str]:
    """(title, text) of an HTML page: the main content only, one line per block, words intact."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(DROP_TAGS):
        tag.decompose()
    body = soup.find("main") or soup.body or soup
    for br in body.find_all("br"):
        br.replace_with("\n")
    for cell in body.find_all(["td", "th"]):
        cell.append(" | ")
    for block in body.find_all(BLOCK_TAGS):
        block.append("\n")
    lines = (" ".join(line.split()).strip("| ") for line in body.get_text().splitlines())
    return title or fallback_title, "\n".join(line for line in lines if line)
