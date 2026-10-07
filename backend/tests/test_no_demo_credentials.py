"""Security tests asserting zero demo, default, or prefilled credentials exist across repository.

Enforces architecture §9.1 and Phase 7b:
- No 'fill demo admin credentials' control or handler in frontend
- No default admin passwords in README or .env.example
- PASSWORD_MIN_LENGTH is at least 10
"""
from pathlib import Path
import pytest
from app.core.config import settings


def _find_repo_root() -> Path:
    """Find repository root whether running inside container (/repo) or on host."""
    repo_container = Path("/repo")
    if repo_container.exists() and (repo_container / "frontend").exists():
        return repo_container
    p = Path(__file__).resolve().parent
    # If in /app/tests, root is /app or the parent containing frontend/
    for parent in [p.parent, p.parent.parent]:
        if (parent / "frontend").exists() or (parent / "README.md").exists():
            return parent
    return Path("/app")


def test_no_demo_credentials_in_login_form():
    """Assert LoginForm contains no demo filler button or hardcoded credentials."""
    repo_root = _find_repo_root()
    login_form_path = repo_root / "frontend" / "src" / "components" / "LoginForm.tsx"
    
    # In container without mounted frontend, check if path exists
    if not login_form_path.exists():
        # Fallback to host relative path check
        login_form_path = Path("/app/../frontend/src/components/LoginForm.tsx")
    
    if login_form_path.exists():
        content = login_form_path.read_text(encoding="utf-8")
        assert "handleFillDemoAdmin" not in content, "Found handleFillDemoAdmin in LoginForm.tsx"
        assert "Fill Demo Admin Credentials" not in content, "Found 'Fill Demo Admin Credentials' in LoginForm.tsx"
        assert "AdminPassword123!" not in content, "Found hardcoded demo password in LoginForm.tsx"
        assert "admin@example.com" not in content, "Found hardcoded demo email in LoginForm.tsx"


def test_no_default_credentials_in_readme():
    """Assert README does not expose default passwords or default admin logins."""
    repo_root = _find_repo_root()
    readme_path = repo_root / "README.md"
    if not readme_path.exists():
        readme_path = Path("/app/../README.md")
        
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
        assert "Admin123!@#" not in content, "Found default password Admin123!@# in README.md"
        assert "Default credentials:" not in content, "Found 'Default credentials:' section in README.md"


def test_no_default_password_in_env_example():
    """Assert .env.example contains only non-functional placeholders."""
    repo_root = _find_repo_root()
    env_example_path = repo_root / ".env.example"
    if not env_example_path.exists():
        env_example_path = Path("/app/../.env.example")
        
    if env_example_path.exists():
        content = env_example_path.read_text(encoding="utf-8")
        assert "adminsecurepassword123" not in content, "Found concrete password in .env.example"
        assert "replace_with_strong_password_min_10_chars" in content, "Missing password placeholder in .env.example"


def test_password_policy_minimum_length_configured():
    """Assert PASSWORD_MIN_LENGTH is at least 10 in configuration."""
    assert settings.PASSWORD_MIN_LENGTH >= 10, f"PASSWORD_MIN_LENGTH must be >= 10, got {settings.PASSWORD_MIN_LENGTH}"
