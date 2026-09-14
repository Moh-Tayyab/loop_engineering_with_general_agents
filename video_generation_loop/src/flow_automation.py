"""Google Flow automation via Playwright (persistent Google session).

The Flow web UI (labs.google/fx/tools/flow) is a consumer tool with no public
API, so we drive it like a user: open a persistent Chromium profile (signed in
once, reused forever), type the prompt, click generate, then download the clip.

Design rules (from requirement.md):
- Never try to log in automatically; if the profile is signed out -> guidance.
- If a selector is ever missing (DOM changed), degrade to manual-assist: print
  the exact prompt and wait for the human to save the clip, then continue.
- All UI interaction is best-effort and defensive; the pipeline must never hang.

Only imported when a browser run is requested (keeps --dry-run dependency-free).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

import src.config as cfg
import src.merger as merger

# Weak textual anchors, order matters (first match wins). `textarea` alone is
# dangerous: Google injects an INVISIBLE `g-recaptcha-response` textarea, so we
# filter every field by visibility before touching it.
PROMPT_FIELD_HINTS = [
    "[contenteditable='true']:visible",
    "[role='textbox'][contenteditable='true']:visible",
    "textarea[placeholder*='prompt' i]:visible",
    "textarea[placeholder*='Describe' i]:visible",
    "textarea[placeholder*='Video' i]:visible",
    "[contenteditable='true'][data-placeholder]:visible",
]
GENERATE_HINTS = [
    "button:has-text('arrow_forward'):visible",  # Flow editor submit (icon + 'Create')
    "button:has-text('Generate'):visible",
    "button:has-text('Start'):visible",
    "button:has-text('Create'):visible",
]
DOWNLOAD_HINTS = [
    "a:has-text('Download'):visible",
    "button:has-text('Download'):visible",
    "[aria-label*='Download' i]:visible",
    "[title*='Download' i]:visible",
    "a[download]:visible",
    "button:has-text('Save'):visible",
]
# Flow "Characters" presenter pipeline (MCP-verified Sep 2026, live PRO account):
# Flow's consistent-presenter mechanism is the Characters feature, NOT a raw
# media ingredient. The verified pipeline (menu-driven, no hidden file inputs):
#   1. "Add media menu" button -> "Upload" menuitem -> file chooser -> image in library
#   2. Characters nav (sidebar) -> "Add from project" button -> select image in dialog
#      -> "Add media" button -> character page opens with the image
#   3. "Done" -> saved Character reusable in prompts via "Add ingredients" picker.
# Selectors below were confirmed against live Flow snapshots (Sep 2026).
ADD_MEDIA_MENU_BTN = "button:has-text('Add media'):visible"
UPLOAD_MENUITEM = "menuitem:has-text('Upload'):visible"
CHARACTERS_NAV = "text=accessibility_new >> xpath=.. >> xpath=.."
ADD_FROM_PROJECT_BTN = "button:has-text('Add from project'):visible"
ADD_MEDIA_IN_DIALOG = "button:has-text('Add media'):visible"
CHARACTER_DONE_BTN = "button:has-text('Done'):visible"
ADD_INGREDIENTS_BTN = "button:has-text('Add ingredients to the prompt box'):visible"
CHARACTERS_TAB = "[role='tab']:has-text('Characters'):visible"
ADD_TO_PROMPT_BTN = "button:has-text('Add to prompt'):visible"
# The "Select media" dialog lists project assets as selectable option nodes
# inside a listbox[aria-label='Asset list']; match by filename.
ASSET_LISTBOX = "[aria-label='Asset list']:visible"
# Any of these present means we reached the usable tool (not the marketing page).
ENTERED_HINTS = [
    "[role='textbox'][contenteditable='true']",
    "[contenteditable='true']",
    "div:has-text('What do you want to create')",
]
# Buttons to click through on the way to the editor (Flow's landing screen
# sits in front of the tool since Aug 2026 redesign).
ENTRY_CLICKS = ["Create with Google Flow", "New project", "Create"]

# Money-path constants (Beat 2): Flow PRO shows an "Approve N credits" modal
# before every generation. Clicking confirm is the ONLY action that spends paid
# credits, so approval selectors are scoped to a real overlay marker and never
# matched page-wide, where an unrelated Continue/OK/Yes button could trigger a
# surprise paid generation.
APPROVE_HINTS = [
    "button:has-text('Approve'):visible",
    "button:has-text('Confirm'):visible",
    "button:has-text('Generate, approve'):visible",
]
GENERIC_CONFIRM_HINTS = [
    "button:has-text('Continue'):visible",
    "button:has-text('OK'):visible",
    "button:has-text('Yes'):visible",
]
# Overlay markers that identify Flow's credit modal, in priority order. Flow's
# dialog role is NOT pinned to [role='dialog'] in-repo, so accept any real
# modal marker; the double-charge guard is "never page-wide", not "role must
# be dialog".
APPROVAL_SCOPES = [
    "[role='dialog'] ",
    "[role='alertdialog'] ",
    "[aria-modal='true'] ",
]
# A downloaded-but-unreadable file is usually the render still finishing; wait
# and re-download (never re-generate) this many times before giving up.
REDOWNLOAD_RETRIES = 2


def _approval_candidates() -> list[tuple[str, str]]:
    """(scope, selector) pairs tried in click order while approving credits.

    Every scope is a real modal overlay marker (role=dialog / alertdialog /
    aria-modal) — NEVER page-wide — so a stray Continue/OK/Yes button in the
    page background can never be clicked (double-charge guard). Pure seam,
    unit-tested without a browser."""
    return [
        (f"{scope}{sel}", sel)
        for sel in APPROVE_HINTS + GENERIC_CONFIRM_HINTS
        for scope in APPROVAL_SCOPES
    ]


def _is_generation_finished(
    *, has_stop: bool, vids: int, has_download: bool, has_done_btn: bool
) -> bool:
    """Completion predicate (pure seam, unit-tested without a browser).

    Done means the 'Stop' control is gone AND a real result exists (a visible
    <video>, a download control, or a completion 'Done' button). Placeholder
    editor chrome (title / timeline / media thumbnail) is NOT a completion
    signal: judging 'done' from it could fire a second paid generation while
    Veo is still rendering — that is the double-charge we harden against."""
    if has_stop:
        return False
    return vids > 0 or has_download or has_done_btn


def _clip_is_real_video(path: Path) -> bool:
    """Download-verify: true when the saved file is a real, readable video.

    Matches ``evaluate_final``'s verification contract: when ffprobe is
    UNAVAILABLE the gate passes on file size alone — a valid clip is never
    re-generated just because nothing could probe it (re-generating would
    charge credits twice). When ffprobe IS available, the file must be
    non-empty and carry a real video stream; anything unreadable fails."""
    if not Path(path).exists():
        return False
    try:
        if Path(path).stat().st_size == 0:
            return False
    except OSError:
        return False
    if not cfg.ffprobe_binary():
        return True  # verification unavailable -> pass-on-size (mirror evaluate_final)
    probe = merger.probe_media(path)
    return bool(probe and probe.get("has_video"))


def _in_viewport(locator) -> bool:
    """True when the element has a real box inside the current viewport.
    Flow's marketing page hides CTAs in a long side-scrolling rail (huge x /
    y offsets) that Playwright refuses to click ("outside of the viewport")."""
    box = locator.bounding_box()
    if not box:
        return False
    # Use 1500 as a generous upper bound — covers 720p, 1080p, and 4K screens
    # while still filtering out elements with absurd y-offsets (Flow's rail).
    return box["x"] >= -5 and box["y"] >= -5 and box["y"] < 1500 and box["width"] > 0


def validate_reference_image(image_path: str | None) -> str:
    """Pure guard for the presenter reference image (paid-account safety).

    Returns the path if it is usable (non-empty and exists on disk); raises
    FlowAutomationError otherwise. Kept side-effect-free so CI can test it
    without a browser — the same check `_add_reference_image` relies on."""
    if not image_path:
        return ""
    if not Path(image_path).exists() or Path(image_path).stat().st_size == 0:
        raise FlowAutomationError(
            f"reference image not found or empty on disk: {image_path!r}"
        )
    return image_path


class FlowAutomationError(RuntimeError):
    pass


# Google SSO session cookies (names stable for many years). Presence means the
# persistent profile holds a real signed-in Google session — far more concrete
# than scanning page text for "sign in", which survives on many logged-in pages.
GOOGLE_SESSION_COOKIES = {
    "SID",
    "SAPISID",
    "SIDCC",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
}


def _has_google_session(cookies: list[dict[str, object]]) -> bool:
    """True if any Google SSO auth cookie is present in the profile's jars."""
    return any(c.get("name") in GOOGLE_SESSION_COOKIES for c in cookies)


