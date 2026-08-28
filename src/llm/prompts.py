"""
Extraction prompts. Every prompt demands strict JSON-only output matching
our canonical schema field names 1:1, and explicitly forbids inventing data
not present in the provided text (this is the enforcement mechanism behind
the "no hallucinated data" requirement -- combined with keeping every
source URL attached to every record for manual audit).
"""

SYSTEM_PROMPT = (
    "You are a precise data-extraction engine for GraphOne / FrontierAtlas. "
    "You extract structured JSON from raw web content. "
    "CRITICAL RULES: "
    "1) Only output valid JSON, nothing else -- no markdown fences, no commentary. "
    "2) Never invent, guess, or hallucinate a field value. If a field is not "
    "present or cannot be confidently inferred from the given text, set it to null. "
    "3) Every record must be traceable to the exact text provided -- do not pull "
    "in outside knowledge about the entity. "
    "4) Return ONLY the JSON object requested, matching the schema exactly."
)

STARTUP_EXTRACTION_PROMPT = """\
Extract a startup entity from the following raw content. Return JSON with
exactly these fields:
{{
  "entityName": string or null,
  "employeeCount": integer or null,
  "description": string or null
}}

Raw content (source: {source_url}):
---
{content}
---
"""

PRODUCT_EXTRACTION_PROMPT = """\
Extract a product entity from the following raw webpage content.

Return JSON with exactly these fields:
{{
  "productName": string or null,
  "startupName": string or null,
  "pricingModel": one of ["FREE", "FREEMIUM", "PAID", "ENTERPRISE"] or null,
  "description": string or null
}}

IMPORTANT EXTRACTION RULES:

1. Extract only information explicitly present in the provided webpage content.
2. Never use outside knowledge.
3. Do not guess the startup/company name.
4. Do not treat words such as "Featured", "Top", "Popular", or navigation text
   as part of the actual product name unless the webpage explicitly identifies
   them as part of the product's name.
5. For pricingModel:
   - FREE = explicitly says the product is free
   - FREEMIUM = explicitly says it has a free plan plus paid features/plans
   - PAID = explicitly says payment is required
   - ENTERPRISE = explicitly identifies enterprise pricing/sales
   - otherwise null
6. For description, extract the actual product description or a concise
   description directly supported by the webpage content.
7. If a field is not present in the supplied content, return null.
8. Return valid JSON only. No markdown. No explanation.

Raw content (source: {source_url}):
---
{content}
---
"""

JOB_EXTRACTION_PROMPT = """\
Extract a job posting entity from the following raw content. Return JSON
with exactly these fields:
{{
  "company": string or null,
  "title": string or null,
  "date": ISO-8601 string or null,
  "is_remote": boolean or null,
  "role_family": string or null (e.g. "Engineering", "Research", "Sales", "Design")
}}

Raw content (source: {source_url}):
---
{content}
---
"""


def build_prompt(record_type: str, source_url: str, content: str) -> str:
    template = {
        "STARTUP": STARTUP_EXTRACTION_PROMPT,
        "PRODUCT": PRODUCT_EXTRACTION_PROMPT,
        "JOB": JOB_EXTRACTION_PROMPT,
    }[record_type]
    return template.format(source_url=source_url, content=content)
