"""Tests for textutils — normal cases, edge cases, and adversarial probes."""

import pytest

from textutils import count_words, redact_secrets, slugify, truncate, wrap_text


# --- slugify -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello-world"),
        ("  hello   world  ", "hello-world"),
        ("A—B_C.D", "a-b-c-d"),
        ("ALREADY-SLUG", "already-slug"),
        ("", ""),
        ("   ", ""),
        ("!!!", ""),
    ],
)
def test_slugify_basic(text, expected):
    assert slugify(text) == expected


def test_slugify_unicode_lowercases():
    assert slugify("Über Café") == "ber-caf"


def test_slugify_truncates_on_word_boundary():
    result = slugify("a very long phrase that goes on and on and on forever", max_len=20)
    assert len(result) <= 20
    assert not result.endswith("-")  # never split mid-word


def test_slugify_short_max_len():
    assert slugify("hello world", max_len=1) in ("h", "")


@pytest.mark.parametrize("bad", [None, 42, 3.14, b"bytes", ["a"], {"a": 1}])
def test_slugify_rejects_non_str(bad):
    with pytest.raises(ValueError):
        slugify(bad)


def test_slugify_rejects_nonpositive_max_len():
    with pytest.raises(ValueError):
        slugify("hello", max_len=0)


# --- truncate ----------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "max_chars", "expected"),
    [
        ("short", 80, "short"),
        ("exactly-len", 11, "exactly-len"),
        ("a" * 10, 8, "aaaaa..."),  # "a"*10 -> "a"*5 + "..."
        ("hello world", 5, "he..."),
        ("", 5, ""),
    ],
)
def test_truncate_basic(text, max_chars, expected):
    assert truncate(text, max_chars=max_chars) == expected


def test_truncate_custom_ellipsis():
    assert truncate("abcdefghij", max_chars=5, ellipsis="~") == "abcd~"


def test_truncate_zero_max_chars_empty_ellipsis():
    assert truncate("abc", max_chars=0, ellipsis="") == ""


@pytest.mark.parametrize("bad", [None, 42, b"bytes"])
def test_truncate_rejects_non_str(bad):
    with pytest.raises(ValueError):
        truncate(bad)


def test_truncate_rejects_negative_max_chars():
    with pytest.raises(ValueError):
        truncate("abc", max_chars=-1)


def test_truncate_rejects_ellipsis_longer_than_max_chars():
    with pytest.raises(ValueError):
        truncate("abcdef", max_chars=2, ellipsis="....")


# --- count_words -------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("   ", 0),
        ("one", 1),
        ("one two three", 3),
        ("  one   two  ", 2),
        ("tab\tseparated\nwords", 3),
    ],
)
def test_count_words(text, expected):
    assert count_words(text) == expected


@pytest.mark.parametrize("bad", [None, 42, ["not a str"]])
def test_count_words_rejects_non_str(bad):
    with pytest.raises(ValueError):
        count_words(bad)


# --- redact_secrets ----------------------------------------------------------

def test_redact_secrets_github_token():
    assert redact_secrets("token ghp_abcdefghijklmnopqrstuvwxyz1234567890 x") == (
        "token [REDACTED] x"
    )


def test_redact_secrets_aws_key():
    assert redact_secrets("AKIAIOSFODNN7EXAMPLE") == "[REDACTED]"


def test_redact_secrets_bearer_token():
    assert redact_secrets("Authorization: Bearer abcDEF123._-~+/xyz4567890xyz") == (
        "Authorization: [REDACTED]"
    )


def test_redact_secrets_plain_text_unchanged():
    assert redact_secrets("just some normal words here") == "just some normal words here"


def test_redact_secrets_custom_replacement():
    assert redact_secrets("ghp_abcdefghijklmnopqrstuvwxyz1234567890", replacement="X") == "X"


@pytest.mark.parametrize("bad", [None, 42, b"bytes"])
def test_redact_secrets_rejects_non_str(bad):
    with pytest.raises(ValueError):
        redact_secrets(bad)


# --- wrap_text ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "width", "expected"),
    [
        ("hello world", 80, "hello world"),
        ("hello world", 11, "hello world"),
        ("hello world", 10, "hello\nworld"),
        ("hello world", 5, "hello\nworld"),
        ("hello world", 1, "h\ne\nl\nl\no\nw\no\nr\nl\nd"),
        ("a" * 10, 5, "a" * 5 + "\n" + "a" * 5),
        ("", 80, ""),
        ("   ", 80, ""),
        ("\t\n  ", 5, ""),
        ("a   b", 80, "a   b"),
        ("  a  b  ", 80, "a  b"),
        ("one two three", 7, "one two\nthree"),
    ],
)
def test_wrap_text_basic(text, width, expected):
    assert wrap_text(text, width=width) == expected


def test_wrap_text_preserves_paragraph_breaks():
    assert wrap_text("para one\n\npara two", 80) == "para one\n\npara two"


def test_wrap_text_preserves_trailing_newline():
    assert wrap_text("a\n", 80) == "a\n"


def test_wrap_text_no_line_exceeds_width():
    text = "The quick brown fox jumps over the lazy dog. " * 10
    for line in wrap_text(text, width=20).split("\n"):
        assert len(line) <= 20


def test_wrap_text_default_width_is_80():
    text = "word " * 30
    lines = wrap_text(text).split("\n")
    assert max(len(line) for line in lines) <= 80
    assert wrap_text(text) == wrap_text(text, width=80)


def test_wrap_text_single_character_lines():
    assert wrap_text("abcd", width=1) == "a\nb\nc\nd"


@pytest.mark.parametrize("bad", [None, 42, 3.14, b"bytes", ["a"], {"a": 1}])
def test_wrap_text_rejects_non_str(bad):
    with pytest.raises(ValueError):
        wrap_text(bad)


def test_wrap_text_rejects_zero_width():
    with pytest.raises(ValueError):
        wrap_text("hello", width=0)


def test_wrap_text_rejects_negative_width():
    with pytest.raises(ValueError):
        wrap_text("hello", width=-1)


@pytest.mark.parametrize("bad_width", [80.0, "80", None, True, [80], (80,), 80.5])
def test_wrap_text_rejects_non_int_width(bad_width):
    with pytest.raises(ValueError):
        wrap_text("hello", width=bad_width)