"""System prompts and templates for AI extraction."""

SYSTEM_PROMPT = """\
You are a precise data extraction assistant. Given web page content and a user prompt, \
extract the requested information and return it as a JSON object.

Rules:
- Only return valid JSON, no markdown fences or explanation.
- If a requested field is not found, use null.
- Be precise: extract exactly what is asked for, nothing more.
"""


def build_extraction_prompt(
    content: str,
    user_prompt: str,
    schema_hint: dict | None = None,
) -> str:
    parts = [f"## Web Page Content\n\n{content}\n\n## Extraction Task\n\n{user_prompt}"]
    if schema_hint:
        parts.append(f"\n\n## Expected Output Schema\n\n{schema_hint}")
    return "\n".join(parts)
