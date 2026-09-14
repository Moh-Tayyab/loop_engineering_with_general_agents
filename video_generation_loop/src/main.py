"""Daily video-generation loop orchestrator.

Usage:
    python -m src.main --dry-run            # template storyboard, no API/browser
    python -m src.main --login              # open Flow, human signs in once (PRO gate)
    python -m src.main                      # real run: template script + Google Flow
    python -m src.main --topic "Plan mode"  # force a specific topic
    python -m src.main --resume             # continue an in-progress day
    python -m src.main --youtube-auth       # one-time OAuth consent for YouTube upload
    python -m src.main --upload-today       # schedule today's merged video on YouTube

Storyboard scripts come from the offline TEMPLATE planner by default (no API).
To use a Gemini API instead, set FLOW_PLANNER=gemini plus GEMINI_API_KEY.

Google Flow account access is granted via the MANUAL LOGIN GATE (`--login`):
the human signs into their Google PRO plan account once in a headed browser;
the persistent session in .runtime/flow-profile/ is reused on every run.
Credentials / 2FA never reach the agent, files, or git.

State & outputs:
    .slc/state.json        run state (atomic, resume-safe)
    .slc/run/$DAY/         day manifest + storyboard
    output/$DAY/           clips + final.mp4 + per-platform captions
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import src.config as cfg
import src.merger as merger
import src.post_package as postpkg
import src.state as st
from src.planner import DURATION_S, SCENES, Storyboard, storyboard_for

MAX_CLIP_ATTEMPTS = 3  # hard escalation bound (requirement.md Constraint)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily AI-video generation loop")
    p.add_argument("--dry-run", action="store_true",
                   help="template storyboard only; no API, no browser, writes package")
    p.add_argument("--login", action="store_true",
                   help="open Flow in a headed browser and wait for the human to sign in once")
    p.add_argument("--resume", action="store_true",
                   help="accepted for clarity; an in-progress day is auto-resumed anyway")
    p.add_argument("--fresh", action="store_true",
                   help="abandon any in-progress day and start a brand-new one")
    p.add_argument("--topic", type=str, default=None,
                   help="force today's topic (title substring)")
    p.add_argument("--day", type=int, default=None,
                   help="override day number in outputs (must be >= 1)")
    p.add_argument("--strict", action="store_true",
                   help="fail instead of falling back to template when the Gemini API fails")
    p.add_argument("--list-topics", action="store_true",
                   help="print the topic queue and exit")
    p.add_argument("--youtube-auth", action="store_true",
                   help="one-time OAuth consent for YouTube upload (saves refresh token)")
    p.add_argument("--upload-today", action="store_true",
                   help="schedule today's merged video on YouTube (private + publishAt)")
    p.add_argument("--auth-console", action="store_true",
                   help="with --youtube-auth: paste URL/code flow instead of local server")
    p.add_argument("--gemini-web", action="store_true",
                   help="use browser-based Gemini Web (gemini.google.com) to write storyboard with Google PRO session (no API key)")
    return p.parse_args(argv)


def pick_topic(state: st.LoopState, requested: str | None) -> st.Topic:
    if requested:
        for t in state.topics:
            if requested.lower() in t.title.lower():
                return t  # explicit override bypasses blocked/done — human decision
        cfg.die(f"no topic matches '{requested}'")
    topic = state.pick_next_topic()
    if topic is None:
        cfg.die("all 15 concepts done or blocked — add more to course/topics.json or force --topic")
    return topic


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg.load_env()
    cfg.ensure_dirs()

    if args.day is not None and args.day < 1:
        cfg.die("--day must be >= 1")

    if args.login:
        return _login()
    if args.youtube_auth:
        return _youtube_auth(args)
    if args.upload_today:
        return _upload_today()

    state = st.LoopState()

    if args.list_topics:
        for t in state.topics:
            done = "DONE" if t.id in state.done_topic_ids else ("in-progress" if any(
                d.topic_id == t.id and d.status == "in_progress" for d in state.days.values()) else "pending")
            print(f"[{done:11}] {t.title}")
        return 0

    if args.dry_run:
        return _run_dry(state, args)

    return _run_real(state, args)


# ------------------------------------------------------------------------------- youtube
def _youtube_auth(args: argparse.Namespace) -> int:
    """One-time OAuth consent for YouTube uploads (tied to YOUR account)."""
    from src import youtube_upload as yt

    secrets = Path(cfg.env_or("YOUTUBE_CLIENT_SECRETS", ".runtime/client_secret.json"))
    print("[youtube-auth] consenting with the client secrets at:")
    print(f"[youtube-auth]   {secrets}")
    if not secrets.exists():
        cfg.die(
            "client_secret json nahi mila. Steps:\n"
            "  1. console.cloud.google.com par project banao\n"
            "  2. 'YouTube Data API v3' enable karo\n"
            "  3. OAuth consent -> External -> test user\n"
            "  4. Credentials -> OAuth client (Desktop app) -> download JSON\n"
            "  5. us file ko .runtime/client_secret.json par rakho, phir yeh command chalao"
        )
    token = yt.generate_refresh_token(secrets, console=args.auth_console)
    print(f"[youtube-auth] OK — refresh token saved to {token}")
    return 0


def _upload_today() -> int:
    """Schedule today's latest merged video on YouTube (private + publishAt).
    Run by the GitHub Actions cron (idempotent: an already-uploaded day is
    skipped, via a marker in .runtime/uploaded.json). Fails loudly with
    actionable messages — never a silent skip."""
    # latest finished day (output/day_NN/final.mp4)
    candidates = sorted(cfg.OUTPUT_DIR.glob("day_*/final.mp4"))
    if not candidates:
        cfg.die("no final.mp4 found under output/ — did the generation step run?")
    final_path = candidates[-1]
    day_dir = final_path.parent

    # idempotency marker: skip already-uploaded days. Read + write is a
    # read-modify-write, so the whole block is excluded from concurrent uploads.
    marker = cfg.RUNTIME_DIR / "uploaded.json"
    try:
        with st.FileLock(st.lock_path_for(marker), timeout_s=cfg.env_float("FLOW_LOCK_TIMEOUT", 5.0)):
            return _upload_one(final_path, day_dir, marker)
    except st.LockTimeoutError as exc:
        cfg.die(f"another upload run holds the upload marker lock — {exc}")


def _pending_message(day_name: str, marker: Path, detail: str = "") -> str:
    return (
        f"[upload] {day_name} was left PENDING (the video may already be scheduled"
        f" on YouTube){detail}. Check YouTube Studio; then either delete this entry"
        f" or set its status to 'done' with the real video_id in {marker} "
        "before re-running."
    )


def _load_marker(marker: Path) -> dict[str, dict]:
    """Load the upload marker, normalising legacy `{day: video_id}` rows into
    `{day: {status, video_id, ts, error}}` rows. Garbage rows are dropped."""
    if not marker.exists():
        return {}
    raw = json.loads(marker.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for day_name, value in raw.items():
        if isinstance(value, str):
            out[day_name] = {"status": "done", "video_id": value, "ts": None, "error": None}
        elif isinstance(value, dict):
            out[day_name] = {
                "status": str(value.get("status", "done")),
                "video_id": value.get("video_id"),
                "ts": value.get("ts"),
                "error": value.get("error"),
            }
    return out


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _upload_one(final_path: Path, day_dir: Path, marker: Path) -> int:
    """Upload one day's final.mp4 under the upload-marker lock.

    Idempotency is a three-state tombstone (pending → done|failed), EACH state
    durably written before the next action:
      - done:    skip (previously uploaded).
      - pending: a previous run wrote the tombstone but the network call was
                 interrupted — the video MAY already be scheduled on YouTube.
                 Refuse to re-upload (double post) and die with instructions.
      - failed:  retry (the YouTube call returned an error; nothing to clean up).
    Legacy string rows (`{day: video_id}`) are treated as `done`."""
    from src import planner
    from src import youtube_upload as yt

    uploaded = _load_marker(marker)
    entry = uploaded.get(day_dir.name)
    if entry:
        if entry["status"] == "done":
            print(f"[upload] {day_dir.name} already uploaded as {entry['video_id']} — skipping")
            return 0
        if entry["status"] == "pending":
            cfg.die(_pending_message(day_dir.name, marker))
        print(f"[upload] retrying a previously FAILED upload for {day_dir.name}")

    storyboard_path = day_dir / "storyboard.json"
    if not storyboard_path.exists():
        cfg.die(f"storyboard missing for {day_dir}")

    state = st.LoopState()
    sb_json = json.loads(storyboard_path.read_text(encoding="utf-8"))
    topic = next((t for t in state.topics if t.title == sb_json.get("topic")), None)
    if topic is None:
        cfg.die(f"topic '{sb_json.get('topic')}' not found in course/topics.json")
    sb = planner.Storyboard.from_dict(sb_json, topic)

    publish_at = cfg.youtube_publish_at()
    thumb = next((p for p in day_dir.glob("thumbnail.*")), None)
    body = yt.seo_document(topic, sb.hook, publish_at=publish_at)

    # Durable PENDING tombstone BEFORE the expensive network call: a crash here
    # is later detected, not silently re-uploaded (double-schedule safety).
    uploaded[day_dir.name] = {"status": "pending", "video_id": None, "ts": _utc_now(), "error": None}
    _atomic_write_json(marker, uploaded)

    print(f"[upload] {final_path}")
    print(f"[upload] publishAt={body['status']['publishAt']} (UTC, scheduled on YouTube)")
    try:
        youtube = yt.build_youtube_client()
        video_id = yt.schedule_upload(youtube, final_path, body, thumbnail_path=thumb)
    except yt.PostCommitError as exc:
        # The video MAY (or DID) get committed upstream — never auto-retry
        # (double post); park in `pending` and let the human reconcile.
        uploaded[day_dir.name] = {
            "status": "pending", "video_id": exc.video_id, "ts": _utc_now(), "error": str(exc),
        }
        _atomic_write_json(marker, uploaded)
        cfg.die(_pending_message(day_dir.name, marker, f" ({exc})"))
    except Exception as exc:
        # Pre-commit only (validation/file errors): safe to retry later.
        uploaded[day_dir.name] = {"status": "failed", "video_id": None, "ts": _utc_now(), "error": str(exc)}
        _atomic_write_json(marker, uploaded)
        cfg.die(f"upload failed: {exc}")

    uploaded[day_dir.name] = {"status": "done", "video_id": video_id, "ts": _utc_now(), "error": None}
    _atomic_write_json(marker, uploaded)
    yt.describe_upload(video_id, body)
    print(f"[upload] done — https://youtube.com/watch?v={video_id}")
    return 0


def _atomic_write_json(path: Path, data: dict) -> None:
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ------------------------------------------------------------------------------- login
def _login() -> int:
    """Manual login gate: grant the agent access to a Google PRO account.

    A headed browser opens Flow with the persistent profile; the human signs in
    once (password + 2FA stay with the human). The session is saved to
    .runtime/flow-profile/ and reused by every generation run.
    """
    from src.flow_automation import FlowAutomationError, FlowClipper

    print("[login] opening Google Flow in a headed browser...")
    print("[login] if Chromium is missing, run: python -m playwright install chromium")
    try:
        with FlowClipper(headless=False) as clipper:
            if clipper.wait_for_sign_in():
                print("[login] OK — session saved. You can now run: python -m src.main")
                return 0
            print("[login] no session detected yet — re-run --login to try again")
            return 1
    except FlowAutomationError as exc:
        cfg.die(str(exc))


# --------------------------------------------------------------------------- dry-run
def _run_dry(state: st.LoopState, args: argparse.Namespace) -> int:
    topic = pick_topic(state, args.topic)
    day = args.day or state.current_day + 1
    day_dir = cfg.OUTPUT_DIR / f"day_{day:02d}"
    storyboard_path = day_dir / "storyboard.json"
    if args.gemini_web or cfg.planner_source() in ("gemini-web", "browser-gemini"):
        from src.flow_automation import FlowClipper
        from src.gemini_web import generate_storyboard_via_gemini_web
        print("[dry-run] generating storyboard via Gemini Web (gemini.google.com)...")
        with FlowClipper() as clipper:
            page = clipper.new_page()
            try:
                sb = generate_storyboard_via_gemini_web(day, topic, page)
            finally:
                page.close()
    else:
        sb = storyboard_for(
            day, topic,
            api_key=(cfg.gcloud_api_key() if cfg.use_gemini() else None),
            strict=args.strict,
        )
    day_dir.mkdir(parents=True, exist_ok=True)
    storyboard_path.write_text(
        json.dumps(sb.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    postpkg.write_post_package(sb, Path("/nonexistent"), day_dir)
    print(f"[dry-run] Day {day:02d} · {topic.title}")
    print(f"  storyboard -> {storyboard_path}")
    print(f"  post pkg   -> {day_dir / 'post.json'} (+ 4 caption_*.txt)")
    print(f"  hook: {sb.hook}")
    print(f"  to preview real run, run: python -m src.main")
    return 0


# --------------------------------------------------------------------------- real run
def _preflight_references(sb) -> None:
    """Validate every presenter reference BEFORE the first browser/cost.

    A missing reference image is caught up front, not discovered mid-day on
    scene N after credits were spent on N-1 (money-safety). Mirrors the
    resolution + check in `_generate_one` so a valid path is never rejected."""
    from src.flow_automation import FlowAutomationError, validate_reference_image

    refs_dir = Path(__file__).resolve().parent.parent / "references"
    for scene in sb.scenes:
        if not scene.needs_presenter:
            continue
        raw = scene.reference_image
        if not raw:
            cfg.die(f"scene {scene.number} needs a presenter but has no reference_image")
        candidate = Path(raw)
        if not candidate.is_absolute() and not candidate.exists():
            candidate = refs_dir / raw
        try:
            validate_reference_image(str(candidate))
        except FlowAutomationError as exc:
            cfg.die(str(exc))


def _esc_relay(day_state: st.DayState, state: st.LoopState, exc: Exception) -> None:
    """Persist the failed day, block its topic, and escalate to the human."""
    state.finish_day(day_state, ok=False, error=str(exc))
    state.block_topic(day_state.topic_id or "")
    state.save()
    print("[escalate] @Moh-Tayyab please review — clip retry budget exhausted")


def _run_real(state: st.LoopState, args: argparse.Namespace) -> int:
    if not merger.ffmpeg_available():
        cfg.die("ffmpeg not found. Install it (apt install ffmpeg) or `pip install imageio-ffmpeg`.")

    # Cross-process exclusion gate: only ONE generation run may hold the state
    # at a time (cron + manual overlap would otherwise both claim/generate for
    # the same day and burn paid credits twice). The lock stays held for the
    # whole run; `state.save()` inside is safe (reentrant).
    try:
        with state.locked(timeout_s=cfg.env_float("FLOW_LOCK_TIMEOUT", 5.0)):
            state.reload()  # decisions must come from a fresh view under the lock
            return _run_real_locked(state, args)
    except st.LockTimeoutError as exc:
        cfg.die(f"another generation run holds the state lock — {exc} (retry after it exits)")


def _run_real_locked(state: st.LoopState, args: argparse.Namespace) -> int:
    if args.fresh:
        abandoned = state.resume_in_progress()
        if abandoned:
            state.finish_day(abandoned, ok=False, error="abandoned via --fresh")
            if abandoned.attempts >= MAX_CLIP_ATTEMPTS:
                state.block_topic(abandoned.topic_id or "")
            print(f"[fresh] abandoned day {abandoned.day}")
        state.save()

    day_state = state.resume_in_progress()
    if day_state is None:
        topic = pick_topic(state, args.topic)
        day_state = state.start_day(topic)
        state.save()
    else:
        print(f"[resume] continuing day {day_state.day} ({day_state.topic_title})")
        topic = next((t for t in state.topics if t.id == day_state.topic_id), None)
        if topic is None:
            cfg.die(f"resume topic lost: {day_state.topic_id}")

    day = args.day or day_state.day

    # durable escalation gate: never replay a day that already exhausted its budget
    if day_state.attempts >= MAX_CLIP_ATTEMPTS and day_state.status != "done":
        state.finish_day(day_state, ok=False, error="clip retry budget exhausted (from prior run)")
        state.block_topic(day_state.topic_id or "")
        state.save()
        print("[escalate] @Moh-Tayyab please review — day already exhausted its retry budget")
        cfg.die("stop: previous run already burned the retry budget for this day")

    day_dir = cfg.OUTPUT_DIR / f"day_{day:02d}"
    # never silently overwrite a completed day's output
    if (day_dir / "final.mp4").exists() and day_state.status != "in_progress":
        cfg.die(f"refusing to overwrite completed {day_dir.name} (has final.mp4)")

    # immutable storyboard per day: persist on first generation, reuse on resume
    storyboard_path = day_dir / "storyboard.json"
    if storyboard_path.exists():
        sb = Storyboard.from_dict(json.loads(storyboard_path.read_text(encoding="utf-8")), topic)
        print(f"[resume] reusing saved storyboard for day {day}")
    else:
        if args.gemini_web or cfg.planner_source() in ("gemini-web", "browser-gemini"):
            from src.flow_automation import FlowClipper
            from src.gemini_web import generate_storyboard_via_gemini_web
            print("[planner] generating storyboard via Gemini Web (gemini.google.com)...")
            with FlowClipper() as clipper:
                page = clipper.new_page()
                try:
                    sb = generate_storyboard_via_gemini_web(day, topic, page)
                finally:
                    page.close()
        else:
            sb = storyboard_for(
                day, topic,
                api_key=(cfg.gcloud_api_key() if cfg.use_gemini() else None),
                strict=args.strict,
            )
        day_dir.mkdir(parents=True, exist_ok=True)
        storyboard_path.write_text(
            json.dumps(sb.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    clips_dir = day_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Money-safety preflight: any presenter reference must exist BEFORE the
    # first browser opens — a missing image surfaces here, never after credits
    # were spent generating earlier scenes.
    _preflight_references(sb)

    clip_paths: list[Path] = []
    try:
        for scene in sb.scenes:
            clip_path = clips_dir / f"clip_{scene.number:02d}.mp4"
            if clip_path.exists() and clip_path.stat().st_size > 0:
                print(f"[reuse] {clip_path.name} (already downloaded)")
                clip_paths.append(clip_path)
                continue
            _generate_one(scene, clip_path, day_state, state)
            clip_paths.append(clip_path)
            state.mark_clip_done(day_state, clip_path.name)
            state.save()
    except RuntimeError:
        # _generate_one exhausted its retry budget and _esc_relay already
        # called finish_day(ok=False) + block_topic + state.save().  The
        # day is durably failed; propagate so the caller sees a non-zero exit
        # without calling die() (which would leave state in limbo).
        return 1

    final_path = day_dir / "final.mp4"
    print("[merge] concatenating clips with ffmpeg ...")
    try:
        merger.concat_clips(clip_paths, final_path)
    except Exception as exc:  # noqa: BLE001 - escalate to human, don't spin
        state.finish_day(day_state, ok=False, error=f"merge: {exc}")
        cfg.die(f"merge failed: {exc}")

    check = merger.evaluate_final(final_path, expected_s=SCENES * DURATION_S)
    if not check["ok"]:
        state.finish_day(day_state, ok=False, error=f"eval: {check}")
        cfg.die(f"final video failed evaluation: {check}")

    postpkg.write_post_package(sb, final_path, day_dir)
    state.finish_day(day_state, ok=True)
    print(f"[done] day {day:02d} ready -> {day_dir}")
    return 0


def _generate_one(scene, clip_path: Path, day_state: st.DayState, state: st.LoopState) -> None:
    from src.flow_automation import (
        FlowAutomationError,  # noqa: F401 - exception type used implicitly by callers
        FlowClipper,
        validate_reference_image,
    )

    for attempt in range(1, MAX_CLIP_ATTEMPTS + 1):
        # Durable gate: a clip that already burned its budget (before a crash)
        # must never be silently re-generated — every retry costs paid credits.
        if day_state.clip_attempts.get(clip_path.name, 0) >= MAX_CLIP_ATTEMPTS:
            break
        try:
            raw_ref = scene.reference_image if scene.needs_presenter else None
            if raw_ref:
                candidate = Path(raw_ref)
                if not candidate.is_absolute() and not candidate.exists():
                    candidate = Path(__file__).resolve().parent.parent / "references" / raw_ref
                raw_ref = str(candidate)
            ref = validate_reference_image(raw_ref)
            with FlowClipper() as clipper:
                clipper.generate_clip(scene.flow_prompt, clip_path, reference_image=ref)
            assert clip_path.exists() and clip_path.stat().st_size > 0
            day_state.clip_succeeded(clip_path.name)
            return
        except Exception as exc:  # noqa: BLE001 - budget-bounded, escalate at cap
            made = day_state.clip_failed(clip_path.name)
            state.save()  # durable: the per-clip attempt ledger survives crashes
            print(f"[warn] clip {scene.number} attempt {made}/{MAX_CLIP_ATTEMPTS} failed: {exc}")
            if made >= MAX_CLIP_ATTEMPTS:
                _esc_relay(day_state, state, exc)
                raise RuntimeError(
                    f"clip {scene.number} exceeded retry budget (day {day_state.day})"
                ) from exc
    # durable cap (crash between attempts): escalate without touching the clip again
    _esc_relay(
        day_state, state,
        RuntimeError(f"clip {scene.number} left over from prior failed attempts"),
    )
    raise RuntimeError(
        f"clip {scene.number} exceeded retry budget (day {day_state.day})"
    )


if __name__ == "__main__":
    sys.exit(main())