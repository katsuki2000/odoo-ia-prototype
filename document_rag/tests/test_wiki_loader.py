"""
Unit tests for ingestion/wiki_loader.py

Tests cover:
- Text file processing
- Markdown file processing (including code blocks in markdown)
- Section extraction
- Metadata generation
"""

import os
import tempfile
import unittest

from document_rag.ingestion.wiki_loader import WikiLoader


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
