"""Tests for textutils.diff — the Myers O(ND) diff engine.

Strategy:
  1. Sanity / unit tests for the public API.
  2. Exhaustive property tests: for every input pair in a small search space,
     the Myers edit script must be optimal (matching an independent LCS-based
     reference) and must reconstruct both inputs exactly.
  3. Unified-diff round-trip: applying the rendered patch must reproduce ``b``.
  4. Adversarial probes: wrong types, negative params, empty strings, unicode,
     degenerate inputs, and large-but-pathological edits.
"""

import itertools
import random

import pytest

from textutils import diff, render_unified, similarity
from textutils.diff import Edit


# --- reconstruction / distance helpers ---------------------------------------


def _reconstruct(ops: list[Edit]) -> tuple[str, str]:
    """Rebuild the two sides of an edit script (char mode) from segments."""
    a_out = "".join(text for op, text in ops if op in ("equal", "delete"))
    b_out = "".join(text for op, text in ops if op in ("equal", "insert"))
    return a_out, b_out


def _reference_edits(a: str, b: str) -> list[Edit]:
    """Independent LCS-based reference: returns *an* optimal edit script."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(
                dp[i + 1][j], dp[i][j + 1]
            )
    ops: list[Edit] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            ops.append(("equal", a[i]))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            ops.append(("delete", a[i]))
            i += 1
        else:
            ops.append(("insert", b[j]))
            j += 1
    while i < n:
        ops.append(("delete", a[i]))
        i += 1
    while j < m:
        ops.append(("insert", b[j]))
        j += 1
    return ops


def _edit_distance(ops: list[Edit]) -> int:
    """Count edit *operations*: segments may merge several units (char mode)."""
    return sum(len(text) for op, text in ops if op != "equal")


# --- diff: sanity -------------------------------------------------------------


def test_diff_identical():
    assert diff("abc", "abc", by_line=False) == [("equal", "abc")]


def test_diff_both_empty():
    assert diff("", "") == []


def test_diff_delete_all():
    assert diff("abc", "", by_line=False) == [("delete", "abc")]


def test_diff_insert_all():
    assert diff("", "abc", by_line=False) == [("insert", "abc")]


def test_diff_single_insert_in_middle():
    assert diff("abc", "abXc", by_line=False) == [("equal", "ab"), ("insert", "X"), ("equal", "c")]


def test_diff_single_delete_in_middle():
    assert diff("abXc", "abc", by_line=False) == [("equal", "ab"), ("delete", "X"), ("equal", "c")]


def test_diff_substitution_is_delete_plus_insert():
    ops = diff("cat", "cut", by_line=False)
    assert _edit_distance(ops) == 2
    assert _reconstruct(ops) == ("cat", "cut")


def test_diff_adjacent_ops_are_merged():
    ops = diff("aa", "bb", by_line=False)
    assert ops in (
        [("delete", "aa"), ("insert", "bb")],
        [("insert", "bb"), ("delete", "aa")],
    )


def test_diff_line_mode_preserves_newlines():
    ops = diff("one\ntwo\n", "one\ntwo\nthree\n")
    assert ops == [("equal", "one\ntwo\n"), ("insert", "three\n")]


def test_diff_line_mode_multiline_insert():
    a = "alpha\n"
    b = "alpha\nbeta\ngamma\n"
    assert diff(a, b) == [("equal", "alpha\n"), ("insert", "beta\ngamma\n")]


def test_diff_empty_lines():
    assert diff("a\n\nb\n", "a\nb\n") == [("equal", "a\n"), ("delete", "\n"), ("equal", "b\n")]


# --- diff: exhaustive optimality + reconstruction ------------------------------


def _small_strings(alphabet: str, max_len: int):
    for length in range(max_len + 1):
        for chars in itertools.product(alphabet, repeat=length):
            yield "".join(chars)


def test_exhaustive_char_mode_matches_reference():
    strings = list(_small_strings("ab", 5))  # 63 strings -> ~4k pairs
    for a in strings:
        for b in strings:
            ops = diff(a, b, by_line=False)
            assert _edit_distance(ops) == _edit_distance(_reference_edits(a, b)), (a, b, ops)
            assert _reconstruct(ops) == (a, b), (a, b, ops)


def test_exhaustive_char_mode_reconstruction_over_larger_alphabet():
    rng = random.Random(7)
    for _ in range(400):
        a = "".join(rng.choice("abc") for _ in range(rng.randint(0, 7)))
        b = "".join(rng.choice("abc") for _ in range(rng.randint(0, 7)))
        ops = diff(a, b, by_line=False)
        assert _edit_distance(ops) == _edit_distance(_reference_edits(a, b)), (a, b)
        assert _reconstruct(ops) == (a, b), (a, b)


def test_diff_line_mode_reconstruction():
    rng = random.Random(11)
    pool = ["aa\n", "bb\n", "cc\n", "dd\n"]
    for _ in range(200):
        a = "".join(rng.choice(pool) for _ in range(rng.randint(0, 6)))
        b = "".join(rng.choice(pool) for _ in range(rng.randint(0, 6)))
        ops = diff(a, b, by_line=True)
        a_lines = "".join(t for op, t in ops if op in ("equal", "delete"))
        b_lines = "".join(t for op, t in ops if op in ("equal", "insert"))
        assert a_lines == a, (a, b, ops)
        assert b_lines == b, (a, b, ops)


def test_diff_unicode_survives_round_trip():
    a = "héllo wörld\nnaïve café\n"
    b = "héllo wörld\ncafé au lait\n"
    ops = diff(a, b)
    a_lines = "".join(t for op, t in ops if op in ("equal", "delete"))
    b_lines = "".join(t for op, t in ops if op in ("equal", "insert"))
    assert a_lines == a
    assert b_lines == b


# --- similarity ----------------------------------------------------------------


def test_similarity_identical_is_one():
    assert similarity("hello world", "hello world") == pytest.approx(1.0)


def test_similarity_identical_empty_is_one():
    assert similarity("", "") == pytest.approx(1.0)


def test_similarity_disjoint_is_zero():
    assert similarity("aaa", "bbb", by_line=False) == pytest.approx(0.0)


def test_similarity_symmetric():
    rng = random.Random(3)
    for _ in range(50):
        a = "".join(rng.choice("abcd") for _ in range(rng.randint(0, 6)))
        b = "".join(rng.choice("abcd") for _ in range(rng.randint(0, 6)))
        assert similarity(a, b, by_line=False) == pytest.approx(
            similarity(b, a, by_line=False)
        )


def test_similarity_bounded():
    for s in ("", "x", "abc", "a\nb\nc\n"):
        assert 0.0 <= similarity(s, "abc") <= 1.0


def test_similarity_close_text_scores_high():
    assert similarity("kitten", "sitting", by_line=False) > 0.5


# --- render_unified -------------------------------------------------------------


def test_unified_headers_only_when_no_change():
    assert render_unified("same\n", "same\n") == "--- a\n+++ b\n"


def test_unified_custom_labels():
    out = render_unified("a\n", "b\n", a_label="old.py", b_label="new.py")
    assert out.startswith("--- old.py\n+++ new.py\n")


def test_unified_single_line_change():
    out = render_unified("one\ntwo\n", "one\nTWO\n")
    lines = out.splitlines()
    assert lines[2].startswith("@@ -1,2 +1,2 @@")
    assert lines[3] == " one"
    assert lines[4] == "-two"
    assert lines[5] == "+TWO"


def test_unified_range_omits_comma_for_single_line():
    out = render_unified("a\n", "b\n")
    assert "@@ -1 +1 @@" in out


def test_unified_context_zero_no_context_lines():
    a = "1\n2\n3\n4\n5\n"
    b = "1\nX\n3\nY\n5\n"
    out = render_unified(a, b, context=0)
    body = [line for line in out.splitlines() if not line.startswith(("@@", "---", "+++"))]
    assert all(line.startswith(("+", "-")) for line in body)


def test_unified_empty_a_inserts_whole_file():
    out = render_unified("", "x\ny\n")
    assert "@@ -0,0 +1,2 @@" in out


def test_unified_deletes_whole_file():
    out = render_unified("x\ny\n", "")
    assert "@@ -1,2 +0,0 @@" in out


def test_unified_multiple_hunks_are_kept_separate():
    a = "\n".join(f"{i}" for i in range(20)) + "\n"
    b = list(a.splitlines(keepends=True))
    b[2] = "CHANGED\n"
    b[15] = "CHANGED\n"
    out = render_unified(a, "".join(b))
    hunk_headers = [line for line in out.splitlines() if line.startswith("@@")]
    assert len(hunk_headers) == 2


# --- render_unified: round-trip patch application ------------------------------


def _apply_unified(patch: str, a: str, b: str) -> str:
    """Apply a unified diff produced by ``render_unified`` to ``a``.

    The patcher honours the ``@@ -old_start,old_count +new_start,new_count @@``
    hint (like real ``patch``) and is strict about the ``" "`` / ``"-"``
    context lines inside each hunk, which catches mis-indexed hunk headers.
    The final check is that the patched text equals ``b`` exactly.
    """
    lines = patch.splitlines()
    assert lines[0].startswith("--- ") and lines[1].startswith("+++ ")
    a_lines = a.splitlines(keepends=True)
    out: list[str] = []
    a_idx = 0
    for line in lines[2:]:
        if not line:
            continue
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@") and line.endswith("@@"):
            old_range = line.split()[1]  # e.g. "-1,2" or "-1" or "-0,0"
            old_start = int(old_range[1:].split(",")[0])
            target = max(0, old_start - 1)
            if target > a_idx:
                out.extend(a_lines[a_idx:target])
                a_idx = target
            continue
        code, content = line[0], line[1:]
        if code == " ":
            assert a_lines[a_idx].rstrip("\n") == content, (a_idx, a_lines[a_idx], content)
            out.append(content + "\n")
            a_idx += 1
        elif code == "-":
            assert a_lines[a_idx].rstrip("\n") == content, (a_idx, a_lines[a_idx], content)
            a_idx += 1
        elif code == "+":
            out.append(content + "\n")
    out.extend(a_lines[a_idx:])
    assert "".join(out) == b
    return "".join(out)


def test_unified_round_trip_random():
    rng = random.Random(5)
    words = ["alpha", "beta", "gamma", "delta"]
    for _ in range(150):
        a = "".join(rng.choice(words) + "\n" for _ in range(rng.randint(0, 8)))
        b = "".join(rng.choice(words) + "\n" for _ in range(rng.randint(0, 8)))
        patch = render_unified(a, b)
        assert _apply_unified(patch, a, b) == b, (a, b, patch)


def test_unified_round_trip_context_zero():
    a = "same\nsame\none\nsame\n"
    b = "same\nsame\ntwo\nsame\n"
    patch = render_unified(a, b, context=0)
    assert _apply_unified(patch, a, b) == b


# --- adversarial probes --------------------------------------------------------


@pytest.mark.parametrize("func", [diff, render_unified, similarity])
@pytest.mark.parametrize("bad", [None, 42, 3.14, b"bytes", ["a"], {"a": 1}])
def test_diff_api_rejects_non_str(func, bad):
    with pytest.raises(ValueError):
        func(bad, "x")


@pytest.mark.parametrize("bad", [None, 42, b"bytes"])
def test_diff_rejects_non_str_second_arg(bad):
    with pytest.raises(ValueError):
        diff("x", bad)


def test_render_unified_rejects_negative_context():
    with pytest.raises(ValueError):
        render_unified("a\n", "b\n", context=-1)


def test_render_unified_rejects_non_int_context():
    with pytest.raises(TypeError):
        render_unified("a\n", "b\n", context=3.5)
    with pytest.raises(TypeError):
        render_unified("a\n", "b\n", context="3")


@pytest.mark.parametrize("bad", [None, 42])
def test_render_unified_rejects_bad_labels(bad):
    with pytest.raises(ValueError):
        render_unified("a\n", "b\n", a_label=bad)


def test_diff_rejects_invalid_by_line_type():
    with pytest.raises(TypeError):
        diff("a", "b", by_line="yes")  # truthy non-bool; document behaviour
    with pytest.raises(TypeError):
        similarity("a", "b", by_line=1)


def test_diff_very_common_prefix_is_fast():
    a = "x" * 5000 + "a\n"
    b = "x" * 5000 + "b\n"
    ops = diff(a, b, by_line=False)
    assert _edit_distance(ops) == 2


def test_diff_degenerate_all_same_returns_single_equal():
    assert diff("a\n" * 100, "a\n" * 100) == [("equal", "a\n" * 100)]


def test_similarity_handles_very_long_input():
    assert similarity("a" * 5000, "a" * 5000) == pytest.approx(1.0)


def test_diff_rejects_astral_plane_input_without_corruption():
    a = "😀\n😀\n"
    b = "😀\n😎\n"
    ops = diff(a, b)
    a_lines = "".join(t for op, t in ops if op in ("equal", "delete"))
    b_lines = "".join(t for op, t in ops if op in ("equal", "insert"))
    assert a_lines == a
    assert b_lines == b