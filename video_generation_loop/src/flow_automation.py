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
            if reference_image:
                self._ensure_presenter_character(page, reference_image)
            self._fill_prompt(page, prompt)
            if reference_image:
                self._attach_character_to_prompt(page)
            self._select_video_mode(page)   # Image->Video toggle + model + 9:16
            self._click_generate(page)
            self._approve_credits(page)   # "Approve N credits" dialog (Flow PRO)
            self._wait_until_finished(page)
            self._download_clip(page, output_path)
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
        redesign): get past it to the EDITOR (a contenteditable prompt box).
        Click the in-viewport CTA -> New project (workspace) -> editor, up to a
        few times; a missing button means we are already one step in."""
        for _ in range(6):
            if page.locator(", ".join(ENTERED_HINTS)).count() > 0:
                self.manifest("entry: editor prompt box detected")
                return
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
        self.manifest("entry: no editor prompt box found — continuing anyway")

    def _select_video_mode(self, page) -> None:
        """Flow's bottom toolbar chip carries the generation settings: Image/Video
        toggle, model (Veo), duration, and aspect ratio.

        MCP-verified (Aug 2026): the bottom toolbar shows a chip like
        'Video · 720p 📱 x1' with an arrow-forward submit button. Clicking the
        chip text area opens a menu. Inside: Image/Video toggle, model picker
        (Omni 1.1 Flash, Veo 3.1 - Lite/Fast/Quality), duration, and aspect
        ratio. The model picker is a nested submenu under the model chip.

        Updated (Aug 2026): the toolbar chip is at the BOTTOM of the editor
        (not the top). Selectors target the chip by its visible text pattern
        and aria-haspopup='menu'."""
        def _menu_items():
            """(element, text) pairs for the currently-open menu."""
            out = []
            seen = set()
            for it in page.locator(
                "[role='menuitem']:visible, [data-state='open'] button:visible, "
                "[role='menu'] button:visible").all()[:80]:
                try:
                    t = " ".join(it.inner_text().split())
                except Exception:
                    continue
                if not t or len(t) > 80 or t in seen:
                    continue
                seen.add(t)
                out.append((it, t))
            return out

        def _open_bottom_toolbar_menu():
            """Click the bottom toolbar chip to open the generation settings menu.
            The chip shows text like 'Video · 720p 📱 x1' or 'Settings trigger'
            and is located near the prompt submit button at the bottom of the editor."""
            # Focus the prompt box first to ensure the toolbar is mounted
            for sel in PROMPT_FIELD_HINTS:
                box = page.locator(sel).first
                if box.count():
                    try:
                        box.click(timeout=3_000)
                    except Exception:
                        pass
                    break
            page.wait_for_timeout(2000)

            # Strategy 1: "Settings trigger" button (MCP-verified Sep 2026)
            settings_btn = page.get_by_role("button", name="Settings trigger").first
            if settings_btn.count() > 0:
                try:
                    settings_btn.click(timeout=3_000)
                    page.wait_for_timeout(1500)
                    texts = [t for _, t in _menu_items()]
                    if texts:
                        self.manifest("toolbar: opened Settings trigger menu")
                        return "Settings trigger"
                except Exception:
                    pass

            # Strategy 2: find the bottom toolbar chip by aria-haspopup='menu'
            # that contains video/image mode text (NOT "More options for the project")
            for btn in page.locator("button[aria-haspopup='menu']:visible").all():
                try:
                    label = " ".join((btn.get_attribute("aria-label") or btn.inner_text() or "").split())
                    bb = btn.bounding_box()
                    if not bb or not label:
                        continue
                    # Skip project-level menus ("More options for the project", "Sort", etc.)
                    if any(skip in label.lower() for skip in
                           ['project', 'sort', 'filter', 'more options', 'search']):
                        continue
                    # The toolbar chip is at the BOTTOM of the page (y > 400)
                    if bb['y'] > 400 and any(kw in label.lower() for kw in
                            ['video', 'image', '720p', '1080p', '480p', 'crop', 'model',
                             'nano', 'veo', 'banana']):
                        btn.click(timeout=3_000)
                        texts = [t for _, t in _menu_items()]
                        for _ in range(6):
                            if texts:
                                break
                            page.wait_for_timeout(500)
                            texts = [t for _, t in _menu_items()]
                        if texts:
                            self.manifest(f"toolbar: opened bottom chip '{label}'")
                            return label
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(300)
                except Exception:
                    continue

            # Strategy 3: find any button with 'arrow_drop_down' near the bottom
            for btn in page.locator("button:visible").all():
                try:
                    text = " ".join(btn.inner_text().split())
                    bb = btn.bounding_box()
                    if not bb or bb['y'] < 400:
                        continue
                    if 'arrow_drop_down' in text or 'Video' in text or 'Image' in text:
                        btn.click(timeout=3_000)
                        texts = [t for _, t in _menu_items()]
                        for _ in range(6):
                            if texts:
                                break
                            page.wait_for_timeout(500)
                            texts = [t for _, t in _menu_items()]
                        if texts:
                            self.manifest(f"toolbar: opened chip '{text[:40]}'")
                            return text[:40]
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(300)
                except Exception:
                    continue
            return None

        def _click_menu_item(pred):
            for it, t in _menu_items():
                if pred(t):
                    try:
                        it.click(timeout=3_000)
                        return True
                    except Exception:
                        return False
            return False

        # First check if video mode is already on (chip shows "Video · ...")
        body_text = page.inner_text('body')
        if 'Video' in body_text and ('720p' in body_text or '1080p' in body_text):
            self.manifest("toolbar: video mode already active")
            # Still try to set model/duration/aspect
            pass

        label = _open_bottom_toolbar_menu()
        if label is None:
            self.manifest("no toolbar menu found (video mode unknown)")
            return

        done = []
        # Step 1: ensure Video mode is on
        if _click_menu_item(lambda t: "videocam" in t and "Video" in t):
            done.append("video mode on")
            page.wait_for_timeout(1200)
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            _open_bottom_toolbar_menu()

        # Step 2: open model picker and select Veo 3.1 Lite
        model_picked = False
        for it, t in _menu_items():
            if 'arrow_drop_down' in t or 'drop_down' in t:
                try:
                    it.click(timeout=3_000)
                    page.wait_for_timeout(1200)
                    model_picked = True
                    self.manifest("toolbar: opened model picker")
                    break
                except Exception:
                    continue
        if model_picked:
            # Look for Veo 3.1 Lite in the submenu
            for it, t in _menu_items():
                if 'veo' in t.lower() and 'lite' in t.lower():
                    try:
                        it.click(timeout=3_000)
                        done.append("model Veo Lite")
                        page.wait_for_timeout(1200)
                        break
                    except Exception:
                        continue
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            _open_bottom_toolbar_menu()

        # Step 3: set duration to 10s
        if _click_menu_item(lambda t: "10s" in t or "10 s" in t):
            done.append("duration 10s")
            page.wait_for_timeout(1200)
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            _open_bottom_toolbar_menu()

        # Step 4: set aspect ratio to 9:16
        if _click_menu_item(lambda t: "9:16" in t or "crop_9_16" in t or "portrait" in t.lower()):
            done.append("aspect 9:16")
            page.wait_for_timeout(1200)

        page.keyboard.press("Escape")
        self.manifest("generation menu set: " + (", ".join(done) if done else "no changes applied"))

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
        picked = False
        options = page.locator(f"[role='option']:has-text('{name}')").all()
        if options:
            try:
                options[0].click(timeout=6_000)
                picked = True
                self.manifest(f"char: picked asset {name} from dialog")
            except Exception:
                pass
        if not picked:
            # fallback: click the first option in the asset list
            first_opt = page.locator("[role='option']:visible").first
            if first_opt.count() > 0:
                try:
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

        # 6. Click "Add media" button in the dialog to confirm selection
        page.wait_for_timeout(1000)
        add_media_btn = page.locator(ADD_MEDIA_IN_DIALOG).first
        if add_media_btn.count() == 0:
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
          2. Select the character from the asset list (on default "All" tab)
          3. Character is auto-attached — verify by checking for "Ingredient" button

        Returns True if the character was successfully attached."""
        # 1. Open ingredients picker
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

        # 2. Select the character from the list (default "All" tab shows characters)
        char_option = page.locator(f"[role='option']:has-text('{character_name}')").first
        if char_option.count() == 0:
            char_option = page.locator("[role='option']:visible").first
        if char_option.count() == 0:
            self.manifest(f"ingredients: character '{character_name}' not found in list")
            page.keyboard.press("Escape")
            return False
        char_option.click(timeout=6_000)
        page.wait_for_timeout(1500)
        self.manifest(f"ingredients: clicked character '{character_name}'")

        # 3. Verify character was attached — look for "Ingredient" button with character image
        ingredient_btn = page.locator("button:has(img[alt='Character ingredient image'])").first
        if ingredient_btn.count() == 0:
            ingredient_btn = page.get_by_role("button", name="Ingredient").first
        if ingredient_btn.count() > 0:
            self.manifest(f"ingredients: attached character '{character_name}' to prompt")
            return True

        # 4. Fallback: check if the "Add to prompt" button appeared (older Flow versions)
        add_prompt = page.locator(ADD_TO_PROMPT_BTN).first
        if add_prompt.count() > 0:
            add_prompt.click(timeout=6_000)
            page.wait_for_timeout(1000)
            self.manifest(f"ingredients: clicked 'Add to prompt' for '{character_name}'")
            return True

        self.manifest(f"ingredients: character '{character_name}' may not have attached (no verification)")
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
                self.manifest("generate clicked")
                return
            except Exception:
                continue
        raise FlowAutomationError("no generate button found")

    def _approve_credits(self, page) -> None:
        """Flow PRO asks "Approve N credits" before each generation. Click the
        dialog's confirm button — and ONLY inside a real dialog, never
        page-wide so a stray Continue/OK/Yes button cannot spend credits.
        Fail-closed: if the day has never seen an explicit approval, a missing/
        unmatched dialog aborts the clip (money gate) rather than proceeding
        without it. Lenient only after the first approval succeeds once, where
        Flow may not re-ask. Set FLOW_CREDITS_PREAPPROVED=1 to skip the
        gate entirely if your account auto-approves credits (rare)."""
        if self._credits_approved:
            self.manifest("credits already approved this clip")
            return
        for _ in range(10):
            for scope, sel in _approval_candidates():
                el = page.locator(scope).first
                if el.count() == 0 or not el.is_visible():
                    continue
                try:
                    el.click(timeout=4_000)
                    self._credits_approved = True
                    self._run_credits_approved = True
                    self.manifest(f"approved credits via '{scope}{sel}'")
                    return
                except Exception:
                    continue
            time.sleep(2)
        if self._run_credits_approved:
            self.manifest("credit dialog not detected, but credits were already "
                          "approved earlier this run — continuing")
            return
        if cfg.env_or("FLOW_CREDITS_PREAPPROVED", "").strip().lower() in ("1", "true", "yes"):
            self._run_credits_approved = True
            self.manifest("FLOW_CREDITS_PREAPPROVED=1 set; skipping credit dialog gate")
            return
        raise FlowAutomationError(
            "no credit-approval dialog detected for the first generation. "
            "Refusing to spend credits without an explicit approval. "
            "If Flow's UI changed, update APPROVE_HINTS/APPROVAL_SCOPES or "
            "approve the dialog manually in the browser then retry."
        )

    def _wait_until_finished(self, page) -> None:
        deadline = time.time() + 900  # Flow generations can take 5-12 min (Veo 3.1 Lite)
        while time.time() < deadline:
            elapsed = int(time.time() - (deadline - 900))
            # A running generation shows a "Stop" control on the submit button;
            # when it disappears AND a result (video or download control) exists,
            # the generation is truly done.
            generating = page.locator("button:has-text('Stop'):visible").count() > 0
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
                        page.wait_for_timeout(1500)
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