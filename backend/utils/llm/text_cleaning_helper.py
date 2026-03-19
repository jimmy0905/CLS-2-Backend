import re
import json

def _escape_newlines_in_json_strings(content: str) -> str:
    """Escape unescaped newline characters appearing inside JSON string values."""
    string_pattern = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)

    def _replace(match: re.Match) -> str:
        # Within a JSON string literal, replace raw LF with the escaped version
        return match.group(0).replace("\n", "\\n")

    return string_pattern.sub(_replace, content)


def _strip_markdown_code_blocks(content: str) -> str:
    """Strip markdown code block formatting from response content."""
    if not content:
        return content

    content = content.strip()

    # Remove ```json...``` or ```...``` code block markers
    if content.startswith("```json"):
        content = content[7:]  # Remove ```json
    elif content.startswith("```"):
        content = content[3:]  # Remove ```

    if content.endswith("```"):
        content = content[:-3]  # Remove trailing ```

    return content.strip()


def _clean_response_content(response_content: str) -> str:
    """Clean control characters and other problematic characters from OpenAI API response content."""
    if response_content is None:
        return ""

    # First, strip markdown code blocks
    cleaned_content = _strip_markdown_code_blocks(response_content)

    # Then, normalize newlines and remove any BOM or null bytes
    cleaned_content = cleaned_content.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_content = cleaned_content.replace("\x00", "").replace("\ufeff", "")

    try:
        # Try to parse the JSON first
        parsed = json.loads(cleaned_content)

        # For string values in the JSON, clean any remaining control characters
        def clean_strings(obj):
            if isinstance(obj, str):
                # Remove control characters except newlines
                return re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", obj)
            elif isinstance(obj, dict):
                return {k: clean_strings(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_strings(item) for item in obj]
            return obj

        # Clean all string values in the JSON
        cleaned_parsed = clean_strings(parsed)

        # Re-serialize with ensure_ascii=False to maintain Unicode characters
        return json.dumps(cleaned_parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        # If JSON parsing fails, clean the entire content as a string
        cleaned_content = re.sub(
            r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", cleaned_content
        )

        # NEW: escape raw newlines that appear inside JSON string values so that the
        # JSON becomes parseable by the standard library
        cleaned_content = _escape_newlines_in_json_strings(cleaned_content)

        try:
            # Try parsing one more time after cleaning
            parsed = json.loads(cleaned_content)
            return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            # If still failing, return the cleaned content as-is
            return cleaned_content