class FlowClipper:
    """Drives Google Flow to produce one timed clip from one prompt."""

    def __init__(
        self,
        *,
        headless: bool | None = None,
        profile_dir: Path | None = None,
        manifest: Callable[[str], None] | None = None,
    ) -> None:
        from playwright.sync_api import sync_playwright  # deferred import

        self._sync = sync_playwright
        self.headless = cfg.flow_headless() if headless is None else headless
        self.profile_dir = profile_dir or cfg.browser_profile_dir()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = manifest or (lambda msg: print(f"[flow] {msg}"))
        self._browser = None
        self._credits_approved = False  # once per clip (Beat 2 money-path guard)
        self._run_credits_approved = False  # once per run: the day must see its money gate

    def __enter__(self) -> "FlowClipper":
        import playwright.sync_api

        self._pw = self._sync().start()
        channel = "chrome" if _system_chrome() else None
        try:
            self._browser = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                channel=channel,
                args=[
                    "--no-first-run",
                    "--disable-default-apps",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except playwright.sync_api.Error as exc:  # type: ignore[attr-defined]
            self._pw.stop()
            raise FlowAutomationError(
                f"Could not launch Chromium with profile {self.profile_dir}. "
                f"Run `python -m playwright install chromium` first, or put a "
                f"signed-in Chrome profile on disk. Underlying: {exc}"
            ) from exc
        return self

    def __exit__(self, *exc) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001 - close must never mask real errors
                pass
        self._pw.stop()

    # --- public API -----------------------------------------------------------------
    def new_page(self):
        """Create a new page in the persistent browser context.

        Callers must close the page before the FlowClipper context exits.
        Preferred over accessing ``_browser`` directly."""
        return self._browser.new_page()

    def sign_in_required(self) -> bool:
        """Best-effort check for an active Google session on the Flow page."""
        page = self._browser.new_page()
        try:
            page.goto(cfg.flow_url(), wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
            text = page.content().lower()
            return "sign in" in text or "log in" in text or "accounts.google.com/signin" in text
        finally:
            page.close()

    def wait_for_sign_in(self, timeout_s: int = 600) -> bool:
        """MANUAL LOGIN GATE — the only sanctioned way to give this agent
        access to a Google account.

        Opens Flow in a HEADED window with the persistent profile and waits
        for the human to sign in with their own credentials (the account that
        holds their Google PRO plan). Credentials and 2FA codes never touch the
        agent, files, env, or git — only the saved browser session in
        ``.runtime/flow-profile/`` is reused on every later run.

        Returns True when a Google session exists; False if it timed out.
        """
        page = self._browser.new_page()
        try:
            page.goto(cfg.flow_url(), wait_until="domcontentloaded", timeout=60_000)
            print("\n============================================================")
            print("SIGN-IN GATE")
            print("In the browser window that just opened, sign in with the")
            print("Google account that has your PRO plan (Flow).")
            print("The agent never sees your password or 2FA code — it only")
            print("reuses this session afterwards. Close the window when done.")
            print("============================================================\n")
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                try:
                    cookies = self._browser.cookies()
                except Exception:  # window closed / browser gone by the human
                    print("[flow] browser window closed — stopping the gate")
                    return False
                if _has_google_session(cookies):
                    print("[flow] Google session detected — profile is fully signed in.")
                    return True
                try:
                    on_login_page = "accounts.google.com" in page.url
                except Exception:
                    on_login_page = True
                print("[flow] waiting for sign-in..." + (" (on accounts.google.com)" if on_login_page else ""))
                time.sleep(5)
            print(f"[flow] sign-in gate timed out after {timeout_s}s — run --login again")
            return False
        finally:
            page.close()

    def generate_clip(self, prompt: str, output_path: Path,
                      reference_image: str | None = None) -> None:
        """Generate one clip for `prompt` and save it to output_path.

        `reference_image` (presenter scenes only): a local image used to
        build a Flow Character so Veo uses the same young man as a consistent
        on-screen presenter.  The Character pipeline (MCP-verified Sep 2026)
        is: Upload via menu -> Characters -> Add from project -> Add media ->
        Done.  Then the character is attached to the prompt via the ingredients
        picker (Characters tab -> Add to prompt)."""
        self._credits_approved = False  # once per generate_clip call (clip-scoped)
        page = self._browser.new_page()
        page.set_default_timeout(60_000)
        try:
            page.goto(cfg.flow_url(), wait_until="domcontentloaded", timeout=60_000)
            self._enter_workspace(page)   # Flow's landing -> project workspace
            project_url = page.url.split("?")[0]   # for download crash-recovery
            if reference_image:
                self._ensure_presenter_character(page, reference_image)
            self._fill_prompt(page, prompt)
            if reference_image:
                if not self._attach_character_to_prompt(page):
                    raise FlowAutomationError(
                        "presenter character was NOT attached to the prompt — "
                        "refusing to generate a presenter clip without the "
                        "reference image in the prompt (paid-account guard)."
                    )
            self._select_video_mode(page)   # Image->Video toggle + model + FLOW_ASPECT
            self._click_generate(page)
            self._approve_credits(page)   # "Approve N credits" dialog (Flow PRO)
            self._wait_until_finished(page)
            try:
                self._download_clip(page, output_path)
            except Exception as exc:
                # A download that crashes the browser has ALREADY spent the
                # generation credits. NEVER silently re-generate — reconnect to
                # the SAME project and try to re-download the finished clip once.
                self.manifest(
                    f"download failed ({type(exc).__name__}); "
                    "trying in-project re-download (no re-generation)"
                )
                if not self._recover_download(project_url, output_path):
                    raise
            self._ensure_real_video(page, output_path)   # never re-generate, re-download
        except Exception as exc:
            self.manifest(f"AUTO-STEP FAILED ({type(exc).__name__}): {exc}")
            if reference_image and isinstance(exc, FlowAutomationError):
                raise
            self._manual_assist(prompt, output_path)
        finally:
            page.close()

    # --- internals (each best-effort, degrade to manual-assist) ---------------------
    def _enter_workspace(self, page) -> None:
        """Flow's public landing page sits in front of the tool now (Aug 2026
        redesign), and an unauthenticated profile lands on the marketing screen
        (Sep 2026: flow.google.com/about). Click the in-viewport CTA -> New
        project (workspace) -> editor. A signed-out profile (accounts.google
        redirect) or an unreachable editor is a FAIL-FAST error — never click
        around blind and never run generation without the editor."""
        for _ in range(8):
            if page.locator(", ".join(ENTERED_HINTS)).count() > 0:
                self.manifest("entry: editor prompt box detected")
                return
            if "accounts.google.com" in page.url:
                raise FlowAutomationError(
                    "Flow profile is signed out (redirected to Google sign-in). "
                    "Re-sign in the flow-profile browser once, then retry."
                )
            clicked = False
            for name in ENTRY_CLICKS:
                btn = page.get_by_role("button", name=name).first
                if btn.count() == 0 or not _in_viewport(btn):
                    continue
                try:
                    btn.click(timeout=8_000)
                    self.manifest(f"entry: clicked '{name}'")
                    clicked = True
                    break
                except Exception:
                    continue
            time.sleep(10 if clicked else 5)  # SPA hops take a moment
        self.manifest("entry: no editor prompt box found")
        raise FlowAutomationError(
            "could not reach the Flow editor — profile signed out or the "
            "landing CTAs changed. Re-sign in the flow-profile browser once, "
            "then retry."
        )

    def _select_video_mode(self, page) -> None:
        """Flow's bottom toolbar chip carries the generation settings: Image/Video
        toggle, model (Veo), duration, aspect ratio, and output count.

        Live-verified Sep 2026 on the current Flow DOM:
          - 'Settings trigger' chip opens the menu; inside, settings are
            [role=radio] buttons (Mode, Video type, Aspect ratio, Output
            count) plus a 'Select model family' button whose popover is made
            of [role=menuitem] items (Omni 1.1 Flash / Veo 3.1 - Lite /
            Fast / Quality).
          - A FRESH project already defaults to most of the wanted state:
            Video mode, Ingredients video-type, x1, Veo 3.1 - Lite,
            720p, 8s. The aspect is ENFORCED from cfg.flow_aspect()
            (FLOW_ASPECT; user-requested 16:9 Sep 2026).
          - The resolution/duration radios ONLY render while the model family
            is 'Omni 1.1 Flash'. Selecting Veo hides them and pins the
            duration to 8s, so 10s clips are NOT reachable via this menu under
            Veo (current Flow behavior; live-verified). This code sets them
            when present and otherwise leaves the Veo default (720p, 8s).
          - Older versions captured the popover via 'menuitem' selectors and
            CORRUPTED this menu (image mode / Nano Banana / 16:9 / x2). This
            version only ENFORCES the wanted radios via role=name clicks."""
        def _menu_items():
            """(element, text) pairs for the currently-open model popover."""
            out = []
            seen = set()
            for it in page.locator("[role='menuitem']:visible").all()[:40]:
                try:
                    t = " ".join(it.inner_text().split())
                except Exception:
                    continue
                if not t or len(t) > 80 or t in seen:
                    continue
                seen.add(t)
                out.append((it, t))
            return out

        def _open_bottom_toolbar_menu() -> bool:
            """Open the 'Settings trigger' menu (current DOM) with a guarded
            fallback for older layouts. Only opens menus that look like the
            generation settings popover; never clicks unrelated controls."""
            for sel in PROMPT_FIELD_HINTS:
                box = page.locator(sel).first
                if box.count():
                    try:
                        box.click(timeout=3_000)
                    except Exception:
                        pass
                    break
            page.wait_for_timeout(1500)
            settings = page.get_by_role("button", name="Settings trigger")
            if settings.count() > 0:
                try:
                    settings.first.click(timeout=3_000)
                    page.wait_for_timeout(1000)
                    if page.locator("[role='radio']:visible").count() > 0:
                        self.manifest("toolbar: opened Settings trigger menu")
                        return True
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                except Exception:
                    pass
            for btn in page.locator("button[aria-haspopup='menu']:visible").all():
                try:
                    label = " ".join((btn.get_attribute("aria-label") or btn.inner_text() or "").split())
                    bb = btn.bounding_box()
                    if not bb or not label or bb['y'] < 400:
                        continue
                    if any(skip in label.lower() for skip in
                           ['project', 'sort', 'filter', 'more options', 'search']):
                        continue
                    if any(kw in label.lower() for kw in
                           ['video', 'image', '720p', '1080p', '480p', 'crop', 'model',
                            'nano', 'veo', 'banana']):
                        btn.click(timeout=3_000)
                        page.wait_for_timeout(800)
                        if page.locator("[role='radio']:visible").count() > 0:
                            self.manifest(f"toolbar: opened bottom chip '{label[:40]}'")
                            return True
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(300)
                except Exception:
                    continue
            return False

        def _click_radio(name: str) -> bool:
            """Click the [role=radio] with accessible name `name` if it is not
            already checked. Returns True only on an actual change."""
            for el in page.get_by_role("radio", name=name, exact=True).all():
                try:
                    if el.get_attribute("aria-checked") == "true":
                        return False
                    el.click(timeout=3_000)
                    return True
                except Exception:
                    continue
            return False

        def _ensure_model_veo_lite() -> bool:
            """Open the model-family popover and pick 'Veo 3.1 - Lite' unless
            the current model already is a Veo family."""
            btn = page.get_by_role("button", name="Select model family")
            if btn.count() == 0:
                return False
            try:
                label = " ".join(btn.first.inner_text().split()).lower()
            except Exception:
                label = ""
            if "veo" in label:
                return False
            try:
                btn.first.click(timeout=3_000)
                page.wait_for_timeout(800)
            except Exception:
                return False
            for el in page.get_by_role("menuitem", name="Veo 3.1 - Lite", exact=True).all():
                try:
                    el.click(timeout=3_000)
                    page.wait_for_timeout(800)
                    return True
                except Exception:
                    continue
            return False

        changed = []
        if not _open_bottom_toolbar_menu():
            self.manifest("no settings menu found; leaving toolbar defaults")
            return
        if _click_radio("Video"):
            changed.append("mode->Video")
            page.wait_for_timeout(1000)
        _click_radio("Ingredients")
        aspect_target = cfg.flow_aspect()
        if _click_radio(aspect_target):
            changed.append(f"aspect->{aspect_target}")
        if _click_radio("x1"):
            changed.append("count->x1")
        if _ensure_model_veo_lite():
            changed.append("model->Veo 3.1 Lite")
            page.wait_for_timeout(800)
        # Resolution/duration are only rendered while the family is Omni Flash;
        # under Veo they are hidden (8s is the UI's pinned default). Best-effort:
        if _click_radio("720p"):
            changed.append("res->720p")
        if _click_radio("10s"):
            changed.append("dur->10s")
        page.keyboard.press("Escape")
        self.manifest("generation menu set: " + (", ".join(changed) if changed else "defaults already correct"))

    def _fill_prompt(self, page, prompt: str) -> None:
        """Type the generation prompt into the Flow editor's prompt box.

        When a presenter Character has been built via
        ``_ensure_presenter_character``, Veo automatically uses it as the
        on-screen presenter — no @-mention ingredient needed in the prompt
        text itself."""
        for sel in PROMPT_FIELD_HINTS:
            el = page.locator(sel).first
            if el.count() == 0 or not el.is_visible():
                self.manifest(f"prompt field: '{sel}' not found/visible, trying next")
                continue
            try:
                el.click(timeout=5_000)
                el.fill(prompt, timeout=5_000)
                self.manifest(f"prompt typed into '{sel}'")
                return
            except Exception:
                continue
        raise FlowAutomationError("no prompt field found")

    def _upload_reference_image(self, page, image_path: str) -> None:
        """Upload the reference image to Flow's project library via the menu-driven
        upload flow (no hidden file inputs — Flow removed them Sep 2026).

        Pipeline: Add media menu -> Upload menuitem -> file chooser -> image in library."""
        name = Path(image_path).name
        if not image_path or not Path(image_path).exists():
            raise FlowAutomationError(
                f"reference image not found on disk: {image_path!r}"
            )
        # Wait for the editor to fully mount (SPA transition after New project)
        # Use getByRole which is more reliable than CSS selectors for Flow's DOM.
        add_menu = None
        for _ in range(10):
            btn = page.get_by_role("button", name="Add media menu").first
            if btn.count() > 0:
                add_menu = btn
                break
            # fallback: try partial text match
            btn2 = page.locator("button:has-text('Add media')").first
            if btn2.count() > 0:
                add_menu = btn2
                break
            page.wait_for_timeout(2000)
        if add_menu is None:
            self._dump_controls(page)
            raise FlowAutomationError("could not find 'Add media menu' button after waiting")

        add_menu.click(timeout=6_000)
        page.wait_for_timeout(800)
        self.manifest("ref: opened Add media menu")

        # Click "Upload" menuitem → triggers file chooser
        upload_item = page.get_by_role("menuitem", name="Upload").first
        if upload_item.count() == 0:
            upload_item = page.locator(UPLOAD_MENUITEM).first
        if upload_item.count() == 0:
            self._dump_controls(page)
            raise FlowAutomationError("could not find 'Upload' menuitem")
        with page.expect_file_chooser(timeout=10_000) as fc_info:
            upload_item.click(timeout=6_000)
        file_chooser = fc_info.value
        file_chooser.set_files(str(image_path))
        page.wait_for_timeout(4000)  # wait for upload to settle
        self.manifest(f"ref: uploaded {name} into library")

    def _ensure_presenter_character(self, page, image_path: str) -> None:
        """Create a Flow "Character" from a presenter reference image so the
        young man appears as a consistent on-screen presenter.

        MCP-verified pipeline (live PRO account, Sep 2026):
          1. Upload image via Add media menu -> Upload -> file chooser
          2. Navigate to Characters section
          3. Check if character already exists → skip if found
          4. "Add from project" -> select image in dialog -> "Add media"
             -> character page opens -> "Done" to save

        CRITICAL (paid-account guard): raises FlowAutomationError if the
        character cannot be confirmed created, so generate_clip refuses to burn
        credits on a presenter scene without the user's image."""
        name = Path(image_path).name
        if not image_path or not Path(image_path).exists():
            raise FlowAutomationError(
                f"reference image not found on disk: {image_path!r}"
            )

        # 1. Upload image into the project library via menu-driven upload
        #    (must be done from the editor page where "Add media menu" is visible)
        self._upload_reference_image(page, image_path)
        self.manifest(f"char: uploaded {name} into library")

        # 2. Navigate to Characters section in the sidebar
        chars_nav = page.locator("text=Characters").first
        if chars_nav.count() > 0:
            try:
                chars_nav.click(timeout=6_000)
                self.manifest("char: clicked Characters nav")
                page.wait_for_timeout(3000)
            except Exception:
                pass
        else:
            project_base = page.url.split("?")[0].split("/character")[0].rstrip("/")
            page.goto(project_base + "/character",
                      wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)

        # 3. Check if character already exists in the Characters section
        existing_char = page.locator("img[alt='Character thumbnail']").first
        existing_char_text = page.locator("text=Untitled character").first
        if existing_char.count() > 0 or existing_char_text.count() > 0:
            self.manifest("char: character already exists in project, skipping creation")
            return

        # 4. Click "Add from project" to open the media picker dialog
        add_proj = page.locator(ADD_FROM_PROJECT_BTN).first
        if add_proj.count() == 0:
            # retry after a moment — the button may mount after page settles
            page.wait_for_timeout(2000)
            add_proj = page.locator(ADD_FROM_PROJECT_BTN).first
        if add_proj.count() == 0:
            self._dump_controls(page)
            raise FlowAutomationError(
                f"could not find 'Add from project' button for {name} "
                "(paid-account guard)."
            )
        add_proj.click(timeout=6_000)
        page.wait_for_timeout(1500)
        self.manifest("char: opened Add from project dialog")

        # 5. In the "Select media" dialog, pick the asset by its filename
        #    The dialog has a listbox[aria-label='Asset list'] with option elements.
        #    NOTE (Sep 2026, live-verified): the dialog AUTO-SELECTS the most
        #    recent asset (aria-selected="true"); clicking an already-selected
        #    option DESELECTS it and hides the 'Add media' button. Only click
        #    when the target asset is not already selected.
        picked = False
        target_opt = page.locator(f"[role='option']:has-text('{name}')").first
        if target_opt.count() == 0:
            target_opt = page.locator(f"[role='listitem']:has-text('{name}')").first
        if target_opt.count() > 0:
            if target_opt.get_attribute("aria-selected") == "true":
                picked = True
                self.manifest(f"char: asset {name} already selected in dialog")
            else:
                try:
                    target_opt.click(timeout=6_000)
                    picked = True
                    self.manifest(f"char: picked asset {name} from dialog")
                except Exception:
                    pass
        if not picked:
            # fallback: click the first option in the asset list (respecting the
            # already-selected guard above)
            first_opt = page.locator("[role='option']:visible").first
            if first_opt.count() > 0:
                try:
                    if first_opt.get_attribute("aria-selected") != "true":
                        first_opt.click(timeout=6_000)
                    picked = True
                    self.manifest("char: picked first available asset")
                except Exception:
                    pass
        if not picked:
            self._dump_controls(page)
            raise FlowAutomationError(
                f"could not pick asset {name} in media dialog (paid-account guard)."
            )

        # 6. Click "Add media" button in the dialog to confirm selection.
        #    The button can render slightly after selection — poll briefly.
        add_media_btn = None
        for _ in range(8):
            cand = page.locator(ADD_MEDIA_IN_DIALOG).first
            if cand.count():
                add_media_btn = cand
                break
            page.wait_for_timeout(500)
        if add_media_btn is None:
            # some layouts auto-navigate to character page on asset click
            if "/character/" in page.url:
                self.manifest("char: auto-navigated to character page")
            else:
                self._dump_controls(page)
                raise FlowAutomationError(
                    f"could not find 'Add media' button in dialog for {name}."
                )
        else:
            add_media_btn.click(timeout=6_000)
            page.wait_for_timeout(2000)
            self.manifest("char: clicked Add media in dialog")

        # 7. Character page should now be open — click "Done" to save
        #    Wait for the Done button to appear (the page may take time to load)
        done_btn = page.locator(CHARACTER_DONE_BTN).first
        for _ in range(10):
            if done_btn.count() > 0:
                break
            page.wait_for_timeout(1500)
            done_btn = page.locator(CHARACTER_DONE_BTN).first
        if done_btn.count() == 0:
            # Also try role-based selector
            done_btn = page.get_by_role("button", name="Done").first
        if done_btn.count() == 0:
            self._dump_controls(page)
            raise FlowAutomationError(
                f"could not find 'Done' button on character page for {name}."
            )
        done_btn.click(timeout=6_000)
        page.wait_for_timeout(1500)
        self.manifest(f"char: presenter character saved from {name}")

        # 8. Return to the project editor
        #    After Done, we might be on the character page or the project page.
        #    Reload the project root to ensure a clean editor state.
        project_base = page.url.split("?")[0].split("/character")[0].rstrip("/")
        page.goto(project_base, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        # If the editor prompt box is not visible, try clicking through entry CTAs
        for _ in range(6):
            if page.locator(", ".join(ENTERED_HINTS)).count():
                self.manifest("char: back in project editor")
                return
            for name in ENTRY_CLICKS:
                btn = page.get_by_role("button", name=name).first
                if btn.count() > 0:
                    try:
                        btn.click(timeout=5_000)
                        page.wait_for_timeout(3000)
                        break
                    except Exception:
                        continue
            if page.locator(", ".join(ENTERED_HINTS)).count():
                self.manifest("char: back in project editor after entry click")
                return
        # Last resort: reload the page
        page.reload(wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        if page.locator(", ".join(ENTERED_HINTS)).count():
            self.manifest("char: back in project editor after reload")
            return
        self._dump_controls(page)
        raise FlowAutomationError(
            f"character saved but could not return to the editor for {name}."
        )

    def _attach_character_to_prompt(self, page, character_name: str = "Untitled character") -> bool:
        """Attach a saved Character to the prompt via the ingredients picker.

        Pipeline (MCP-verified Sep 2026):
          1. Click "Add ingredients to the prompt box" button
          2. Select the character from the asset list
          3. Confirm a character chip actually landed in the prompt editor.
             The chip renders OUTSIDE the contenteditable as a sibling
             `div.chip-image-wrapper > img[alt='Character ingredient image']`
             (contenteditable-scoped checks were a false negative); a picker
             thumbnail ('Character thumbnail') is NOT proof of attach.

        Returns True only when the ingredient chip is verified inside the
        editor; generate_clip refuses to run a presenter scene without it."""
        def _editor_has_ingredient() -> bool:
            ed = page.locator("[contenteditable='true']:visible").first
            # Sep 2026: the ingredient chip renders OUTSIDE the contenteditable
            # as `div.chip-image-wrapper > img[alt='Character ingredient image']`
            # beside the prompt box (Flow's `flow-base-prompt-box`). Scope by the
            # chip's own alt first (never the picker 'Character thumbnail'), then
            # fall back to the contenteditable-scoped variants.
            chip = page.locator("img[alt*='ingredient' i]").first
            if chip.count() > 0 and chip.is_visible():
                return True
            if ed.count() == 0:
                return False
            chip_ed = page.locator(
                "div[contenteditable='true'] img[alt*='Character' i],"
                "div[contenteditable='true'] img[alt*='ingredient' i]"
            ).first
            if chip_ed.count() > 0:
                return True
            try:
                return ("@" + character_name) in (ed.inner_text() or "")
            except Exception:
                return False

        def _try_attach_once(attempt: int) -> bool:
            """Open picker -> Characters tab -> click character -> poll for chip.

            Returns True only when the ingredient chip is verified in the editor
            (a picker thumbnail is NOT proof of attach). Credit-free; safe to retry."""
            ing_btn = page.get_by_role("button", name="Add ingredients to the prompt box").first
            if ing_btn.count() == 0:
                ing_btn = page.locator(ADD_INGREDIENTS_BTN).first
            if ing_btn.count() == 0:
                ing_btn = page.locator("button:has-text('Add ingredients')").first
            if ing_btn.count() == 0:
                self.manifest("ingredients: 'Add ingredients' button not found")
                return False
            ing_btn.click(timeout=6_000)
            page.wait_for_timeout(1500)
            self.manifest("ingredients: opened picker")

            # The Sep 2026 picker tabs content by type (All / Images / Videos /
            # Voices / Characters / Avatars / Uploads). Characters only appear
            # under the Characters tab — searching the default "All" tab finds
            # nothing (the regression the old 'thumbnail' check masked).
            chars_tab = page.get_by_role("tab", name="Characters", exact=True).first
            if chars_tab.count() > 0:
                try:
                    chars_tab.click(timeout=6_000)
                    page.wait_for_timeout(1500)
                    self.manifest("ingredients: switched to Characters tab")
                except Exception:
                    pass

            char_option = page.locator(f"[role='option']:has-text('{character_name}')").first
            if char_option.count() == 0:
                char_option = page.locator(f"[role='listitem']:has-text('{character_name}')").first
            if char_option.count() == 0:
                char_option = page.locator("[role='option']:visible").first
            if char_option.count() == 0:
                self.manifest(f"ingredients: character '{character_name}' not found in list")
                page.keyboard.press("Escape")
                return False
            char_option.click(timeout=6_000)
            # A freshly created character's first insert can settle late
            # (and occasionally skip in headed mode) — poll up to ~6s.
            for _ in range(12):
                page.wait_for_timeout(500)
                if _editor_has_ingredient():
                    self.manifest(f"ingredients: attached character '{character_name}' to prompt")
                    return True
            self.manifest(f"ingredients: attempt {attempt} clicked character '{character_name}' (attach unconfirmed)")
            return False

        # 1+2+3. Retry the picker insert up to 3x. Credit-free; the chip
        #         verification refuses false positives, so a flake never burns a
        #         generation credit nor attaches the wrong thing.
        for attempt in range(1, 4):
            if _try_attach_once(attempt):
                return True
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(1000)
            if _editor_has_ingredient():
                self.manifest(f"ingredients: attached character '{character_name}' (post-close)")
                return True

        # 4. The click may have only previewed the character — use the picker's
        #    explicit insert control if one is visible.
        for sel in ("button:has-text('Add to prompt')", "button:has-text('Insert')"):
            ctrl = page.locator(sel).first
            if ctrl.count() == 0 or not ctrl.is_visible():
                continue
            try:
                ctrl.click(timeout=6_000)
                page.wait_for_timeout(1200)
                if _editor_has_ingredient():
                    self.manifest(f"ingredients: inserted '{character_name}' via '{sel}'")
                    return True
            except Exception:
                continue

        # 5. Close the picker and re-check once more
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        if _editor_has_ingredient():
            self.manifest(f"ingredients: attached character '{character_name}' (post-close)")
            return True
        self.manifest(f"ingredients: character '{character_name}' NOT attached to prompt")
        return False

    def _generation_in_progress(self, page) -> bool:
        """True while Flow is rendering a clip: the pre-2026 'Stop' control, a
        real progressbar element, or any visible '%NN' text (Sep 2026 UI shows
        a percent chip like 'play_circle 42%' instead of a Stop button)."""
        try:
            if page.locator("button:has-text('Stop'):visible").count() > 0:
                return True
            if page.locator("[role='progressbar']:visible").count() > 0:
                return True
            return page.get_by_text(re.compile(r"\d+\s*%")).count() > 0
        except Exception:
            return False

    def _click_generate(self, page) -> None:
        """Click the generate/create button. Some buttons start disabled
        (aria-disabled='true') while the prompt is being processed — wait
        for them to become enabled before clicking."""
        for sel in GENERATE_HINTS:
            el = page.locator(sel).first
            if el.count() == 0 or not el.is_visible():
                continue
            # Wait up to 30s for the button to become enabled
            for _ in range(15):
                try:
                    disabled = el.get_attribute("aria-disabled")
                except Exception:
                    disabled = None
                if disabled != "true":
                    break
                page.wait_for_timeout(2000)
            try:
                el.click(timeout=8_000)
            except Exception:
                continue
            self.manifest("generate clicked")
            # Post-click sanity (Sep 2026 UI): confirm something actually
            # started — progress ('Stop' / progressbar / percent chip), an
            # already-rendered video, or an approval dialog — so a silently
            # failed click is caught in 20s instead of a 900s generation wait.
            for _ in range(20):
                started = (
                    self._generation_in_progress(page)
                    or page.locator("video:visible").count() > 0
                    or page.locator("[role='dialog']:visible").count() > 0
                )
                if started:
                    return
                page.wait_for_timeout(1000)
            raise FlowAutomationError(
                "generate clicked but no generation started within 20s (no "
                "progress control, no video, no approval dialog) — aborted "
                "before anything could be charged"
            )
        raise FlowAutomationError("no generate button found")

    def _approve_credits(self, page) -> None:
        """Money gate (live-verified Sep 2026): the current Flow UI consumes the
        account's FREE daily credits silently — no modal — and only shows an
        approval dialog when a paid generation is attempted.

        Policy:
          - No approval dialog detected -> free-credit generation: accept.
          - Approval dialog detected:
              * FLOW_APPROVE_CREDITS=1 (supervised runs only) -> click it once.
              * otherwise -> HARD STOP (never auto-spend paid credits).
          - FLOW_CREDITS_PREAPPROVED=1 still bypasses the gate entirely (compat).
        Approval clicks, when they happen, are scoped to a real overlay marker
        (role=dialog / alertdialog / aria-modal), never page-wide, so a stray
        Continue/OK/Yes button in the page background cannot spend credits."""
        if self._credits_approved:
            self.manifest("credits already approved this clip")
            return
        if self._run_credits_approved:
            # Free-credit mode already confirmed earlier in this run — no need
            # to re-scan for a dialog on every clip.
            self._credits_approved = True
            return
        if cfg.env_or("FLOW_CREDITS_PREAPPROVED", "").strip().lower() in ("1", "true", "yes"):
            self._run_credits_approved = True
            self.manifest("FLOW_CREDITS_PREAPPROVED=1 set; skipping credit dialog gate")
            return
        auto_approve = cfg.env_or("FLOW_APPROVE_CREDITS", "").strip().lower() in ("1", "true", "yes")
        for _ in range(5):
            for scope, sel in _approval_candidates():
                el = page.locator(scope).first
                if el.count() == 0 or not el.is_visible():
                    continue
                if auto_approve:
                    try:
                        el.click(timeout=4_000)
                        self._credits_approved = True
                        self._run_credits_approved = True
                        self.manifest(f"approved credits via '{scope}{sel}'")
                        return
                    except Exception:
                        continue
                raise FlowAutomationError(
                    "PAID credit-approval dialog detected and FLOW_APPROVE_CREDITS "
                    "is not set — refusing to spend money automatically. Approve "
                    "manually in the browser, or set FLOW_APPROVE_CREDITS=1 only "
                    "for a supervised (Gate 5) run."
                )
            time.sleep(2)
        # No dialog appeared before generation started: Flow is consuming the
        # account's FREE daily credits (current UI). Accept and remember.
        self._credits_approved = True
        self._run_credits_approved = True
        self.manifest("no credit dialog — free-credit generation accepted (daily budget)")

    def _wait_until_finished(self, page) -> None:
        deadline = time.time() + 900  # Flow generations can take 5-12 min (Veo 3.1 Lite)
        while time.time() < deadline:
            elapsed = int(time.time() - (deadline - 900))
            # A running generation shows a "Stop" control on the submit button,
            # a progressbar, or a percent chip (Sep 2026 UI); when none is
            # present AND a result (video or download control) exists, the
            # generation is truly done.
            generating = self._generation_in_progress(page)
            if not generating:
                vids = page.locator("video:visible").count()
                dl = any(page.locator(s).count() > 0 for s in DOWNLOAD_HINTS)
                done_btn = page.locator("button:has-text('Done'):visible").count() > 0
                if _is_generation_finished(
                    has_stop=generating, vids=vids,
                    has_download=dl, has_done_btn=done_btn,
                ):
                    self.manifest("generation finished (result present)")
                    return
            if elapsed % 60 == 0:
                self.manifest(f"waiting for generation... ({elapsed}s)")
            time.sleep(6)
        raise FlowAutomationError("generation did not finish in 900s")

    def _download_clip(self, page, output_path: Path) -> None:
        """Flow's download path. Primary (MCP-verified Aug 2026): a visible
        'Download' control whose accessible name matches /download/i — on the
        editor view the top-bar button 'download Download' saves the resolved
        MP4 directly (no 3-dots, no resolution submenu). Fallback: hover the
        finished video tile -> the tile's top-left overflow (more_vert / 3 dots)
        -> 'Download' -> pick a resolution (720p) -> the browser starts a
        download."""
        def _inside(box, other, margin=10):
            return (other["x"] >= box["x"] - margin and other["y"] >= box["y"] - margin
                    and other["x"] + other["width"] <= box["x"] + box["width"] + margin
                    and other["y"] + other["height"] <= box["y"] + box["height"] + margin)

        def _tile_box():
            tile = page.locator("video:visible, img[src*='media']:visible, img[src*='blob']:visible").first
            if tile.count() == 0:
                return None
            try:
                tile.hover(timeout=4_000)
                page.wait_for_timeout(2000)
                return tile.bounding_box()
            except Exception:
                return None

        def _click_downloadish():
            cands = [
                # MCP-verified (Aug 2026): editor top-bar button whose accessible
                # name is 'download Download' saves the resolved MP4 directly.
                "button[aria-label*='Download' i]:visible",
                "button[aria-label*='download' i]:visible",
            ] + DOWNLOAD_HINTS + [
                "button:has-text('Download file'):visible",
                "button:has-text('Export'):visible",
            ]
            for sel in cands:
                el = page.locator(sel).first
                if el.count() == 0 or not el.is_visible():
                    continue
                try:
                    with page.expect_download(timeout=120_000) as dl_info:
                        el.click(timeout=5_000)
                        page.wait_for_timeout(8000)
                    dl_info.value.save_as(str(output_path))
                    self.manifest(f"saved clip -> {output_path}")
                    return True
                except Exception as exc:
                    self.manifest(f"download via '{sel}' failed ({type(exc).__name__})")
                    continue
            return False

        # path 1 (primary, MCP-verified): any visible Download control — the
        # editor top-bar button 'download Download' saves the resolved MP4
        # directly. Priority over the tile-overflow path below.
        if _click_downloadish():
            return

        box = _tile_box()
        if box:
            # path 2: hovered tile overflow (3 dots) -> Download -> resolution
            for btn in page.locator("button:visible").all()[:80]:
                try:
                    label = " ".join((btn.get_attribute("aria-label") or btn.inner_text() or "").split())
                    if "more_vert" not in label and "More" not in label:
                        continue
                    bb = btn.bounding_box()
                    if not bb or not _inside(box, bb, margin=40):
                        continue
                    btn.click(timeout=4_000)
                    self.manifest("opened tile overflow menu (3 dots)")
                    page.wait_for_timeout(1200)
                except Exception:
                    continue
                dl_item = page.locator(
                    "[role='menuitem']:has-text('Download'):visible, "
                    "[data-state='open'] button:has-text('download'):visible").first
                if not dl_item.count() or not dl_item.is_visible():
                    continue
                try:
                    with page.expect_download(timeout=120_000) as dl_info:
                        dl_item.click(timeout=5_000)
                        # The generation config is already 720p (set by
                        # _select_video_mode), so the browser's DEFAULT download
                        # is a 720p file. Clicking a resolution inside Flow's
                        # download flow has crashed the headed browser
                        # (TargetClosedError, Sep 2026), so try the default
                        # download FIRST (~25s). Only if nothing arrives do we
                        # tap the explicit 720p item (user-requested).
                        started = False
                        for _ in range(17):
                            page.wait_for_timeout(1500)
                            try:
                                dl_info.value
                                started = True
                                break
                            except Exception:
                                continue
                        if not started:
                            for res in ("720p", "1080p", "480p"):
                                r = page.locator(
                                    f"[role='menuitem']:has-text('{res}'):visible, "
                                    f"[data-state='open'] button:has-text('{res}'):visible").first
                                if r.count() and r.is_visible():
                                    try:
                                        r.click(timeout=4_000)
                                        self.manifest(f"chose resolution {res}")
                                        break
                                    except Exception:
                                        continue
                        page.wait_for_timeout(8000)
                    dl_info.value.save_as(str(output_path))
                    self.manifest(f"saved clip -> {output_path}")
                    return
                except Exception as exc:
                    self.manifest(f"tile-download failed ({type(exc).__name__})")
        self._dump_controls(page)
        raise FlowAutomationError("no download control found")

    def _recover_download(self, project_url: str, output_path: Path) -> bool:
        """Re-download a finished clip WITHOUT re-generating (credits already
        spent). Used when the browser died mid-download: reconnect to the same
        flow project on a fresh page and try the download path again."""
        page = self._browser.new_page()
        page.set_default_timeout(60_000)
        try:
            page.goto(project_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(8000)
            for name in ("Videos", "All media"):
                t = page.get_by_text(name, exact=True).first
                if t.count() > 0 and t.is_visible():
                    try:
                        t.click(timeout=4_000)
                        page.wait_for_timeout(4000)
                        break
                    except Exception:
                        pass
            self._download_clip(page, output_path)
            self._ensure_real_video(page, output_path)
            self.manifest(f"recovered clip download from project: {output_path.name}")
            return True
        except Exception as exc:
            self.manifest(f"in-project re-download also failed ({type(exc).__name__})")
            return False
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _ensure_real_video(self, page, output_path: Path) -> None:
        """Download-verify loop: accept only a real, readable video file.

        An empty / unreadable download is usually the render still finishing
        when we grabbed it — wait, then re-download (never re-generate; credits
        were already spent).  After REDOWNLOAD_RETRIES the file still is not a
        video -> raise so the caller's retry / manual-assist budget owns it."""
        for attempt in range(1, REDOWNLOAD_RETRIES + 1):
            if _clip_is_real_video(output_path):
                self.manifest(f"clip verified as real video: {output_path.name}")
                return
            self.manifest(
                f"clip not a real video (attempt {attempt}/{REDOWNLOAD_RETRIES}) "
                "— waiting, then re-downloading"
            )
            self._wait_until_finished(page)
            self._download_clip(page, output_path)
        if not _clip_is_real_video(output_path):
            raise FlowAutomationError(
                f"downloaded file is not a real video after re-downloads: {output_path}"
            )

    def _dump_controls(self, page) -> None:
        """Debug aid: log visible interactive controls with aria/title so the
        next selector iteration can target the real control names."""
        self.manifest("----- visible controls ----")
        for el in page.locator("a, button").all()[:60]:
            try:
                if not el.is_visible():
                    continue
                info = el.evaluate(
                    "e => (e.getAttribute('aria-label') || e.title || e.innerText || '')"
                    ".trim().replace(/\\s+/g, ' ').slice(0, 50)"
                )
                if info:
                    self.manifest(f"  {info}")
            except Exception:
                continue

    def _manual_assist(self, prompt: str, output_path: Path) -> None:
        """Batched / unattended runs must not block a hallway: when fail-fast
        is on, log the prompt + target path to manual_todo.txt and raise
        immediately. Interactive runs print the prompt and block up to 30
        minutes waiting for the operator to save the video file."""
        if cfg.fail_fast_enabled():
            todo = _log_manual_todo(prompt, output_path)
            raise FlowAutomationError(
                f"fail-fast: manual task logged to {todo.name} "
                "(unattended run will not block on Flow)"
            )
        print("\n==============================================")
        print("MANUAL ASSIST REQUIRED")
        print("Paste this prompt into Google Flow, generate, then save the")
        print("video file to the path below. I will wait.")
        print(f"PATH: {output_path}")
        print("PROMPT:")
        print(prompt)
        print("==============================================")
        for _ in range(180):  # up to 30 minutes
            if output_path.exists() and output_path.stat().st_size > 0:
                print(f"[flow] clip picked up -> {output_path}")
                return
            time.sleep(10)
        raise FlowAutomationError(
            f"manual assist timed out waiting for {output_path}"
        )


def _log_manual_todo(prompt: str, output_path: Path) -> Path:
    """Append one human task to manual_todo.txt (timestamped, append-only).

    Unattended runs never block on Flow; they record the escaped prompt and
    target path so a human can reproduce the generation later. Returns the
    todo file."""
    todo = cfg.manual_todo_path()
    todo.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with todo.open("a", encoding="utf-8") as fh:
        fh.write(
            f"[{stamp}] generate and save to:\n  {output_path}\n"
            f"PROMPT:\n{prompt}\n"
            + ("-" * 40)
            + "\n"
        )
    return todo


def _system_chrome() -> bool:
    import shutil

    return shutil.which("google-chrome") or shutil.which("chromium")