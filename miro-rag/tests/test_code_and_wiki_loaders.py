"""
Unit tests for ingestion/code_loader.py and ingestion/wiki_loader.py

Tests cover:
- Python AST extraction and chunking
- XML record/template parsing
- Text file processing
- Markdown file processing
- Metadata generation
"""

import os
import tempfile
import unittest
from pathlib import Path

from ingestion.code_loader import CodeLoader
from ingestion.wiki_loader import WikiLoader


class TestCodeLoaderPython(unittest.TestCase):
    """Test suite for CodeLoader - Python files."""

    def setUp(self):
        """Initialize CodeLoader for each test."""
        self.loader = CodeLoader(chunk_size=200, chunk_overlap=20)

    def test_initialization(self):
        """Test CodeLoader initialization."""
        self.assertEqual(self.loader.chunk_size, 200)
        self.assertEqual(self.loader.chunk_overlap, 20)
        self.assertIsNotNone(self.loader.splitter)

    def test_extract_module_name(self):
        """Test module name extraction from file path."""
        test_cases = [
            (Path("/home/user/account/models.py"), "account"),
            (Path("/home/user/sale/models.py"), "sale"),
            (Path("/home/user/stock/models.py"), "stock"),
            (Path("/home/user/project/models.py"), "unknown"),
        ]

        for path, expected_module in test_cases:
            module = self.loader._extract_module_name(path)
            self.assertEqual(module, expected_module)

    def test_extract_ast_info_simple(self):
        """Test AST extraction from simple Python code."""
        code = """
def simple_function():
    pass

class SimpleClass:
    def method(self):
        pass
"""

        info = self.loader._extract_ast_info(code)

        self.assertIn("classes", info)
        self.assertIn("functions", info)
        self.assertEqual(len(info["classes"]), 1)
        self.assertEqual(len(info["functions"]), 1)
        self.assertEqual(info["classes"][0]["name"], "SimpleClass")
        self.assertEqual(info["functions"][0]["name"], "simple_function")

    def test_extract_ast_info_with_docstring(self):
        """Test AST extraction with module docstring."""
        code = '''"""Module docstring."""
def func():
    pass
'''

        info = self.loader._extract_ast_info(code)

        self.assertIsNotNone(info.get("docstring"))
        self.assertIn("Module docstring", info["docstring"])

    def test_extract_ast_info_syntax_error(self):
        """Test AST extraction with syntax error."""
        code = "def broken(:"  # Syntax error

        info = self.loader._extract_ast_info(code)

        # Should return empty info without crashing
        self.assertIn("classes", info)
        self.assertIn("functions", info)

    def test_compute_hash(self):
        """Test hash computation for code chunks."""
        code1 = "def function1(): pass"
        code2 = "def function2(): pass"

        hash1 = CodeLoader._compute_hash(code1)
        hash2 = CodeLoader._compute_hash(code2)

        self.assertEqual(len(hash1), 12)
        self.assertNotEqual(hash1, hash2)

    def test_load_python_file_not_found(self):
        """Test loading non-existent Python file."""
        with self.assertRaises(FileNotFoundError):
            self.loader.load_python_file("/non/existent/file.py")

    def test_load_python_file_wrong_extension(self):
        """Test loading file with wrong extension."""
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            with self.assertRaises(ValueError):
                self.loader.load_python_file(f.name)

    def test_load_python_file_metadata(self):
        """Test that load_python_file generates proper metadata."""
        code = """
class TestClass:
    def test_method(self):
        '''Test docstring'''
        pass
"""

        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False
        ) as f:
            f.write(code)
            f.flush()
            py_path = f.name

        try:
            result = self.loader.load_python_file(py_path)

            # Verify structure
            self.assertIn("chunks", result)
            self.assertIn("metadatas", result)
            self.assertIn("ast_summary", result)

            # Verify metadata fields
            for metadata in result["metadatas"]:
                self.assertIn("source", metadata)
                self.assertIn("type", metadata)
                self.assertEqual(metadata["type"], "code_python")
                self.assertIn("content_hash", metadata)
                self.assertIn("classes", metadata)
                self.assertIn("functions", metadata)
                self.assertIn("has_docstring", metadata)

        finally:
            os.unlink(py_path)


