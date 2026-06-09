import pytest

from app.utils.templates import (
    extract_template_variables,
    render_template,
    validate_template,
)


def test_extract_template_variables():
    assert extract_template_variables("Hello {username}") == {"username"}
    assert extract_template_variables("Hello {{username}}") == {"username"}
    assert extract_template_variables("{username} {link}") == {"username", "link"}
    assert extract_template_variables("No vars") == set()


def test_validate_template_unknown_variable():
    with pytest.raises(ValueError, match="Unknown template variables: invalid"):
        validate_template("Hello {invalid}")


def test_validate_template_allowed_variables():
    validate_template("Hello {username}, here is {link}")


def test_render_template_basic():
    result = render_template("Hello {username}", {"username": "Ahmed"})
    assert result == "Hello Ahmed"


def test_render_template_double_braces():
    result = render_template("Hello {{username}}", {"username": "Ahmed"})
    assert result == "Hello Ahmed"


def test_render_template_missing_fallback():
    result = render_template("Hello {username}", {})
    assert result == "Hello there"


def test_render_template_empty_result_raises():
    with pytest.raises(ValueError, match="Rendered message cannot be empty"):
        render_template("{link}", {})


def test_render_template_too_long_raises():
    template = "Hello {username} " + "x" * 1000
    with pytest.raises(ValueError, match="exceeds 1000 characters"):
        render_template(template, {"username": "test"})


def test_render_template_all_allowed_vars():
    template = "Hi {username}, {campaign_name}, {keyword}, {link}, {media_url}"
    result = render_template(
        template,
        {
            "username": "u",
            "campaign_name": "c",
            "keyword": "k",
            "link": "l",
            "media_url": "m",
        },
    )
    assert result == "Hi u, c, k, l, m"
