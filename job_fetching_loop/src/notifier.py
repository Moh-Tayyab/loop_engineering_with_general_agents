"""Notification system: Telegram + WhatsApp delivery of job digests.

Telegram is the primary target (free bot API, rich formatting).
WhatsApp is secondary (Twilio or Cloud API, requires paid account).
"""
from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

import src.config as cfg
from src.log import get_logger
from src.models import NormalizedJob, utc_now

log = get_logger(__name__)


class Notifier(ABC):
    # Stable identity for per-channel notification dedup (telegram, whatsapp).
    kind: str = "unnamed"

    @abstractmethod
    def send_daily(self, jobs: list[NormalizedJob], stats: dict[str, Any]) -> bool:
        """Send daily summary. Returns True on success."""
        ...

    @abstractmethod
    def send_weekly_digest(self, week_stats: dict[str, Any], top_jobs: list[NormalizedJob]) -> bool:
        """Send the weekly digest (delivered Monday after the 3-day backfill)."""
        ...

# ── Telegram ─────────────────────────────────────────────────────────────────

class TelegramNotifier(Notifier):
    kind = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_base = f"https://api.telegram.org/bot{bot_token}"

    def send_daily(self, jobs: list[NormalizedJob], stats: dict[str, Any]) -> bool:
        text = self._format_daily(jobs, stats)
        return self._send(text)

    def send_weekly_digest(self, week_stats: dict[str, Any], top_jobs: list[NormalizedJob]) -> bool:
        text = self._format_weekly(week_stats, top_jobs)
        return self._send(text)

    def _format_daily(self, jobs: list[NormalizedJob], stats: dict[str, Any]) -> str:
        today = utc_now().date().isoformat()
        total = stats.get("total_this_week", 0)
        new_count = len(jobs)

        lines = [
            f"🤖 AI/ML Jobs — {today}",
            "━" * 32,
            f"📊 New: {new_count} jobs | This week: {total}",
            "",
        ]

        top = jobs[:5]
        if top:
            lines.append("🔥 Top Picks:")
            for i, job in enumerate(top, 1):
                salary = ""
                if job.salary_min:
                    salary = f" — {job.salary_currency or ''}{job.salary_min//1000}k"
                    if job.salary_max:
                        salary += f"-{job.salary_max//1000}k"
                lines.append(f"{i}. {job.title} @ {job.company} ({job.location_type}){salary}")
                lines.append(f"   {job.url}")
            lines.append("")

        sources = stats.get("sources", {})
        if sources:
            lines.append("📡 Sources:")
            for name, count in sources.items():
                lines.append(f"  {name}: {count} jobs")
            lines.append("")

        lines.append(f"📁 Full list: output/jobs_{today}.json")
        return "\n".join(lines)

    def _format_weekly(self, week_stats: dict[str, Any], top_jobs: list[NormalizedJob]) -> str:
        week = week_stats.get("week_key", "this week")
        total = week_stats.get("total", 0)
        by_source = week_stats.get("by_source", {})
        by_type = week_stats.get("by_type", {})

        lines = [
            f"📊 Weekly Digest — {week}",
            "━" * 32,
            f"Total jobs found: {total}",
            "",
        ]

        if by_source:
            lines.append("📡 By Source:")
            for name, count in sorted(by_source.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {count}")
            lines.append("")

        if by_type:
            lines.append("💼 By Type:")
            for jtype, count in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"  {jtype}: {count}")
            lines.append("")

        top = top_jobs[:10]
        if top:
            lines.append("🏆 Top 10 This Week:")
            for i, job in enumerate(top, 1):
                salary = ""
                if job.salary_min:
                    salary = f" ({job.salary_currency or ''}{job.salary_min//1000}k)"
                lines.append(f"{i}. {job.title} @ {job.company}{salary}")
            lines.append("")

        lines.append("📁 Full report: output/digest_" + week_stats.get("week_key", "unknown") + ".json")
        return "\n".join(lines)

    def _send(self, text: str) -> bool:
        import urllib.request
        import urllib.parse

        if not self.bot_token or not self.chat_id:
            log.warning("[telegram] missing BOT_TOKEN or CHAT_ID — skipped")
            return False
        # Telegram hard-caps a message at 4096 chars; trim and note the cut.
        if len(text) > 4000:
            text = text[:3990] + "\n… [truncated]"
        # plain text (no Markdown): job titles with `*_[]()` in them would
        # else break parse_mode=Markdown and 400 the whole send.
        url = f"{self.api_base}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.status
                if status == 200:
                    log.info("telegram sent (%d chars)", len(text))
                    return True
                else:
                    body = resp.read().decode()
                    log.warning("telegram API returned %s: %s", status, body)
                    return False
        except Exception as exc:
            log.warning("telegram send failed: %s", exc)
            return False