class TestCodeLoaderXML(unittest.TestCase):
    """Test suite for CodeLoader - XML files."""

    def setUp(self):
        """Initialize CodeLoader for each test."""
        self.loader = CodeLoader()

    def test_extract_xml_id_record(self):
        """Test extraction of record ID from XML."""
        xml = '<record id="account_move_001" model="account.move">'

        record_id = self.loader._extract_xml_id(xml, "record")

        self.assertEqual(record_id, "account_move_001")

    def test_extract_xml_id_template(self):
        """Test extraction of template ID from XML."""
        xml = '<template id="sale_view_001" name="Sale Order">'

        template_id = self.loader._extract_xml_id(xml, "template")

        self.assertEqual(template_id, "sale_view_001")

    def test_extract_xml_id_not_found(self):
        """Test XML ID extraction when no ID exists."""
        xml = "<record model='account.move'>"

        record_id = self.loader._extract_xml_id(xml, "record")

        self.assertIsNone(record_id)

    def test_split_xml_by_records(self):
        """Test splitting XML by record boundaries."""
        xml = """<records>
<record id="rec1" model="sale.order">
    <field name="name">Order 1</field>
</record>
<record id="rec2" model="sale.order">
    <field name="name">Order 2</field>
</record>
</records>"""

        chunks = self.loader._split_xml_by_records(xml)

        self.assertEqual(len(chunks), 2)
        self.assertIn("rec1", chunks[0])
        self.assertIn("rec2", chunks[1])

    def test_load_xml_file_not_found(self):
        """Test loading non-existent XML file."""
        with self.assertRaises(FileNotFoundError):
            self.loader.load_xml_file("/non/existent/file.xml")

    def test_load_xml_file_wrong_extension(self):
        """Test loading file with wrong extension."""
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            with self.assertRaises(ValueError):
                self.loader.load_xml_file(f.name)

    def test_load_xml_file_metadata(self):
        """Test that load_xml_file generates proper metadata."""
        xml = """<records>
<record id="test_001" model="account.move">
    <field name="name">Test Record</field>
</record>
</records>"""

        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(xml)
            f.flush()
            xml_path = f.name

        try:
            result = self.loader.load_xml_file(xml_path)

            # Verify structure
            self.assertIn("chunks", result)
            self.assertIn("metadatas", result)
            self.assertIn("xml_summary", result)

            # Verify metadata fields
            for metadata in result["metadatas"]:
                self.assertIn("source", metadata)
                self.assertIn("type", metadata)
                self.assertEqual(metadata["type"], "code_xml")
                self.assertIn("content_hash", metadata)
                self.assertIn("record_id", metadata)
                self.assertIn("template_id", metadata)

        finally:
            os.unlink(xml_path)


