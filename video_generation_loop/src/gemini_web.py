"""Browser-based Gemini Web Automation (No API Key Required).

Uses the existing signed-in Google PRO session in `.runtime/flow-profile/`
to interact with https://gemini.google.com/app directly:
1. Navigates to Gemini web app in the shared browser context.
2. Prompts Gemini for a 6-scene structured educational storyboard.
3. Extracts and parses the JSON response from the chat bubble.
4. Returns a validated `Storyboard` object ready for Google Flow.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

import src.config as cfg
from src.planner import (
    DURATION_S,
    SCENES,
    Scene,
    Storyboard,
    _PRESENTER_BG,
    _PRESENTER_SCENES,
    _VISUAL_BG,
    _default_captions,
    _presenter_background,
    _ref_images,
    _screen_text,
    screen_storyboard,
    template_storyboard,
)
from src.state import Topic

GEMINI_WEB_URL = "https://gemini.google.com/app"

PROMPT_INPUT_SELECTORS = [
    "div[role='textbox'][contenteditable='true']",
    "rich-textarea [contenteditable='true']",
    "textarea[aria-label*='Ask Gemini']",
    "textarea[aria-label*='prompt']",
    "div.ql-editor",
    "textarea",
]

SUBMIT_BUTTON_SELECTORS = [
    "button[aria-label*='Send message']:visible",
    "button[aria-label*='Submit']:visible",
    "button.send-button:visible",
    "button[mattooltip*='Send']:visible",
]

RESPONSE_SELECTORS = [
    "message-content",
    ".model-response-text",
    "div.response-container",
    "[data-test-id='model-response']",
    "div.markdown",
]


class GeminiWebError(RuntimeError):
    """Raised when web-based Gemini interaction fails."""


def _extract_json(text: str) -> dict:
    """Extract a JSON object from markdown code fences or raw text."""
    # Match ```json ... ``` code blocks
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1)
    # Find outer curly braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"No JSON object found in Gemini response: {text[:200]}...")


def generate_storyboard_via_gemini_web(
    day: int,
    topic: Topic,
    page,
    manifest: Callable[[str], None] = print,
    timeout_s: int = 120,
    strict: bool = False,
) -> Storyboard:
    """Ask Gemini Web (gemini.google.com) to generate a 6-scene storyboard.

    Mirrors `planner.gemini_storyboard` semantics end-to-end (parity):
    - topic inputs are screened for secrets/injection BEFORE the browser opens;
    - the LLM OUTPUT goes through the same `screen_storyboard` gate
    - on any failure/timeout/unscreened output: strict => raise GeminiWebError,
      else degrade to the deterministic template (money-safe: no paid Flow
      prompt is ever built from unscreened content)."""
    for label, text in (("title", topic.title), ("takeaway", topic.takeaway)):
        problems = _screen_text(text)
        if problems:
            if strict:
                raise GeminiWebError(f"unsafe {label} content: {problems}")
            manifest(f"[gemini-web] unsafe {label} ({problems}), using template")
            return template_storyboard(day, topic)

    manifest(f"[gemini-web] navigating to {GEMINI_WEB_URL} ...")
    page.goto(GEMINI_WEB_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3000)

    # Check if signed in
    url = page.url.lower()
    if "accounts.google.com" in url or "signin" in url:
        raise GeminiWebError(
            "Gemini Web is not signed in. Please run `python -m src.main --login` to sign in."
        )

    manifest("[gemini-web] finding prompt input box ...")
    input_box = None
    for sel in PROMPT_INPUT_SELECTORS:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            input_box = el
            break

    if input_box is None:
        raise GeminiWebError(
            "Could not find prompt input on gemini.google.com. Google may have updated the UI."
        )

    system_instruction = (
        "You are an expert short-form video director for Pakistani tech education.\n"
        f"Topic for Day {day}: '{topic.title}'. Core Takeaway: '{topic.takeaway}'.\n"
        "Write a strict 6-scene storyboard for a 60-second video.\n"
        "- Scenes 1, 2, 4, 5, 6: Presenter scenes featuring a young guy with glasses in a modern dark tech studio, "
        "calm engaging youthful male voice, speaking natural Urdu/Hindi with realistic lip-sync.\n"
        "- Scene 3: A pure dark-terminal animated code visual (no human on screen).\n"
        "Output ONLY valid JSON with no conversational text before or after, exactly matching this schema:\n"
        "{\n"
        '  "hook": "string (3-second Roman Urdu hook)",\n'
        '  "scenes": [\n'
        '    {"scene_number": 1, "voiceover": "string (Urdu/Hindi ~24 words)", "flow_video_prompt": "string"},\n'
        '    {"scene_number": 2, "voiceover": "string", "flow_video_prompt": "string"},\n'
        '    {"scene_number": 3, "voiceover": "string", "flow_video_prompt": "string (dark terminal, no human)"},\n'
        '    {"scene_number": 4, "voiceover": "string", "flow_video_prompt": "string"},\n'
        '    {"scene_number": 5, "voiceover": "string", "flow_video_prompt": "string"},\n'
        '    {"scene_number": 6, "voiceover": "string", "flow_video_prompt": "string"}\n'
        "  ],\n"
        '  "captions": {\n'
        '    "tiktok": "string",\n'
        '    "instagram_reels": "string",\n'
        '    "facebook": "string",\n'
        '    "youtube_shorts": "string"\n'
        "  }\n"
        "}"
    )

    manifest("[gemini-web] typing prompt request into Gemini ...")
    input_box.click(timeout=5_000)
    input_box.fill(system_instruction, timeout=10_000)
    page.wait_for_timeout(800)

    # Submit
    submitted = False
    for sel in SUBMIT_BUTTON_SELECTORS:
        btn = page.locator(sel).first
        if btn.count() > 0 and btn.is_visible():
            btn.click(timeout=3_000)
            submitted = True
            manifest("[gemini-web] clicked Send button")
            break
    if not submitted:
        page.keyboard.press("Enter")
        manifest("[gemini-web] pressed Enter to submit")

    # Wait for response completion
    manifest("[gemini-web] waiting for Gemini response ...")
    deadline = time.time() + timeout_s
    response_text = ""
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        # Check if streaming stop button is active
        stop_btn = page.locator("button[aria-label*='Stop']:visible, button.stop-button:visible")
        if stop_btn.count() > 0:
            continue

        # Look for model responses
        for sel in RESPONSE_SELECTORS:
            responses = page.locator(sel).all()
            if responses:
                last_response = responses[-1]
                txt = last_response.inner_text() or ""
                if "{" in txt and "}" in txt:
                    response_text = txt
                    break
        if response_text:
            break

    if not response_text:
        msg = "[gemini-web] timeout waiting for Gemini response"
        if strict:
            raise GeminiWebError(msg)
        manifest(f"{msg}, falling back to template")
        return template_storyboard(day, topic)

    manifest("[gemini-web] extracting and parsing JSON storyboard ...")
    try:
        data = _extract_json(response_text)
    except Exception as exc:
        msg = f"[gemini-web] JSON parse failed ({exc})"
        if strict:
            raise GeminiWebError(msg)
        manifest(f"{msg}, falling back to template")
        return template_storyboard(day, topic)

    hook = str(data.get("hook", "") or "")
    raw_captions = data.get("captions")
    if not isinstance(raw_captions, dict):
        raw_captions = {}
    captions = {k: str(v) for k, v in raw_captions.items() if isinstance(v, str)}

    refs = _ref_images()
    raw_scenes = data.get("scenes")
    scenes: list[Scene] = []
    if isinstance(raw_scenes, list):
        for i, sc in enumerate(raw_scenes[:SCENES], start=1):
            if not isinstance(sc, dict):
                continue
            prompt_text = str(sc.get("flow_video_prompt", "") or "").strip()
            vo = str(sc.get("voiceover", "") or "").strip()
            is_presenter = i in _PRESENTER_SCENES
            ref_img = refs[(i - 1) % len(refs)] if (is_presenter and refs) else None
            if not prompt_text:
                prompt_text = template_storyboard(day, topic).scenes[i - 1].flow_prompt
            if not vo:
                vo = template_storyboard(day, topic).scenes[i - 1].voiceover
            scenes.append(
                Scene(
                    number=i,
                    duration_s=DURATION_S,
                    voiceover=vo,
                    flow_prompt=prompt_text,
                    needs_presenter=is_presenter,
                    reference_image=ref_img,
                    background=_presenter_background(i) if is_presenter else _VISUAL_BG,
                )
            )

    template_sb = template_storyboard(day, topic)
    while len(scenes) < SCENES:
        scenes.append(template_sb.scenes[len(scenes)])

    sb = Storyboard(day=day, topic=topic, hook=hook, scenes=scenes)
    sb.captions = captions or _default_captions(topic)

    # Planner parity gate: same screen as the Gemini API path. Unscreened
    # output must NEVER build a paid Flow prompt.
    problems = screen_storyboard(sb)
    if problems:
        if strict:
            raise GeminiWebError(f"unsafe storyboard content: {problems}")
        manifest(f"[gemini-web] unscreened output ({problems}), falling back to template")
        return template_storyboard(day, topic)
    manifest("[gemini-web] Storyboard generated successfully from Gemini Web.")
    return sb
