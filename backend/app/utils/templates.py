import re

from app.utils.normalization import normalize_comment

_ALLOWED_VARIABLES = {"username", "campaign_name", "keyword", "link", "media_url"}
_VARIABLE_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}|\{(\w+)\}")

_DEFAULT_FALLBACKS = {
    "username": "there",
    "link": "",
    "media_url": "",
    "keyword": "",
    "campaign_name": "",
}


def extract_template_variables(template: str) -> set[str]:
    return {match.group(1) or match.group(2) for match in _VARIABLE_PATTERN.finditer(template)}


def validate_template(template: str) -> None:
    variables = extract_template_variables(template)
    unknown = variables - _ALLOWED_VARIABLES
    if unknown:
        raise ValueError(f"Unknown template variables: {', '.join(sorted(unknown))}")


def render_template(template: str, context: dict) -> str:
    validate_template(template)

    def _replace(match: re.Match) -> str:
        var = match.group(1) or match.group(2)
        if var in context:
            return str(context[var])
        return _DEFAULT_FALLBACKS.get(var, "")

    result = _VARIABLE_PATTERN.sub(_replace, template)
    result = result.strip()
    if not result:
        raise ValueError("Rendered message cannot be empty")
    if len(result) > 1000:
        raise ValueError("Rendered message exceeds 1000 characters")
    return result
