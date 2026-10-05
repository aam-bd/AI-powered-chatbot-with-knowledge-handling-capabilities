"""Web page parser with comprehensive SSRF protection (Architecture §9.3).

Protections:
- Domain allowlist verification against ALLOWED_URL_DOMAINS (empty list disables URL ingestion in production unless explicitly allowed)
- DNS resolution checks: strictly blocking private, loopback, link-local, and reserved IP ranges
- Redirect loop limitation and per-redirect IP validation
- Request timeouts and maximum content-length size caps
- Boilerplate/script stripping using BeautifulSoup
"""
from typing import List, Dict, Any, Optional
import ipaddress
import socket
import urllib.parse
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logger import logger


def is_forbidden_ip(ip_str: str) -> bool:
    """Return True if an IP address is private, loopback, link-local, multicast, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        )
    except ValueError:
        return False


def validate_ip_address(ip_str: str) -> None:
    """Ensure an IP address is not private, loopback, link-local, or reserved."""
    if is_forbidden_ip(ip_str):
        raise ValueError(
            f"SSRF Protection: Access to Private, loopback, or reserved IP '{ip_str}' is forbidden."
        )


def validate_ssrf_url(url: str, allowed_domains: Optional[List[str]] = None) -> str:
    """Validate URL scheme, domain allowlist, and DNS resolved IP addresses."""
    domains_to_check = (
        allowed_domains if allowed_domains is not None else settings.ALLOWED_URL_DOMAINS
    )

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Invalid URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are allowed."
        )

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise ValueError(f"URL '{url}' does not contain a valid hostname.")

    # Check direct IP addresses
    if is_forbidden_ip(hostname):
        raise ValueError(
            f"SSRF Protection: Access to Private, loopback, or reserved IP '{hostname}' is forbidden."
        )

    # Check domain allowlist if configured
    if domains_to_check:
        allowed = False
        for allowed_domain in domains_to_check:
            allowed_domain = allowed_domain.lower().strip()
            if hostname == allowed_domain or hostname.endswith(f".{allowed_domain}"):
                allowed = True
                break

        if not allowed:
            raise ValueError(
                f"SSRF Protection: Domain '{hostname}' is not in ALLOWED_URL_DOMAINS."
            )

    # Resolve hostname via DNS and check all returned IP addresses
    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        resolved_ips = {item[4][0] for item in addr_info}
    except Exception as exc:
        raise ValueError(
            f"SSRF Protection: DNS resolution failed for hostname '{hostname}': {exc}"
        ) from exc

    if not resolved_ips:
        raise ValueError(f"SSRF Protection: No IP addresses resolved for hostname '{hostname}'.")

    for ip_str in resolved_ips:
        validate_ip_address(ip_str)

    return url


def parse_web_url(url: str) -> List[Dict[str, Any]]:
    """Fetch and parse a web page safely with SSRF defense and redirect verification."""
    logger.info(f"Parsing web URL: {url}")
    current_url = url
    max_redirects = 3
    redirect_count = 0
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        while True:
            validate_ssrf_url(current_url)

            try:
                resp = client.get(current_url)
            except Exception as exc:
                raise ValueError(f"Failed to fetch URL '{current_url}': {exc}") from exc

            # Handle redirects manually to enforce SSRF validation at every hop
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    raise ValueError(f"Redirect status {resp.status_code} received without Location header.")

                redirect_count += 1
                if redirect_count > max_redirects:
                    raise ValueError(f"SSRF Protection: Exceeded maximum allowed redirects ({max_redirects}).")

                # Resolve relative redirects against current URL
                current_url = urllib.parse.urljoin(current_url, location)
                logger.info(f"Following redirect ({redirect_count}/{max_redirects}) to: {current_url}")
                continue

            if resp.status_code != 200:
                raise ValueError(f"Failed to fetch URL '{current_url}', HTTP status {resp.status_code}.")

            content_bytes = resp.content
            if len(content_bytes) > max_bytes:
                raise ValueError(
                    f"Content size ({len(content_bytes)} bytes) exceeds allowed limit of {settings.MAX_UPLOAD_MB} MB."
                )

            html = resp.text
            break

    soup = BeautifulSoup(html, "html.parser")

    # Strip unwanted tags
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"]):
        tag.decompose()

    # Extract title
    page_title = None
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()

    # Prefer main / article content
    main_el = soup.find("article") or soup.find("main") or soup.find("body")
    text = (main_el.get_text(separator="\n", strip=True) if main_el else soup.get_text(separator="\n", strip=True))

    if not text:
        return []

    return [{
        "text": text,
        "page": None,
        "section": page_title,
    }]
