"""
tests/test_ui.py

Unit and integration tests for Step 10: Simple Web UI.
Verifies HTML structure, CSS styling rules, JS interaction features,
and FastAPI static mounting without triggering full startup reindexing.
"""

import os
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from api.main import app

UI_DIR = Path(__file__).parent.parent / "ui"


@pytest.fixture
def client_without_startup():
    """Create a TestClient with startup scans mocked out for fast UI verification."""
    with patch("api.main.run_startup_scan"), patch("api.main.PeriodicScanScheduler.start"):
        with TestClient(app) as client:
            yield client


class TestStep10Deliverables:
    """Verifies all deliverables across Days 1, 2, and 3 of Step 10."""

    def test_ui_files_exist(self):
        """Verify index.html, style.css, and app.js exist in ui/ directory."""
        assert (UI_DIR / "index.html").exists(), "ui/index.html is missing"
        assert (UI_DIR / "style.css").exists(), "ui/style.css is missing"
        assert (UI_DIR / "app.js").exists(), "ui/app.js is missing"

    def test_day_1_chat_interface_and_session(self):
        """Verify basic chat UI elements and session_id persistence in localStorage."""
        html_content = (UI_DIR / "index.html").read_text(encoding="utf-8")
        js_content = (UI_DIR / "app.js").read_text(encoding="utf-8")

        # Check DOM elements
        assert 'id="chat-input"' in html_content, "Missing message input field #chat-input"
        assert 'id="send-btn"' in html_content, "Missing send button #send-btn"
        assert 'id="chat-messages"' in html_content, "Missing chat history container #chat-messages"

        # Check loading spinner in app.js
        assert "showTyping(" in js_content, "Missing showTyping() spinner function during API calls"
        assert "typing-indicator" in js_content, "Missing typing indicator CSS class reference in app.js"

        # Check session management and API endpoint call
        assert "localStorage.getItem('miro_conversations')" in js_content, "Missing localStorage check for conversations"
        assert "session_id: conv.id" in js_content, "Not sending session_id with /api/v1/ask requests"
        assert "/api/v1/ask" in js_content, "Not calling POST /api/v1/ask endpoint"

    def test_day_2_sources_confidence_and_ocr_warning(self):
        """Verify source citation display, confidence badge, and OCR warning indicators."""
        js_content = (UI_DIR / "app.js").read_text(encoding="utf-8")

        # Source display (collapsible <details> section below answer)
        assert "<details class=\"source-item\">" in js_content, "Missing collapsible source section (<details class='source-item'>)"
        assert "source-title" in js_content, "Missing source title class"
        assert "source-snippet" in js_content, "Missing source snippet display"
        assert "s.doc_type" in js_content, "Not checking source document type for icons"

        # Confidence badge indicator (green/yellow/red classes)
        assert "confidence-badge" in js_content, "Missing confidence-badge display logic"
        assert "confClass = 'high'" in js_content, "Missing high confidence styling assignment"
        assert "confClass = 'low'" in js_content, "Missing low confidence styling assignment"
        assert "confClass = 'medium'" in js_content, "Missing medium confidence styling assignment"

        # OCR warning indicator with tooltip
        assert "ocr_warning" in js_content, "Not reading ocr_warning flag from backend response"
        assert 'title="Avertissement OCR"' in js_content, "Missing OCR warning tooltip text"
        assert "fa-triangle-exclamation" in js_content, "Missing warning icon for OCR content"

    def test_day_3_user_selector_and_responsive_design(self):
        """Verify user selector for RBAC testing and responsive CSS styling."""
        html_content = (UI_DIR / "index.html").read_text(encoding="utf-8")
        js_content = (UI_DIR / "app.js").read_text(encoding="utf-8")
        css_content = (UI_DIR / "style.css").read_text(encoding="utf-8")

        # User selector dropdown
        assert 'id="user-selector"' in html_content, "Missing #user-selector dropdown in index.html"
        assert 'option value="2"' in html_content, "Missing Admin user option (uid=2)"
        assert 'option value="5"' in html_content, "Missing Vendeur user option (uid=5)"

        # JS sending different uid with each request
        assert "document.getElementById('user-selector')?.value" in js_content, "JS does not read #user-selector value"
        assert "user_uid: parseInt(uid)" in js_content, "JS does not pass selected user_uid to API request payload"

        # Responsive design rules and professional styling
        assert "@media (max-width: 900px)" in css_content, "Missing tablet responsive @media query in style.css"
        assert "@media (max-width: 540px)" in css_content, "Missing phone responsive @media query in style.css"
        assert "--bg-main" in css_content and "--accent" in css_content, "Missing professional CSS design tokens"

    def test_fastapi_static_ui_mounting(self, client_without_startup):
        """Verify that FastAPI mounts /ui and serves index.html."""
        response = client_without_startup.get("/ui/index.html")
        assert response.status_code == 200, f"Expected 200 OK from /ui/index.html, got {response.status_code}"
        assert "text/html" in response.headers.get("content-type", "").lower(), "Expected text/html content type"
        assert "MIRO Assistant" in response.text, "Title or content not found in served index.html"
