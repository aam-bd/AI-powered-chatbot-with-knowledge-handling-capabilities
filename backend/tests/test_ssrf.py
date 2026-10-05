"""Unit and integration tests for SSRF protections on web URL ingestion."""
import pytest
from app.services.parsers.web import (
    validate_ssrf_url,
    is_forbidden_ip,
    parse_web_url,
)


def test_ssrf_blocks_loopback_ipv4():
    """Verify loopback IPv4 addresses are strictly blocked."""
    with pytest.raises(ValueError, match="Private, loopback, or reserved IP"):
        validate_ssrf_url("http://127.0.0.1:8000/secret")


def test_ssrf_blocks_loopback_ipv6():
    """Verify loopback IPv6 addresses are strictly blocked."""
    with pytest.raises(ValueError, match="Private, loopback, or reserved IP"):
        validate_ssrf_url("http://[::1]:8080/data")


def test_ssrf_blocks_private_subnets():
    """Verify private subnet IPs (10.x, 172.16.x, 192.168.x) are blocked."""
    for ip in ["10.0.0.1", "172.16.0.5", "192.168.1.100"]:
        with pytest.raises(ValueError, match="Private, loopback, or reserved IP"):
            validate_ssrf_url(f"http://{ip}/admin")


def test_ssrf_blocks_cloud_metadata_link_local():
    """Verify cloud provider metadata IP 169.254.169.254 is strictly blocked."""
    with pytest.raises(ValueError, match="Private, loopback, or reserved IP"):
        validate_ssrf_url("http://169.254.169.254/latest/meta-data")


def test_ssrf_blocks_non_http_schemes():
    """Verify non-HTTP/HTTPS schemes are rejected."""
    for bad_url in [
        "file:///etc/passwd",
        "ftp://ftp.example.com/file.txt",
        "gopher://gopher.example.com",
    ]:
        with pytest.raises(ValueError, match="Only HTTP and HTTPS"):
            validate_ssrf_url(bad_url)


def test_ssrf_domain_allowlist(monkeypatch):
    """Verify allowlist enforcement when domain allowlist is non-empty."""
    allowed = ["docs.example.com", "api.example.com"]

    # Mock DNS resolution to return a valid public IP
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )

    # Allowed domain
    validate_ssrf_url("https://docs.example.com/guide", allowed_domains=allowed)

    # Disallowed domain
    with pytest.raises(ValueError, match="is not in ALLOWED_URL_DOMAINS"):
        validate_ssrf_url("https://malicious.org/payload", allowed_domains=allowed)


def test_ssrf_is_forbidden_ip_helper():
    """Test is_forbidden_ip direct IP checking."""
    assert is_forbidden_ip("127.0.0.1") is True
    assert is_forbidden_ip("10.0.0.5") is True
    assert is_forbidden_ip("192.168.0.1") is True
    assert is_forbidden_ip("169.254.1.1") is True
    assert is_forbidden_ip("8.8.8.8") is False
    assert is_forbidden_ip("1.1.1.1") is False


def test_parse_web_url_blocks_ssrf_direct():
    """Verify parse_web_url raises ValueError on SSRF attempts."""
    with pytest.raises(ValueError):
        parse_web_url("http://127.0.0.1:9200/_cat/indices")
