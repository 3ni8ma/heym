"""Tests for file_processor — text extraction, chunking, and overlap logic."""

import json
import unittest

from app.services.file_processor import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    FileProcessor,
    TextChunk,
    create_file_processor,
)


class CleanPdfTextTests(unittest.TestCase):
    """Tests for the PDF text deduplication/cleanup regex pipeline."""

    def setUp(self) -> None:
        self.processor = FileProcessor()

    def test_empty_string(self) -> None:
        assert self.processor._clean_pdf_text("") == ""

    def test_single_word(self) -> None:
        assert self.processor._clean_pdf_text("hello") == "hello"

    def test_no_duplications(self) -> None:
        assert self.processor._clean_pdf_text("normal text here") == "normal text here"

    def test_single_char_repetition_collapses(self) -> None:
        result = self.processor._clean_pdf_text("m m m")
        assert result == "m"

    def test_double_char_repetition_collapses(self) -> None:
        result = self.processor._clean_pdf_text("ss ss ss")
        assert result == "sss"

    def test_space_separated_letters(self) -> None:
        result = self.processor._clean_pdf_text("J o i n t")
        assert result == "Joint"

    def test_mixed_input_no_change(self) -> None:
        result = self.processor._clean_pdf_text("hello world")
        assert result == "hello world"

    def test_whitespace_normalization(self) -> None:
        result = self.processor._clean_pdf_text("hello   world")
        assert result == "hello world"

    def test_whitespace_collapse(self) -> None:
        result = self.processor._clean_pdf_text("hello   world")
        assert result == "hello world"

    def test_leading_trailing_whitespace(self) -> None:
        result = self.processor._clean_pdf_text("  hello  ")
        assert result == "hello"

    def test_numbers_are_preserved(self) -> None:
        result = self.processor._clean_pdf_text("1 2 3 4 5")
        assert result == "12345"

    def test_mixed_letters_and_numbers(self) -> None:
        result = self.processor._clean_pdf_text("page 1 of 2")
        assert "page" in result
        assert "1" in result


class ChunkTextTests(unittest.TestCase):
    """Tests for word-based text chunking."""

    def setUp(self) -> None:
        self.processor = FileProcessor(chunk_size=20, overlap=5)

    def test_empty_text(self) -> None:
        chunks = self.processor._chunk_text("", {"source": "test"})
        assert chunks == []

    def test_whitespace_only(self) -> None:
        chunks = self.processor._chunk_text("   ", {"source": "test"})
        assert chunks == []

    def test_single_chunk(self) -> None:
        text = "hello world"
        chunks = self.processor._chunk_text(text, {"source": "test"})
        assert len(chunks) == 1
        assert chunks[0].text == "hello world"
        assert chunks[0].metadata["chunk_index"] == 0
        assert chunks[0].metadata["source"] == "test"

    def test_multiple_chunks(self) -> None:
        words = ["word"] * 20
        text = " ".join(words)
        processor = FileProcessor(chunk_size=30, overlap=5)
        chunks = processor._chunk_text(text, {"source": "test"})
        assert len(chunks) > 1

    def test_chunk_index_increments(self) -> None:
        words = ["word"] * 30
        text = " ".join(words)
        processor = FileProcessor(chunk_size=30, overlap=5)
        chunks = processor._chunk_text(text, {"source": "test"})
        for i, chunk in enumerate(chunks):
            assert chunk.metadata["chunk_index"] == i

    def test_metadata_propagated(self) -> None:
        meta = {"source": "test.pdf", "page": 1}
        chunks = self.processor._chunk_text("hello world", meta)
        assert chunks[0].metadata["source"] == "test.pdf"
        assert chunks[0].metadata["page"] == 1
        assert "chunk_index" in chunks[0].metadata


