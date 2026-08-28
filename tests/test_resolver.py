import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.resolution.resolver import EntityResolver


def test_exact_match():
    r = EntityResolver()
    result = r.resolve("OpenAI")
    assert result.canonical_name == "OpenAI"
    assert result.method == "normalized"


def test_whitespace_case_normalization():
    r = EntityResolver()
    result = r.resolve("  openai  ")
    assert result.canonical_name == "OpenAI"
    assert result.method == "normalized"


def test_legal_suffix_normalization():
    r = EntityResolver()
    result = r.resolve("OpenAI, Inc.")
    assert result.canonical_name == "OpenAI"
    assert result.method == "normalized"


def test_empty_name_is_safe():
    r = EntityResolver()
    result = r.resolve("  ")
    assert result.canonical_name == ""
    assert result.method == "unresolved_new_entity"
    assert result.confidence == 0.0


def test_different_companies_not_merged():
    r = EntityResolver()
    result = r.resolve("OpenBit")
    assert result.method == "unresolved_new_entity"
    assert result.canonical_name == "Openbit"


def test_alias_match():
    r = EntityResolver()
    result = r.resolve("Open AI")
    assert result.canonical_name == "OpenAI"
    assert result.method == "alias"


def test_fuzzy_match_typo():
    r = EntityResolver()
    result = r.resolve("Anthorpic")  # typo
    assert result.canonical_name == "Anthropic"
    assert result.method == "fuzzy"


def test_unresolved_new_entity_passes_through():
    r = EntityResolver()
    result = r.resolve("Totally Unknown Startup Co")
    assert result.method == "unresolved_new_entity"
    assert "Totally Unknown" in result.canonical_name


if __name__ == "__main__":
    test_exact_match()
    test_whitespace_case_normalization()
    test_legal_suffix_normalization()
    test_empty_name_is_safe()
    test_different_companies_not_merged()
    test_alias_match()
    test_fuzzy_match_typo()
    test_unresolved_new_entity_passes_through()
    print("All resolver tests passed.")
