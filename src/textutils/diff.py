"""textutils.diff — Myers O(ND) diff engine.

Implements Eugene Myers' shortest-edit-script algorithm (``diff``), a
git-style unified diff renderer (``render_unified``), and a text-similarity
ratio (``similarity``). Pure standard library, no dependencies.

Algorithm notes
---------------
Myers' algorithm finds the shortest edit script in O((N + M)D) time and
O(N + M) linear space per depth via a breadth-first search over the edit
graph, where ``D`` is the number of edits. Each depth ``d`` stores, for every
diagonal ``k = x - y``, the farthest ``x`` reachable with ``d`` edits. We keep
a per-depth trace of the ``v`` arrays and backtrack from the goal ``(n, m)``
to recover one minimal script (tie-breaking is deterministic).

The result is always optimal: the number of insert + delete units equals
``n + m - 2 * |LCS|``.

Complexity caveat: like ``difflib``, the worst case (two completely disjoint
inputs) is quadratic — O((N + M)^2) time when ``D ~= N + M``. Identical or
near-identical inputs are handled in near-linear time via long diagonal runs.
"""

from __future__ import annotations

from typing import Literal

from ._validate import require_str

Op = Literal["equal", "insert", "delete"]
Edit = tuple[Op, str]

__all__ = ["diff", "render_unified", "similarity", "Edit", "Op"]


def diff(a: str, b: str, *, by_line: bool = True) -> list[Edit]:
    """Return the shortest edit script that converts ``a`` into ``b``.

    Each element is an ``(op, text)`` tuple where ``op`` is one of:

    - ``"equal"``  — text present in both inputs (from ``a`` and ``b``),
    - ``"insert"`` — text taken from ``b`` only,
    - ``"delete"`` — text taken from ``a`` only.

    With ``by_line=True`` (default) the inputs are treated as newline-separated
    text and each unit is a line (newline kept). With ``by_line=False`` each
    unit is a single character. Consecutive identical operations are merged
    into one ``(op, text)`` segment.

    Raises ``ValueError`` if ``a`` or ``b`` is not a ``str``.
    """
    require_str(a)
    require_str(b)
    if not isinstance(by_line, bool):
        raise TypeError("by_line must be a bool")
    a_units = _units(a, by_line)
    b_units = _units(b, by_line)
    return _segments(a_units, b_units, _myers(a_units, b_units))


def render_unified(
    a: str,
    b: str,
    *,
    a_label: str = "a",
    b_label: str = "b",
    context: int = 3,
) -> str:
    """Render a git-style unified diff from ``a`` to ``b`` (line mode).

    ``a`` and ``b`` should be newline-terminated text (like file contents);
    the output is a ``str`` that always ends with ``"\\n"``. ``context`` is the
    number of unchanged context lines shown around each change; ``0`` shows
    only changed lines. Raises ``ValueError`` for non-``str`` input or a
    negative ``context``.
    """
    require_str(a, name="a")
    require_str(b, name="b")
    require_str(a_label, name="a_label")
    require_str(b_label, name="b_label")
    if not isinstance(context, int) or isinstance(context, bool):
        raise TypeError("context must be an int")
    if context < 0:
        raise ValueError("context must be >= 0")

    line_ops = _expand_to_lines(diff(a, b, by_line=True))
    changed = [i for i, (op, _) in enumerate(line_ops) if op != "equal"]
    header = f"--- {a_label}\n+++ {b_label}"

    if not changed:
        return header + "\n"

    hunks = _build_hunks(changed, context, len(line_ops))

    out = [header]
    for lo, hi in hunks:
        old_start = sum(1 for op, _ in line_ops[:lo] if op != "insert")
        new_start = sum(1 for op, _ in line_ops[:lo] if op != "delete")
        old_count = sum(1 for op, _ in line_ops[lo : hi + 1] if op != "insert")
        new_count = sum(1 for op, _ in line_ops[lo : hi + 1] if op != "delete")
        out.append(f"@@ -{_render_range(old_start, old_count)} +{_render_range(new_start, new_count)} @@")
        for op, line in line_ops[lo : hi + 1]:
            if op == "equal":
                prefix = " "
            elif op == "delete":
                prefix = "-"
            else:
                prefix = "+"
            out.append(prefix + line.rstrip("\n"))
    return "\n".join(out) + "\n"


