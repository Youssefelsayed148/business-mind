import pytest

from app.utils.normalization import (
    normalize_arabic,
    normalize_comment,
    normalize_english,
    strip_emojis,
)


def test_strip_emojis():
    assert strip_emojis("hello") == "hello"
    assert strip_emojis("Claude🔥") == "Claude"
    assert strip_emojis("🚀test🎉") == "test"


def test_normalize_english_lowercase():
    assert normalize_english("PROMPT!!") == "prompt"


def test_normalize_english_trim():
    assert normalize_english("  Ai  ") == "ai"


def test_normalize_english_emoji():
    assert normalize_english("Claude🔥") == "claude"


def test_normalize_english_punctuation():
    assert normalize_english("Hello!") == "hello"
    assert normalize_english("(test)") == "test"


def test_normalize_arabic_tashkeel():
    assert normalize_arabic("بُرومبت") == "برومبت"


def test_normalize_arabic_alef_variants():
    assert normalize_arabic("أحمد") == "احمد"
    assert normalize_arabic("إبراهيم") == "ابراهيم"
    # آ -> ا, then ة -> ه
    assert normalize_arabic("آمنة") == "امنه"


def test_normalize_arabic_ta_marbuta():
    assert normalize_arabic("مدرسة") == "مدرسه"


def test_normalize_arabic_alef_maksura():
    assert normalize_arabic("غالي") == "غالي"
    assert normalize_arabic("علي") == "علي"


def test_normalize_comment_english():
    assert normalize_comment("  PROMPT!!  ") == "prompt"


def test_normalize_comment_arabic():
    assert normalize_comment("بُرومبت") == "برومبت"


def test_normalize_comment_arabic_alef():
    result = normalize_comment("أحمد")
    assert result == "احمد"
