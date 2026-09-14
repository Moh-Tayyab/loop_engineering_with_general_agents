"""YouTube Data API v3 upload + scheduling (official, headless/CI-safe).

The GitHub Actions cron uses this to upload today's merged video as a
PRIVATE scheduled upload: YouTube publishes it automatically at `publishAt`.

Why this and not browser automation of YouTube Studio?
- Data API v3 supports native scheduling (`privacyStatus=private` +
  `publishAt`), SEO fields (title/description/tags/categoryId), and
  `thumbnails.set`. It runs headlessly on a runner with no Google session.
- Auth is an OAuth2 refresh token scoped to `youtube.upload`, obtained once
  via `--youtube-auth` (the human consents in a browser). The token lives in
  `.runtime/youtube_token.json` (gitignored) or an injected CI secret file —
  NEVER commited.

Google client libs are imported lazily so dry-run/tests stay dependency-free.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import src.config as cfg
from src.state import Topic

# OAuth scope: upload a video (also lets us set the scheduled publish time).
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# categoryId 27 = Education (best fit for the crash course).
DEFAULT_CATEGORY_ID = "27"

# Lang codes on YouTube: hi is Hindi (most searchable for Urdu/Pakistani shorts).
DEFAULT_LANGUAGE = "hi"
DEFAULT_TAGS = ["shorts", "ai", "learncoding", "pakistan", "urdu"]
HASHTAGS = " #Shorts #Coding #AI #LearnInUrdu"

# Title length guard: YouTube truncates long titles around this.
MAX_TITLE_LEN = 70


class YouTubeError(RuntimeError):
    pass


class YouTubeAuthError(YouTubeError):
    pass


# --------------------------------------------------------------------------- auth
def youtube_token_path() -> Path:
    """Where the OAuth token file lives (env-overridable for CI)."""
    return Path(
        cfg.env_or("YOUTUBE_TOKEN_FILE", str(cfg.RUNTIME_DIR / "youtube_token.json"))
    )


def generate_refresh_token(client_secrets_path: Path, *, console: bool = False) -> Path:
    """One-time OAuth consent flow. The human signs into their Google account
    (browser), we save a refresh token to `.runtime/youtube_token.json`.

    Args:
        client_secrets_path: downloaded `client_secret_*.json` from Google
            Cloud Console (OAuth 2.0 Client IDs -> Desktop app).
        console: True to print the auth URL + code in a headless terminal
            (needed on the GitHub runner / VNC-less machines).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_secrets_path.exists():
        raise YouTubeAuthError(
            f"client secrets not found at {client_secrets_path} — create a Google "
            "Cloud project, enable 'YouTube Data API v3', make an OAuth client "
            "(Desktop app), and download its client_secret_*.json"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
    if console:
        creds = flow.run_console()
    else:
        creds = flow.run_local_server(port=0)
    path = youtube_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    return path


def load_credentials() -> "Any":
    """Load cached credentials; refresh in place. Raises YouTubeAuthError with
    actionable guidance if the token file is missing."""
    from google.oauth2.credentials import Credentials

    path = youtube_token_path()
    if not path.exists():
        raise YouTubeAuthError(
            f"no YouTube token at {path} — run `python -m src.main --youtube-auth` "
            "once, or set YOUTUBE_TOKEN_FILE to a CI secret file",
        )
    creds = Credentials.from_authorized_user_file(
        str(path), scopes=SCOPES
    )
    return creds


def build_youtube_client() -> "Any":
    from googleapiclient.discovery import build

    creds = load_credentials()
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- SEO
def seo_document(topic: Topic, hook: str, *, publish_at: _dt.datetime,
                 category_id: str = DEFAULT_CATEGORY_ID,
                 tags: list[str] | None = None) -> dict[str, object]:
    """Deterministic SEO metadata (title/description/tags/category/schedule) for
    the video. Purely derived from the topic + hook; no free text from prompts.

    Returns the full `videos.insert` body dict (snippet + status).
    """
    title = (f"{topic.title} — Urdu mein | "
             f"{_slug(hook)} | #Shorts").strip()
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 20].rsplit(" ", 1)[0] + " | #Shorts"
    desc_lines = [
        f"{hook}",
        "",
        f"Ye #{_slug(topic.title)} ka naya episode hai — Agentic Coding Crash Course. "
        "Dekho, samjho, aur khud banao!",
        "",
        "SUBSCRIBE for daily AI-coding shorts in Urdu.",
        HASHTAGS,
    ]
    description = "\n".join(desc_lines)
    tag_list = tags or list(dict.fromkeys(DEFAULT_TAGS + _topic_keywords(topic)))
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tag_list,
            "categoryId": category_id,
            "defaultLanguage": DEFAULT_LANGUAGE,
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "publishAt": publish_at.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def _slug(text: str) -> str:
    return " ".join(text.split())[:40]


