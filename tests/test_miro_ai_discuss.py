# -*- coding: utf-8 -*-
"""tests/test_miro_ai_discuss.py
================================
Unit tests for the miro_ai_discuss Odoo addon module.
Verifies Markdown-to-HTML conversion, text cleaning, JWT generation,
manifest consistency, and XML definitions.
"""
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai_discuss/models/miro_ai_bot.py"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai_discuss/__manifest__.py"
DATA_XML_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai_discuss/data/bot_partner_data.xml"
VIEWS_XML_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai_discuss/views/discuss_channel_views.xml"


@pytest.fixture
def bot_module():
    spec = importlib.util.spec_from_file_location("miro_ai_bot", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_structure():
    """Verify manifest metadata, dependencies and data files."""
    assert MANIFEST_PATH.exists()
    content = MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = eval(content, {"__builtins__": {}})

    assert manifest["name"] == "MIRO AI Assistant (Discuss Chat)"
    assert "base" in manifest["depends"]
    assert "mail" in manifest["depends"]
    assert "miro_ai" in manifest["depends"]
    assert "data/bot_partner_data.xml" in manifest["data"]
    assert "views/discuss_channel_views.xml" in manifest["data"]
    assert manifest.get("installable") is True


def test_bot_partner_data_xml():
    """Verify partner record definition in data XML."""
    assert DATA_XML_PATH.exists()
    tree = ET.parse(DATA_XML_PATH)
    root = tree.getroot()

    record = root.find(".//record[@id='partner_miro_ai_bot']")
    assert record is not None
    assert record.attrib.get("model") == "res.partner"

    fields = {f.attrib.get("name"): (f.text or "").strip() for f in record.findall("field")}
    assert fields.get("name") == "Assistant IA"
    assert "assistant.ia@" in fields.get("email", "")
    assert record.find(".//field[@name='active']").attrib.get("eval") == "True"


def test_views_xml():
    """Verify server action and menu item in views XML."""
    assert VIEWS_XML_PATH.exists()
    tree = ET.parse(VIEWS_XML_PATH)
    root = tree.getroot()

    action = root.find(".//record[@id='action_open_miro_discuss_chat']")
    assert action is not None
    assert action.attrib.get("model") == "ir.actions.server"

    menu = root.find(".//menuitem[@id='menu_miro_ai_discuss_chat']")
    assert menu is not None
    assert menu.attrib.get("action") == "action_open_miro_discuss_chat"


def test_plain_text_rendering_escapes_html_and_does_not_parse_markdown(bot_module):
    convert = bot_module.plain_text_to_html
    assert convert("") == ""
    assert convert(None) == ""

    escaped = convert("<script>alert('xss')</script>")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped

    markdown = "### Titre\n**important**\n- Point 1\n[docs](https://example.com)"
    rendered = convert(markdown)
    assert rendered == "### Titre<br/>**important**<br/>- Point 1<br/>[docs](https://example.com)"
    assert "<h6" not in rendered
    assert "<strong>" not in rendered
    assert "<ul" not in rendered
    assert "<a " not in rendered


def test_jwt_generation(bot_module):
    """Verify HS256 JWT generation conforms to standard."""
    secret = "test_secret_key_123"
    payload = {
        "sub": "42",
        "uid": 42,
        "company_id": 1,
        "groups": [1, 2, 3],
        "api_key": "rpc_secret_key"
    }

    token = bot_module.generate_jwt_token(payload, secret)
    parts = token.split(".")
    assert len(parts) == 3

    # Header verification
    def b64_decode(s):
        padded = s + "=" * (-len(s) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))

    header = b64_decode(parts[0])
    assert header == {"alg": "HS256", "typ": "JWT"}

    # Payload verification
    decoded_payload = b64_decode(parts[1])
    assert decoded_payload["uid"] == 42
    assert decoded_payload["api_key"] == "rpc_secret_key"

    # Signature verification
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    assert parts[2] == expected_sig


def test_clean_incoming_text(bot_module):
    """Verify mention stripping and html2plaintext conversion."""
    bot = bot_module.MiroAiBot()

    # Mention tag in HTML
    html_input = '<p><a href="#" data-oe-model="res.partner" data-oe-id="99">@Assistant IA</a> Quelle est la marge ?</p>'
    cleaned = bot._clean_incoming_text(html_input)
    assert "@Assistant IA" not in cleaned
    assert "Quelle est la marge ?" in cleaned

    # Plaintext mention
    text_input = "<p>@Assistant IA comment configurer un article ?</p>"
    cleaned2 = bot._clean_incoming_text(text_input)
    assert "@Assistant IA" not in cleaned2
    assert "comment configurer un article ?" in cleaned2


