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

    def test_extract_section_plain_text(self):
        """Test section extraction from plain text."""
        text = "INTRODUCTION\nSome content here\nMORE CONTENT"

        section = self.loader._extract_section(text)

        self.assertIn(section, ["INTRODUCTION", "MORE CONTENT"])

    def _chunk_markdown(self, markdown, chunk_size=60):
        loader = WikiLoader(chunk_size=chunk_size, chunk_overlap=0)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "doc.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            return loader.load_markdown_file(path)

    def test_every_chunk_carries_the_titles_that_govern_it(self):
        markdown = "# Guide\n\n## Debouches\n\n### Par mention\n\n" + "Texte du paragraphe. " * 40

        result = self._chunk_markdown(markdown)

        paragraphs = [c for c in result["chunks"] if "Texte du paragraphe" in c]
        self.assertGreater(len(paragraphs), 1)
        for chunk in paragraphs:
            self.assertTrue(chunk.startswith("[Guide > Debouches > Par mention]\n"))
        self.assertEqual(result["metadatas"][-1]["section"], "Guide > Debouches > Par mention")

    def test_a_chunk_opening_with_a_heading_does_not_inherit_its_sibling(self):
        markdown = "# Guide\n\n## A\n\n" + "alpha " * 30 + "\n\n## B\n\n" + "beta " * 60

        result = self._chunk_markdown(markdown)
        by_start = {c.split("\n", 1)[-1][:4]: m["section"] for c, m in zip(result["chunks"], result["metadatas"])}
        sections = [m["section"] for m in result["metadatas"]]

        self.assertEqual(by_start["## B"], "Guide")
        self.assertIn("Guide > B", sections)
        self.assertNotIn("Guide > A > B", sections)

    def test_a_split_table_repeats_its_header_in_every_chunk(self):
        rows = "\n".join(f"| Row{i} | Value{i} |" for i in range(20))
        markdown = "## Table\n\n| Name | Outcome |\n| --- | --- |\n" + rows + "\n"

        chunks = self._chunk_markdown(markdown, chunk_size=40)["chunks"]

        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            if "| Row" in chunk:
                self.assertIn("| Name | Outcome |\n| --- | --- |", chunk)
        self.assertEqual(chunks[1].count("| Name | Outcome |"), 1)

    def test_has_table_is_true_only_for_chunks_holding_table_rows(self):
        prose = "Choix a | b - c. " * 20
        table = "| Name | Outcome |\n| --- | --- |\n" + "\n".join(f"| Row{i} | Value{i} |" for i in range(10))
        markdown = f"## Prose\n\n{prose}\n\n## Table\n\n{table}\n"

        result = self._chunk_markdown(markdown, chunk_size=40)

        for chunk, metadata in zip(result["chunks"], result["metadatas"]):
            self.assertEqual(metadata["has_table"], "Row" in chunk or "| Name |" in chunk)
        self.assertTrue(any(m["has_table"] for m in result["metadatas"]))
        self.assertTrue(any(not m["has_table"] for m in result["metadatas"]))

    def test_a_document_without_headings_is_left_unchanged(self):
        markdown = "Texte simple. " * 40

        chunks = self._chunk_markdown(markdown)["chunks"]

        self.assertFalse(any(chunk.startswith("[") for chunk in chunks))

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
