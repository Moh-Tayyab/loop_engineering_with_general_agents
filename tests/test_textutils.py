"""Tests for textutils — normal cases, edge cases, and adversarial probes."""

import pytest

from textutils import count_words, redact_secrets, slugify, truncate


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


def test_redact_secrets_openai_style():
    assert redact_secrets("sk-proj-9f8e7d6c5b4a3c2d1e0f") == "[REDACTED]"


def test_redact_secrets_uppercase_prefix():
    assert redact_secrets("GHP_abcdefghijklmnopqrstuvwxyz1234567890") == "[REDACTED]"


def test_redact_secrets_sk_test_uppercase():
    assert redact_secrets("token SK_test_abcdefghijklmnopqrstuvwxyz123456") == (
        "token [REDACTED]"
    )


# --- slugify/truncate type validation --------------------------------------

@pytest.mark.parametrize("bad", [None, "5", 3.14, b"5"])
def test_slugify_rejects_non_int_max_len(bad):
    with pytest.raises(ValueError):
        slugify("hello world", max_len=bad)


@pytest.mark.parametrize("bad", [None, "5", 3.14, b"5"])
def test_truncate_rejects_non_int_max_chars(bad):
    with pytest.raises(ValueError):
        truncate("hello world", max_chars=bad)