class AddContextOverlapTests(unittest.TestCase):
    """Tests for context overlap injection between chunks."""

    def setUp(self) -> None:
        self.processor = FileProcessor(chunk_size=10, overlap=5)

    def test_single_chunk_unchanged(self) -> None:
        chunks = [TextChunk(text="hello", metadata={"chunk_index": 0})]
        result = self.processor._add_context_overlap(chunks)
        assert len(result) == 1
        assert result[0].text == "hello"

    def test_empty_list(self) -> None:
        result = self.processor._add_context_overlap([])
        assert result == []

    def test_first_chunk_has_next_context(self) -> None:
        chunks = [
            TextChunk(text="first chunk", metadata={"chunk_index": 0}),
            TextChunk(text="second chunk", metadata={"chunk_index": 1}),
        ]
        result = self.processor._add_context_overlap(chunks)
        assert result[0].metadata["has_prev_context"] is False
        assert result[0].metadata["has_next_context"] is True
        assert result[0].text.startswith("first chunk")

    def test_last_chunk_has_prev_context(self) -> None:
        chunks = [
            TextChunk(text="first chunk", metadata={"chunk_index": 0}),
            TextChunk(text="second chunk", metadata={"chunk_index": 1}),
        ]
        result = self.processor._add_context_overlap(chunks)
        assert result[1].metadata["has_prev_context"] is True
        assert result[1].metadata["has_next_context"] is False

    def test_middle_chunk_has_both_contexts(self) -> None:
        chunks = [
            TextChunk(text="aaa bbb ccc", metadata={"chunk_index": 0}),
            TextChunk(text="ddd eee fff", metadata={"chunk_index": 1}),
            TextChunk(text="ggg hhh iii", metadata={"chunk_index": 2}),
        ]
        processor = FileProcessor(chunk_size=50, overlap=5)
        result = processor._add_context_overlap(chunks)
        assert result[1].metadata["has_prev_context"] is True
        assert result[1].metadata["has_next_context"] is True

    def test_overlap_length_respected(self) -> None:
        long_text = "a" * 20
        short_text = "b" * 10
        chunks = [
            TextChunk(text=long_text, metadata={"chunk_index": 0}),
            TextChunk(text=short_text, metadata={"chunk_index": 1}),
        ]
        processor = FileProcessor(chunk_size=50, overlap=5)
        result = processor._add_context_overlap(chunks)
        assert "..." in result[1].text
        assert result[1].text.startswith("...")


class ProcessCsvTests(unittest.TestCase):
    """Tests for CSV file processing."""

    def setUp(self) -> None:
        self.processor = FileProcessor()

    def test_simple_csv(self) -> None:
        csv_content = b"name,age\nAlice,30\nBob,25"
        chunks = self.processor.process_csv(csv_content, "test.csv")
        assert len(chunks) == 2
        assert "Alice" in chunks[0].text
        assert "30" in chunks[0].text
        assert chunks[0].metadata["file_type"] == "csv"
        assert chunks[0].metadata["row"] == 1

    def test_csv_with_empty_rows(self) -> None:
        csv_content = b"name,age\nAlice,30\n\nBob,25"
        chunks = self.processor.process_csv(csv_content, "test.csv")
        assert len(chunks) == 2

    def test_csv_single_column(self) -> None:
        csv_content = b"item\napple\nbanana"
        chunks = self.processor.process_csv(csv_content, "test.csv")
        assert len(chunks) == 2
        assert "apple" in chunks[0].text

    def test_csv_custom_file_size(self) -> None:
        csv_content = b"name\nAlice"
        chunks = self.processor.process_csv(csv_content, "test.csv", file_size=999)
        assert chunks[0].metadata["file_size"] == 999

    def test_csv_uses_actual_length_when_no_file_size(self) -> None:
        csv_content = b"name\nAlice"
        chunks = self.processor.process_csv(csv_content, "test.csv")
        assert chunks[0].metadata["file_size"] == len(csv_content)


class ProcessJsonTests(unittest.TestCase):
    """Tests for JSON file processing."""

    def setUp(self) -> None:
        self.processor = FileProcessor()

    def test_list_of_dicts(self) -> None:
        data = [{"name": "Alice"}, {"name": "Bob"}]
        content = json.dumps(data).encode()
        chunks = self.processor.process_json(content, "test.json")
        assert len(chunks) == 2
        assert "Alice" in chunks[0].text
        assert chunks[0].metadata["file_type"] == "json"
        assert chunks[0].metadata["index"] == 0

    def test_single_dict(self) -> None:
        data = {"key": "value", "nested": {"a": 1}}
        content = json.dumps(data).encode()
        chunks = self.processor.process_json(content, "test.json")
        assert len(chunks) >= 1
        assert "key" in chunks[0].text

    def test_scalar_value(self) -> None:
        content = b'"hello"'
        chunks = self.processor.process_json(content, "test.json")
        assert len(chunks) == 1
        assert "hello" in chunks[0].text

    def test_number_value(self) -> None:
        content = b"42"
        chunks = self.processor.process_json(content, "test.json")
        assert len(chunks) == 1
        assert "42" in chunks[0].text

    def test_json_custom_file_size(self) -> None:
        data = {"a": 1}
        content = json.dumps(data).encode()
        chunks = self.processor.process_json(content, "test.json", file_size=999)
        assert chunks[0].metadata["file_size"] == 999

    def test_json_empty_list(self) -> None:
        content = b"[]"
        chunks = self.processor.process_json(content, "test.json")
        assert len(chunks) == 0


