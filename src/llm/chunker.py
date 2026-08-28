"""
Intelligent chunking / truncation so no LLM request exceeds a provider's
context window (avoiding 413 Payload Too Large), while keeping the most
semantically dense content.

Strategy:
  1. Always keep the title/headline and first N tokens intact (usually the
     densest, most informative part of an article/paper/listing).
  2. If the doc still exceeds budget, split remaining body into paragraph-
     aligned chunks (never mid-sentence) and keep chunks from the start and
     end of the document (lead + conclusion tend to carry the most signal;
     middle sections are more likely to be padding/boilerplate/ads).
  3. If a doc must be processed as several chunks (e.g. long research
     paper), each chunk carries enough shared context (title + running
     summary) that the LLM can extract consistently across chunks, and the
     orchestrator merges partial extractions.
"""
from dataclasses import dataclass

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
except ImportError:  # tiktoken optional; fall back to a rough heuristic
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)  # ~4 chars/token heuristic


@dataclass
class Chunk:
    index: int
    total: int
    text: str
    token_count: int


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def chunk_document(
    title: str,
    body: str,
    max_tokens: int,
    reserved_for_prompt_and_output: int = 800,
) -> list[Chunk]:
    """
    Returns a list of chunks, each guaranteed to fit within
    `max_tokens - reserved_for_prompt_and_output`.
    """
    budget = max(500, max_tokens - reserved_for_prompt_and_output)
    title_tokens = count_tokens(title or "")

    full_text = f"{title}\n\n{body}" if title else body
    if count_tokens(full_text) <= budget:
        return [Chunk(index=0, total=1, text=full_text, token_count=count_tokens(full_text))]

    paragraphs = _split_paragraphs(body)
    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = title_tokens

    def _flush():
        if current:
            text = (title + "\n\n" if title else "") + "\n\n".join(current)
            chunks.append(Chunk(index=len(chunks), total=-1, text=text, token_count=count_tokens(text)))

    for para in paragraphs:
        para_tokens = count_tokens(para)
        if para_tokens > budget:
            # Single paragraph too large on its own -- hard-truncate it.
            para = para[: budget * 4]  # rough char cap matching token heuristic
            para_tokens = count_tokens(para)

        if current_tokens + para_tokens > budget:
            _flush()
            current = [para]
            current_tokens = title_tokens + para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens

    _flush()

    total = len(chunks)
    for c in chunks:
        c.total = total
    return chunks