# ── WhatsApp (Twilio) ───────────────────────────────────────────────────────

class WhatsAppNotifier(Notifier):
    kind = "whatsapp"

    def __init__(self, from_number: str, to_number: str, auth_token: str, account_sid: str):
        self.from_number = from_number
        self.to_number = to_number
        self.auth_token = auth_token
        self.account_sid = account_sid

    def send_daily(self, jobs: list[NormalizedJob], stats: dict[str, Any]) -> bool:
        text = self._format_plain(jobs, stats)
        return self._send(text)

    def send_weekly_digest(self, week_stats: dict[str, Any], top_jobs: list[NormalizedJob]) -> bool:
        text = self._format_plain(top_jobs, week_stats)
        return self._send(text)

    def _format_plain(self, jobs: list[NormalizedJob], stats: dict[str, Any]) -> str:
        today = utc_now().date().isoformat()
        lines = [f"AI/ML Jobs — {today}", f"New: {len(jobs)}", ""]
        for i, j in enumerate(jobs[:5], 1):
            lines.append(f"{i}. {j.title} @ {j.company}")
        return "\n".join(lines)

    def _send(self, text: str) -> bool:
        import urllib.request
        import base64

        if not self.auth_token or not self.account_sid:
            log.warning("[whatsapp] missing credentials — skipped")
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = urllib.parse.urlencode({
            "From": f"whatsapp:{self.from_number}",
            "To": f"whatsapp:{self.to_number}",
            "Body": text,
        }).encode()
        auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    log.info("[whatsapp] sent")
                    return True
                log.warning("whatsapp API returned %s", resp.status)
                return False
        except Exception as exc:
            log.warning("whatsapp send failed: %s", exc)
            return False

# ── LinkedIn (UGC Posts API) ────────────────────────────────────────────────