class ProcessTextTests(unittest.TestCase):
    """Tests for plain text processing."""

    def setUp(self) -> None:
        self.processor = FileProcessor(chunk_size=1000, overlap=200)

    def test_simple_text(self) -> None:
        content = b"Hello world this is a test"
        chunks = self.processor.process_text(content, "test.txt")
        assert len(chunks) >= 1
        assert "Hello" in chunks[0].text
        assert chunks[0].metadata["file_type"] == "text"

    def test_text_custom_file_size(self) -> None:
        content = b"Hello"
        chunks = self.processor.process_text(content, "test.txt", file_size=999)
        assert chunks[0].metadata["file_size"] == 999


class ProcessMarkdownTests(unittest.TestCase):
    """Tests for markdown processing."""

    def setUp(self) -> None:
        self.processor = FileProcessor(chunk_size=1000, overlap=200)

    def test_simple_markdown(self) -> None:
        content = b"# Title\n\nSome content here"
        chunks = self.processor.process_markdown(content, "test.md")
        assert len(chunks) >= 1
        assert chunks[0].metadata["file_type"] == "markdown"


class ProcessFileDispatchTests(unittest.TestCase):
    """Tests for file type dispatch in process_file."""

    def setUp(self) -> None:
        self.processor = FileProcessor(chunk_size=1000, overlap=200)

    def test_txt_extension(self) -> None:
        content = b"Hello world"
        chunks = self.processor.process_file(content, "test.txt")
        assert chunks[0].metadata["file_type"] == "text"

    def test_md_extension(self) -> None:
        content = b"# Title"
        chunks = self.processor.process_file(content, "test.md")
        assert chunks[0].metadata["file_type"] == "markdown"

    def test_markdown_extension(self) -> None:
        content = b"# Title"
        chunks = self.processor.process_file(content, "test.markdown")
        assert chunks[0].metadata["file_type"] == "markdown"

    def test_csv_extension(self) -> None:
        content = b"name\nAlice"
        chunks = self.processor.process_file(content, "test.csv")
        assert chunks[0].metadata["file_type"] == "csv"

    def test_json_extension(self) -> None:
        content = b'{"key": "value"}'
        chunks = self.processor.process_file(content, "test.json")
        assert chunks[0].metadata["file_type"] == "json"

    def test_unknown_extension_falls_back_to_text(self) -> None:
        content = b"Hello world"
        chunks = self.processor.process_file(content, "test.xyz")
        assert chunks[0].metadata["file_type"] == "text"

    def test_uppercase_extension(self) -> None:
        content = b"Hello world"
        chunks = self.processor.process_file(content, "TEST.TXT")
        assert chunks[0].metadata["file_type"] == "text"


class CreateFileProcessorTests(unittest.TestCase):
    """Tests for the factory function."""

    def test_default_values(self) -> None:
        processor = create_file_processor()
        assert processor.chunk_size == DEFAULT_CHUNK_SIZE
        assert processor.overlap == DEFAULT_OVERLAP

    def test_custom_values(self) -> None:
        processor = create_file_processor(chunk_size=500, overlap=100)
        assert processor.chunk_size == 500
        assert processor.overlap == 100


class TextChunkDataclassTests(unittest.TestCase):
    """Tests for the TextChunk dataclass."""

    def test_creation(self) -> None:
        chunk = TextChunk(text="hello", metadata={"key": "value"})
        assert chunk.text == "hello"
        assert chunk.metadata == {"key": "value"}


if __name__ == "__main__":
    unittest.main()
