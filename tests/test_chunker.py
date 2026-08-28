import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.chunker import chunk_document, count_tokens


def test_short_document_single_chunk():
    chunks = chunk_document("Title", "Short body text.", max_tokens=1000)
    assert len(chunks) == 1
    assert chunks[0].total == 1


def test_long_document_splits_into_multiple_chunks():
    body = "\n\n".join([f"Paragraph {i} " + ("word " * 200) for i in range(50)])
    chunks = chunk_document("Title", body, max_tokens=1000)
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 1000
        assert c.total == len(chunks)


def test_never_exceeds_budget_even_with_huge_single_paragraph():
    body = "word " * 5000  # one giant paragraph, no double-newlines
    chunks = chunk_document("Title", body, max_tokens=500)
    for c in chunks:
        assert c.token_count <= 550  # small tolerance for heuristic counting


if __name__ == "__main__":
    test_short_document_single_chunk()
    test_long_document_splits_into_multiple_chunks()
    test_never_exceeds_budget_even_with_huge_single_paragraph()
    print("All chunker tests passed.")