def _topic_keywords(topic: Topic) -> list[str]:
    words = [w for w in topic.title.lower().replace("-", " ").split() if len(w) > 2]
    words += [w for w in topic.takeaway.lower().split() if len(w) > 2][:3]
    return words or ["coding"]


# --------------------------------------------------------------------------- upload
class PostCommitError(YouTubeError):
    """The YouTube upload endpoint committed the video (or may have), so an
    automatic retry would risk a DOUBLE upload. `_upload_one` maps this to a
    `pending` tombstone and dies — a human must reconcile in YouTube Studio.

    video_id is None when the failure window was indeterminate (resumable
    error after the server may have accepted the final chunk)."""

    def __init__(self, message: str, video_id: str | None = None) -> None:
        super().__init__(message)
        self.video_id = video_id


def schedule_upload(youtube, video_path: Path, body: dict[str, object],
                    thumbnail_path: Path | None = None) -> str:
    """Upload `video_path` with `body` (snippet+status). Schedules via
    privacyStatus=private + publishAt. Sets a thumbnail when provided.
    Returns the new videoId. Raises YouTubeError if download-less upload.

    Error contract (money-safety — never silently double-post):
      - video missing/empty            -> YouTubeError      (nothing committed)
      - resumable/HTTP failure while or after inserting     -> PostCommitError
        (the video MAY be committed; the caller must NOT auto-retry)
      - thumbnail set failure          -> PostCommitError(video_id)
        (the video IS committed; only the thumbnail failed)"""
    from googleapiclient.http import MediaFileUpload

    if not video_path.exists():
        raise YouTubeError(f"video missing: {video_path}")
    if video_path.stat().st_size == 0:
        raise YouTubeError(f"video empty: {video_path}")

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    # Indeterminate zone: from the first chunk onward the server MAY have
    # committed the video before ANY failure. So every failure here — HttpError,
    # the _resume_upload deadline (plain YouTubeError), socket/timeout/transport
    # errors — parks the tombstone as `pending` (no auto-retry), not `failed`.
    try:
        response = _resume_upload(request)
    except Exception as exc:  # noqa: BLE001 - may be post-commit; never retry
        raise PostCommitError(f"YouTube upload failed: {exc}") from exc
    try:
        video_id = response["id"]
    except (KeyError, TypeError, AttributeError) as exc:
        # The response arrived (a committable state) but carries no id — treat
        # as indeterminate: the video may exist, so never auto-retry.
        raise PostCommitError(f"YouTube upload returned no video id: {exc}") from exc

    if thumbnail_path is not None:
        # The video is committed from this point on, even if the file is
        # missing — so these too are PostCommitError (never `failed`/retry).
        if not thumbnail_path.exists():
            raise PostCommitError(f"thumbnail missing: {thumbnail_path}", video_id=video_id)
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=str(thumbnail_path),
            ).execute()
        except Exception as exc:  # noqa: BLE001 - video committed; do not retry
            raise PostCommitError(f"thumbnail set failed: {exc}", video_id=video_id) from exc

    return video_id


def _resume_upload(request, *, timeout_s: int = 3600) -> dict[str, object]:
    """Drive a resumable upload to completion (with progress prints).

    Args:
        request: a resumable upload request from the YouTube Data API.
        timeout_s: hard deadline in seconds (default 1 hour) to prevent
            an infinite loop if the API stops responding.
    """
    import time as _time

    deadline = _time.time() + timeout_s
    while True:
        if _time.time() > deadline:
            raise YouTubeError(
                f"YouTube upload did not complete within {timeout_s}s — "
                "check network connectivity and YouTube API status"
            )
        status, response = request.next_chunk()
        if response:
            return response
        if status:
            print(f"[youtube] uploading... {int(status.progress() * 100)}%")


def describe_upload(video_id: str, body: dict[str, object]) -> None:
    print(f"[youtube] scheduled private upload -> videoId {video_id}")
    print(f"[youtube]      title   : {body['snippet']['title']}")
    print(f"[youtube]      publish : {body['status']['publishAt']} (UTC, auto by YouTube)")


# --------------------------------------------------------------------------- JSON dump (for tests/report)
def seo_document_to_json(body: dict[str, object]) -> str:
    return json.dumps(body, indent=2, ensure_ascii=False)