def test_handle_channel_message_ignores_bot_author(bot_module):
    """Ensure bot does not respond to its own messages to avoid infinite loops."""
    bot = bot_module.MiroAiBot()
    bot._get_bot_partner_id = MagicMock(return_value=999)

    channel = MagicMock()
    channel.__len__.return_value = 1

    message = MagicMock()
    message.author_id.id = 999
    message.message_type = "comment"

    bot._handle_channel_message(channel, message, {"author_id": 999, "message_type": "comment"})
    channel.message_post.assert_not_called()


def test_handle_channel_message_ignores_unrelated(bot_module):
    """Ensure bot ignores messages in channels where it is neither direct chat nor mentioned."""
    bot = bot_module.MiroAiBot()
    bot._get_bot_partner_id = MagicMock(return_value=999)

    channel = MagicMock()
    channel.__len__.return_value = 1
    channel.channel_type = "channel"

    message = MagicMock()
    message.author_id.id = 10
    message.message_type = "comment"
    message.partner_ids.ids = [20, 30]

    bot._handle_channel_message(channel, message, {"author_id": 10, "message_type": "comment", "partner_ids": [20, 30]})
    channel.message_post.assert_not_called()


def test_handle_channel_message_in_private_chat(bot_module, monkeypatch):
    """Ensure bot responds in private 1-on-1 chat."""
    bot = bot_module.MiroAiBot()
    bot._get_bot_partner_id = MagicMock(return_value=999)
    bot._call_rag_backend = MagicMock(return_value={"answer": "**Voici la réponse**", "sources": []})

    user = MagicMock()
    user._is_public.return_value = False
    user.partner_id.id = 10

    channel = MagicMock()
    channel.__len__.return_value = 1
    channel.channel_type = "chat"
    channel.id = 55
    channel.with_context.return_value.sudo.return_value = channel
    channel.with_context.return_value.channel_partner_ids.ids = [10, 999]

    message = MagicMock()
    message.author_id.id = 10
    message.create_uid = user
    message.message_type = "comment"
    message.body = "<p>Bonjour l'assistant</p>"

    bot._handle_channel_message(channel, message, {"author_id": 10, "message_type": "comment"})

    bot._call_rag_backend.assert_called_once()
    channel.message_post.assert_called_once()
    _, kwargs = channel.message_post.call_args
    assert kwargs["author_id"] == 999
    assert kwargs["message_type"] == "comment"
    assert "<strong>Voici la réponse</strong>" in str(kwargs["body"])


def test_handle_channel_message_mention_in_public_channel(bot_module, monkeypatch):
    """Ensure bot responds when mentioned in a public channel and pings back the author."""
    bot = bot_module.MiroAiBot()
    bot._get_bot_partner_id = MagicMock(return_value=999)
    bot._call_rag_backend = MagicMock(return_value={"answer": "Explication complète", "sources": []})

    user = MagicMock()
    user._is_public.return_value = False
    user.partner_id.id = 15

    channel = MagicMock()
    channel.__len__.return_value = 1
    channel.channel_type = "channel"
    channel.id = 77
    channel.with_context.return_value.sudo.return_value = channel

    message = MagicMock()
    message.id = 501
    message.author_id.id = 15
    message.create_uid = user
    message.message_type = "comment"
    message.partner_ids.ids = [999]
    message.body = '<p><a data-oe-model="res.partner" data-oe-id="999">@Assistant IA</a> comment faire ?</p>'

    bot._handle_channel_message(channel, message, {"author_id": 15, "message_type": "comment", "partner_ids": [999]})

    bot._call_rag_backend.assert_called_once()
    channel.message_post.assert_called_once()
    _, kwargs = channel.message_post.call_args
    assert kwargs["author_id"] == 999
    assert kwargs["parent_id"] == 501
    assert kwargs["partner_ids"] == [15]


def test_markdown_lists_strip_their_markers(bot_module):
    html = bot_module.plain_text_to_html("- first\n- second\n\n1. one\n2. two")
    assert html.count("<li") == 4
    assert "- first" not in html
    assert "1. one" not in html
    assert ">first</li>" in html
    assert ">two</li>" in html
