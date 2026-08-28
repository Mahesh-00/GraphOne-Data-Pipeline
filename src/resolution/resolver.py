"""
Deterministic-first entity resolution: canonicalizes messy startup/product
name strings against a seed list.

Pipeline (cheapest/most-deterministic check first, most expensive last):
  1. Exact match (case/whitespace-insensitive) against canonical names.
  2. Exact match against the known-alias table.
  3. Normalization (strip legal suffixes like "Inc.", "Ltd", "LLC", "Co",
     punctuation, extra whitespace) + retry exact match.
  4. Fuzzy match (token-sort ratio) against canonical names, thresholded --
     only accepted above a high similarity bar to avoid false merges.
  5. If nothing clears the threshold, the name is treated as a genuinely
     new / unseen entity and passed through as its own canonical form
     (logged, so the mapping can be reviewed and added to the seed list).

Every resolution decision (raw name, canonical name, method, confidence) is
logged to the mapping log required for the "Entity Mapping Log" deliverable
tab.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from src.utils.logging_config import get_logger, log_ctx

SEED_PATH = Path(__file__).parent / "canonical_seed.json"

logger = get_logger(__name__)

LEGAL_SUFFIXES = re.compile(
    r"\b(inc\.?|incorporated|ltd\.?|limited|llc\.?|co\.?|corp\.?|corporation|technologies|labs?|pbc)\b",
    re.IGNORECASE,
)
PUNCTUATION = re.compile(r"[.,\-_/\\'\"]+")
WHITESPACE = re.compile(r"\s+")

FUZZY_THRESHOLD = 88  # 0-100; conservative to avoid false merges


@dataclass
class ResolutionResult:
    raw_name: str
    canonical_name: str
    method: str          # "exact" | "alias" | "normalized" | "fuzzy" | "unresolved_new_entity"
    confidence: float     # 0-100
    source_name: Optional[str] = None
    source_url: Optional[str] = None


def _normalize(name: str) -> str:
    n = name.strip().lower()
    n = LEGAL_SUFFIXES.sub("", n)
    n = PUNCTUATION.sub(" ", n)
    n = WHITESPACE.sub(" ", n).strip()
    return n


def _canonical_guess(raw_name: str) -> str:
    normalized = _normalize(raw_name)
    if not normalized:
        return ""

    tokens = normalized.split(" ")
    return " ".join(
        token.upper() if token.isupper() else token.capitalize()
        for token in tokens
    )


class EntityResolver:
    def __init__(self, seed_path: Path = SEED_PATH):
        seed = json.loads(seed_path.read_text())
        self.canonical_names: list[str] = seed["startups"]
        self.alias_to_canonical: dict[str, str] = {}
        for canonical, aliases in seed.get("aliases", {}).items():
            for alias in aliases:
                self.alias_to_canonical[_normalize(alias)] = canonical
        # also index canonical names themselves under normalized form
        self._normalized_to_canonical = {_normalize(c): c for c in self.canonical_names}
        self.mapping_log: list[ResolutionResult] = []

    def resolve(
        self,
        raw_name: Optional[str],
        source_name: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> ResolutionResult:
        raw_name_value = raw_name or ""

        if not raw_name_value.strip():
            result = ResolutionResult(
                raw_name_value,
                "",
                "unresolved_new_entity",
                0.0,
                source_name,
                source_url,
            )
            log_ctx(
                logger,
                20,
                "entity_resolution",
                raw_name=raw_name_value,
                canonical_name=result.canonical_name,
                method=result.method,
                confidence=result.confidence,
                source_name=source_name,
                source_url=source_url,
            )
            self.mapping_log.append(result)
            return result

        norm = _normalize(raw_name_value)

        # 1. normalized exact match: case/punctuation/suffix-agnostic.
        if norm in self._normalized_to_canonical:
            result = ResolutionResult(
                raw_name_value,
                self._normalized_to_canonical[norm],
                "normalized",
                100.0,
                source_name,
                source_url,
            )
            log_ctx(
                logger,
                20,
                "entity_resolution",
                raw_name=raw_name_value,
                canonical_name=result.canonical_name,
                method=result.method,
                confidence=result.confidence,
                source_name=source_name,
                source_url=source_url,
            )
            self.mapping_log.append(result)
            return result

        # 2. alias table: handle explicit known alias strings.
        if norm in self.alias_to_canonical:
            result = ResolutionResult(
                raw_name_value,
                self.alias_to_canonical[norm],
                "alias",
                100.0,
                source_name,
                source_url,
            )
            log_ctx(
                logger,
                20,
                "entity_resolution",
                raw_name=raw_name_value,
                canonical_name=result.canonical_name,
                method=result.method,
                confidence=result.confidence,
                source_name=source_name,
                source_url=source_url,
            )
            self.mapping_log.append(result)
            return result

        # 3. fuzzy match against canonical names
        match = process.extractOne(
            norm, self._normalized_to_canonical.keys(), scorer=fuzz.token_sort_ratio
        )
        if match and match[1] >= FUZZY_THRESHOLD:
            canonical = self._normalized_to_canonical[match[0]]
            result = ResolutionResult(
                raw_name_value,
                canonical,
                "fuzzy",
                float(match[1]),
                source_name,
                source_url,
            )
            log_ctx(
                logger,
                20,
                "entity_resolution",
                raw_name=raw_name_value,
                canonical_name=result.canonical_name,
                method=result.method,
                confidence=result.confidence,
                source_name=source_name,
                source_url=source_url,
            )
            self.mapping_log.append(result)
            return result

        # 4. unresolved -- new entity, not in our seed of 50. Pass through as its
        #    own canonical form and flag for manual review.
        canonical_guess = _canonical_guess(raw_name_value)
        result = ResolutionResult(
            raw_name_value,
            canonical_guess,
            "unresolved_new_entity",
            0.0,
            source_name,
            source_url,
        )
        log_ctx(
            logger,
            20,
            "entity_resolution",
            raw_name=raw_name_value,
            canonical_name=result.canonical_name,
            method=result.method,
            confidence=result.confidence,
            source_name=source_name,
            source_url=source_url,
        )
        self.mapping_log.append(result)
        return result

    def export_mapping_log(self) -> list[dict]:
        return [r.__dict__ for r in self.mapping_log]