def similarity(a: str, b: str, *, by_line: bool = True) -> float:
    """Return a similarity ratio in ``[0.0, 1.0]`` between ``a`` and ``b``.

    Defined as ``(len_a + len_b - edit_distance) / (len_a + len_b)`` where the
    edit distance is the Myers shortest-edit-script length. ``1.0`` means
    identical, ``0.0`` means every unit differs. ``""`` vs ``""`` returns
    ``1.0``. Raises ``ValueError`` for non-``str`` input.
    """
    require_str(a)
    require_str(b)
    if not isinstance(by_line, bool):
        raise TypeError("by_line must be a bool")
    a_units = _units(a, by_line)
    b_units = _units(b, by_line)
    total = len(a_units) + len(b_units)
    if total == 0:
        return 1.0
    moves = _myers(a_units, b_units)
    distance = sum(1 for move in moves if move != "E")
    return (total - distance) / total


# --- internals ---------------------------------------------------------------


def _units(text: str, by_line: bool) -> list[str]:
    if by_line:
        return text.splitlines(keepends=True)
    return list(text)


def _myers(a: list[str], b: list[str]) -> list[str]:
    """Return the minimal edit path as a list of moves.

    Each move is ``"E"`` (equal / diagonal), ``"D"`` (delete from ``a``) or
    ``"I"`` (insert from ``b``). ``D`` moves consume ``a``, ``I`` moves
    consume ``b``, ``E`` moves consume both.
    """
    n, m = len(a), len(b)
    max_depth = n + m
    v: dict[int, int] = {1: 0}
    trace: list[dict[int, int]] = []

    for depth in range(max_depth + 1):
        trace.append(dict(v))
        for k in range(-depth, depth + 1, 2):
            if k == -depth or (k != depth and v.get(k - 1, -1) < v.get(k + 1, -1)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, 0) + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[k] = x
            if x >= n and y >= m:
                trace.append(dict(v))
                return _backtrack(trace, n, m)
    raise RuntimeError("unreachable: Myers diff exceeded the theoretical max depth")


def _backtrack(trace: list[dict[int, int]], n: int, m: int) -> list[str]:
    """Walk the depth trace from ``(n, m)`` back to ``(0, 0)``.

    ``trace[d]`` holds the ``v`` array after depth ``d - 1`` was processed, so
    the backtrack loop mirrors exactly the forward predecessor rule.
    """
    moves: list[str] = []
    x, y = n, m
    for depth in range(len(trace) - 2, 0, -1):
        v = trace[depth]
        k = x - y
        if k == -depth or (k != depth and v.get(k - 1, -1) < v.get(k + 1, -1)):
            prev_k = k + 1
        else:
            prev_k = k - 1
        prev_x = v.get(prev_k, 0)
        prev_y = prev_x - prev_k
        while x > prev_x and y > prev_y:
            moves.append("E")
            x -= 1
            y -= 1
        if x > prev_x:
            moves.append("D")
            x -= 1
        elif y > prev_y:
            moves.append("I")
            y -= 1
    while x > 0 and y > 0:
        moves.append("E")
        x -= 1
        y -= 1
    moves.reverse()
    return moves


def _segments(a: list[str], b: list[str], moves: list[str]) -> list[Edit]:
    """Collapse the move list into merged ``(op, text)`` segments."""
    segments: list[Edit] = []
    i = j = 0
    for move in moves:
        if move == "E":
            op, token, i, j = "equal", a[i], i + 1, j + 1
        elif move == "D":
            op, token, i = "delete", a[i], i + 1
        else:
            op, token, j = "insert", b[j], j + 1
        if segments and segments[-1][0] == op:
            segments[-1] = (op, segments[-1][1] + token)
        else:
            segments.append((op, token))
    return segments


def _expand_to_lines(edits: list[Edit]) -> list[tuple[Op, str]]:
    """Split merged segments back into one entry per physical line."""
    line_ops: list[tuple[Op, str]] = []
    for op, text in edits:
        for line in text.splitlines(keepends=True):
            line_ops.append((op, line))
    return line_ops


def _build_hunks(changed: list[int], context: int, total: int) -> list[tuple[int, int]]:
    """Group changed-line indices into ``(lo, hi)`` hunks with context.

    Consecutive changed lines (an index run with no gap) form one change block;
    blocks are then expanded by ``context`` and merged when their expansions
    touch or overlap.
    """
    blocks: list[list[int]] = []
    for idx in changed:
        if blocks and idx == blocks[-1][1] + 1:
            blocks[-1][1] = idx
        else:
            blocks.append([idx, idx])

    hunks: list[tuple[int, int]] = []
    for start, end in blocks:
        lo = max(0, start - context)
        hi = min(total - 1, end + context)
        if hunks and lo <= hunks[-1][1] + 1:
            hunks[-1] = (hunks[-1][0], hi)
        else:
            hunks.append((lo, hi))
    return hunks


def _render_range(start: int, count: int) -> str:
    """Render a git-style ``-start,count`` range (1-based, omitting `,1`)."""
    if count == 0:
        return f"{start},0"
    if count == 1:
        return str(start + 1)
    return f"{start + 1},{count}"