class TestWikiLoader(unittest.TestCase):
    """Test suite for WikiLoader."""

    def setUp(self):
        """Initialize WikiLoader for each test."""
        self.loader = WikiLoader(chunk_size=200, chunk_overlap=20)

    def test_initialization(self):
        """Test WikiLoader initialization."""
        self.assertEqual(self.loader.chunk_size, 200)
        self.assertEqual(self.loader.chunk_overlap, 20)
        self.assertIsNotNone(self.loader.splitter)

    def test_compute_hash(self):
        """Test hash computation for wiki chunks."""
        text1 = "This is content for wiki page"
        text2 = "This is different content"

        hash1 = WikiLoader._compute_hash(text1)
        hash2 = WikiLoader._compute_hash(text2)

        self.assertEqual(len(hash1), 12)
        self.assertNotEqual(hash1, hash2)

    def test_extract_section_plain_text(self):
        """Test section extraction from plain text."""
        text = "INTRODUCTION\nSome content here\nMORE CONTENT"

        section = self.loader._extract_section(text)

        self.assertIn(section, ["INTRODUCTION", "MORE CONTENT"])

    def test_extract_markdown_section(self):
        """Test section extraction from markdown."""
        text = "## Installation\nSome installation steps\n### Prerequisites"

        section = self.loader._extract_markdown_section(text)

        self.assertEqual(section, "Installation")

    def test_extract_markdown_section_h3(self):
        """Test h3 extraction from markdown."""
        text = "### Advanced Usage\nMore details here"

        section = self.loader._extract_markdown_section(text)

        self.assertEqual(section, "Advanced Usage")

    def test_load_text_file_not_found(self):
        """Test loading non-existent text file."""
        with self.assertRaises(FileNotFoundError):
            self.loader.load_text_file("/non/existent/file.txt")

    def test_load_text_file_wrong_extension(self):
        """Test loading file with wrong extension."""
        with tempfile.NamedTemporaryFile(suffix=".md") as f:
            with self.assertRaises(ValueError):
                self.loader.load_text_file(f.name)

    def test_load_text_file_metadata(self):
        """Test that load_text_file generates proper metadata."""
        text = """WIKI ARTICLE
Introduction paragraph.

SECTION 2
Another section with content.
"""

        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False
        ) as f:
            f.write(text)
            f.flush()
            txt_path = f.name

        try:
            result = self.loader.load_text_file(txt_path)

            # Verify structure
            self.assertIn("chunks", result)
            self.assertIn("metadatas", result)

            # Verify metadata fields
            for metadata in result["metadatas"]:
                self.assertIn("source", metadata)
                self.assertIn("type", metadata)
                self.assertEqual(metadata["type"], "doc_wiki")
                self.assertIn("content_hash", metadata)
                self.assertIn("section", metadata)
                self.assertIn("has_code_block", metadata)

        finally:
            os.unlink(txt_path)

    def test_load_markdown_file_not_found(self):
        """Test loading non-existent markdown file."""
        with self.assertRaises(FileNotFoundError):
            self.loader.load_markdown_file("/non/existent/file.md")

    def test_load_markdown_file_wrong_extension(self):
        """Test loading file with wrong extension."""
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            with self.assertRaises(ValueError):
                self.loader.load_markdown_file(f.name)

    def test_load_markdown_file_with_title(self):
        """Test loading markdown file with H1 title."""
        markdown = """# Documentation Title

## Introduction

This is the introduction section.

## Usage

Instructions for usage here.
"""

        with tempfile.NamedTemporaryFile(
            suffix=".md", mode="w", delete=False
        ) as f:
            f.write(markdown)
            f.flush()
            md_path = f.name

        try:
            result = self.loader.load_markdown_file(md_path)

            # Verify structure
            self.assertIn("chunks", result)
            self.assertIn("metadatas", result)

            # Verify metadata
            for metadata in result["metadatas"]:
                self.assertEqual(metadata["title"], "Documentation Title")
                self.assertIn("section", metadata)
                self.assertIn("has_table", metadata)

        finally:
            os.unlink(md_path)

    def test_load_markdown_file_with_code_block(self):
        """Test markdown file with code blocks."""
        markdown = """# Code Example

Here is some code:

```python
def hello():
    print("Hello")
```

And that's it.
"""

        with tempfile.NamedTemporaryFile(
            suffix=".md", mode="w", delete=False
        ) as f:
            f.write(markdown)
            f.flush()
            md_path = f.name

        try:
            result = self.loader.load_markdown_file(md_path)

            # Find chunk with code block
            has_code = any(m["has_code_block"] for m in result["metadatas"])
            self.assertTrue(has_code)

        finally:
            os.unlink(md_path)


if __name__ == "__main__":
    unittest.main()