class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Fail-closed redirect policy for the LinkedIn POST.

    urllib.request follows 301/302/303 by CONVERTING the POST to a GET and
    re-issuing it with the request headers — including `Authorization: Bearer`.
    Following a redirect anywhere would leak the LinkedIn access token to the
    redirect target. Returning None from redirect_request makes urlopen raise
    (HTTPError on the 3xx), which we catch and log. Never follow.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LinkedInNotifier(Notifier):
    """Post the weekly digest to LinkedIn as a member status update.

    Weekly-only: the weekly digest is delivered Monday morning (Friday is the
    LinkedIn hiring-feed scrape day), so this post fires then, not on Friday.
    Uses the LinkedIn API v2 `ugcPosts` endpoint, which needs an OAuth2 token
    scoped with `w_member_social` (from a LinkedIn Developer app) plus the
    author's person URN (urn:li:person:<id>). Posts are PUBLIC member shares
    with text only (shareMediaCategory: NONE) — the same plain-text safety rule
    as Telegram (job titles with `*_[]()` would break rich text).
    """
    kind = "linkedin"

    def __init__(self, access_token: str, author_urn: str):
        self.access_token = access_token
        self.author_urn = author_urn

    def send_daily(self, jobs: list[NormalizedJob], stats: dict[str, Any]) -> bool:
        log.info("[linkedin] weekly-only notifier — daily send skipped")
        return False

    def send_weekly_digest(self, week_stats: dict[str, Any], top_jobs: list[NormalizedJob]) -> bool:
        text = self._format_weekly(week_stats, top_jobs)
        return self._post_share(text)

    def _format_weekly(self, week_stats: dict[str, Any], top_jobs: list[NormalizedJob]) -> str:
        week = week_stats.get("week_key", "this week")
        total = week_stats.get("total", 0)
        by_source = week_stats.get("by_source", {})

        lines = [
            f"AI/ML Remote Jobs — Weekly Digest ({week})",
            "",
            f"Total remote AI/ML jobs found this week: {total}",
            "",
        ]
        if by_source:
            lines.append("Sources:")
            for name, count in sorted(by_source.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {count}")
            lines.append("")
        top = top_jobs[:10]
        if top:
            lines.append("Top openings this week:")
            for i, j in enumerate(top, 1):
                lines.append(f"{i}. {j.title} @ {j.company} ({j.location_type})")
                lines.append(f"   {j.url}")
            lines.append("")
        lines.append("Full report in the output/: digest_*.json")

        text = "\n".join(lines)
        # LinkedIn caps a plain-text share at 3000 chars; trim conservatively.
        if len(text) > 2900:
            text = text[:2880] + "\n…"
        return text

    def _post_share(self, text: str) -> bool:
        if not self.access_token or not self.author_urn:
            log.warning("[linkedin] missing LINKEDIN_POST_ACCESS_TOKEN or LINKEDIN_POST_URN — skipped")
            return False
        if not self.author_urn.startswith("urn:li:"):
            log.warning("[linkedin] LINKEDIN_POST_URN must look like urn:li:person:<id> — skipped")
            return False
        payload = json.dumps({
            "author": self.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.linkedin.com/v2/ugcPosts",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
                "LinkedIn-Version": "202401",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(_RefuseRedirects())
        try:
            with opener.open(req, timeout=15) as resp:
                # 202 Accepted is a legit success: LinkedIn queues ugcPosts
                # for asynchronous processing. Missing it would make every
                # slow-but-successful post report as failed and re-post every
                # subsequent run (weekly:linkedin never marked).
                if resp.status in (200, 201, 202):
                    log.info("[linkedin] weekly digest posted (%d chars)", len(text))
                    return True
                body = resp.read().decode(errors="replace")
                log.warning("linkedin API returned %s: %s", resp.status, body[:500])
                return False
        except Exception as exc:
            log.warning("linkedin post failed: %s", exc)
            return False

def build_notifiers() -> list[Notifier]:
    """Build all configured notifiers from environment."""
    notifiers: list[Notifier] = []
    if cfg.notify_telegram():
        token = cfg.env_or("TELEGRAM_BOT_TOKEN", "")
        chat = cfg.env_or("TELEGRAM_CHAT_ID", "")
        if token and not chat:
            log.warning("TELEGRAM_BOT_TOKEN set but TELEGRAM_CHAT_ID missing — Telegram notifications disabled")
        elif token and chat:
            notifiers.append(TelegramNotifier(token, chat))
    if cfg.notify_whatsapp():
        sid = cfg.env_or("WHATSAPP_ACCOUNT_SID", "")
        token = cfg.env_or("WHATSAPP_AUTH_TOKEN", "")
        from_num = cfg.env_or("WHATSAPP_FROM", "")
        to_num = cfg.env_or("WHATSAPP_TO", "")
        if sid and token and from_num and to_num:
            notifiers.append(WhatsAppNotifier(from_num, to_num, token, sid))
        else:
            log.warning("NOTIFY_WHATSAPP=1 but credentials incomplete — WhatsApp notifications disabled")
    if cfg.notify_linkedin():
        token = cfg.env_or("LINKEDIN_POST_ACCESS_TOKEN", "")
        urn = cfg.env_or("LINKEDIN_POST_URN", "")
        if token and urn:
            notifiers.append(LinkedInNotifier(token, urn))
        else:
            log.warning("NOTIFY_LINKEDIN=1 but LINKEDIN_POST_ACCESS_TOKEN/LINKEDIN_POST_URN incomplete — LinkedIn posting disabled")
    return notifiers