"""Storyboard (6-scene) generator.

Two planners behind one interface:
- TemplatePlanner: deterministic, no API, used for --dry-run and tests.
- GeminiPlanner: calls Gemini via the OpenAI-compatible endpoint using
  GEMINI_API_KEY. Falls back to TemplatePlanner on any failure unless
  strict=True.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import src.config as cfg
from src.state import Topic

SCENES = 6
DURATION_S = 10
ASPECT = "9:16"

VISUAL_ANCHOR = (
    "tall vertical 9:16 short-form tech video, sleek dark terminal and "
    "glowing code interface, cinematic depth of field, modern UI in frame, "
    "clean minimal aesthetic, 24fps"
)


@dataclass
class Scene:
    number: int
    duration_s: int
    voiceover: str
    flow_prompt: str
    needs_presenter: bool = False
    reference_image: str | None = None
    background: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "scene_number": self.number,
            "duration_sec": self.duration_s,
            "voiceover": self.voiceover,
            "flow_video_prompt": self.flow_prompt,
            "needs_presenter": self.needs_presenter,
            "reference_image": self.reference_image,
            "background": self.background,
        }


@dataclass
class Storyboard:
    day: int
    topic: Topic
    hook: str
    scenes: list[Scene] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, object], topic: Topic) -> "Storyboard":
        """Rehydrate a saved storyboard (immutable per-day; resume-safe)."""
        sb = cls(
            day=int(data.get("day", 0)),
            topic=topic,
            hook=str(data.get("hook", "") or ""),
        )
        for sc in data.get("scenes") or []:
            num = int(sc.get("scene_number", 0))
            sb.scenes.append(
                Scene(
                    number=num,
                    duration_s=int(sc.get("duration_sec", DURATION_S)),
                    voiceover=str(sc.get("voiceover", "")),
                    flow_prompt=str(sc.get("flow_video_prompt", "")),
                    needs_presenter=bool(sc.get("needs_presenter", False)),
                    reference_image=sc.get("reference_image") or None,
                    background=str(sc.get("background", "")),
                )
            )
        caps = data.get("captions")
        sb.captions = dict(caps) if isinstance(caps, dict) else {}
        return sb

    def to_dict(self) -> dict[str, object]:
        return {
            "day": self.day,
            "topic": self.topic.title,
            "topic_id": self.topic.id,
            "hook": self.hook,
            "scenes": [s.to_dict() for s in self.scenes],
            "captions": self.captions,
            "meta": {
                "source": "https://agentfactory.panaversity.org/docs/agentic-coding-crash-course",
                "clip_count": SCENES,
                "duration_sec": SCENES * DURATION_S,
                "aspect_ratio": ASPECT,
            },
        }


# --- Presenter-style template planner (default; user-approved, paid-safe) ---
# The presenter (young man) appears in a subset of scenes, built from a user
# reference image into a Flow Character (see flow_automation._ensure_presenter_character);
# the remaining scenes are pure terminal/UI visuals with voiceover only.
_PRESENTER_TEMPLATE = (
    "Educational explainer video featuring the young guy with glasses from the reference "
    "image as the on-screen presenter and narrator with dark hair and modern tech outfit. "
    "{background} The presenter looks directly into the camera with confident, professional, "
    "and natural gestures, speaking naturally in a calm engaging youthful male voice with "
    "realistic lip-sync. Animated clean text overlays highlighting key takeaways. "
    "Narrate / Lip-Sync exactly (in clear Urdu/Hindi): '{narration}'"
)
_PRESENTER_BG = "Clean modern dark-themed studio setting with soft blue neon accents and subtle tech elements in the background."
_VISUAL_BG = "Close-up animated dark terminal and code editor, glowing green-white code typed by an AI agent cursor, clean minimal aesthetic, 24fps, no human on screen."

# Scene 3 is always a pure-visual terminal demo; the rest are presenter scenes.
_PRESENTER_SCENES = {1, 2, 4, 5, 6}


def _ref_images() -> list[str]:
    """Reference-image filenames available for presenter scenes (references/*.png).
    Prefer 9:16 vertical shots, then any image, so the presenter crops well."""
    ref_dir = Path(__file__).resolve().parent.parent / "references"
    if not ref_dir.is_dir():
        return []
    return sorted(p.name for p in ref_dir.glob("*.png"))


def _presenter_narration(i: int, topic: Topic) -> str:
    patterns = [
        f"{topic.title} chatbots nahi hain. Woh sirf jawab nahi dete — woh aapke computer par asal kaam karte hain. Aur isi ek baat ne coding ka tareeqa badal diya.",
        "Aap describe karte ho, woh kaam karte hain. Aap review karte ho. Sab se bada mindset shift yeh hai: sawal mat poocho, instruction do.",
        f"{topic.title} ka poora faida tabi aata hai jab tum ise asal kaam par lagate ho — woh file banata, test chalat, theek karta hai.",
        "Sab se aam ghalti? Inse chatbot jaisa baat karna. 'Mujhe samjhao', 'kya ho sakta hai' — aisa poochne se faida nahi milta. Order do.",
        "Aaj se aise try karo: ek acha sa instruction likho — kaam batao, format batao, jab chaahiye woh batao. Phir review karo. Yahi poora system hai.",
        "Nateeja? Tum ab kaam zyada karte ho, ghaltiyan kam. Yehi asli superpower hai — sawal poochne wale nahi, kaam karne wala. Subscribe karo, kal agla concept bhi seekhein.",
    ]
    return patterns[(i - 1) % len(patterns)]


def _presenter_background(i: int) -> str:
    if i == 2:
        return ("Clean modern dark-themed studio setting with a floating terminal and code panel behind the presenter, soft blue neon accents, code snippets animating.")
    if i == 4:
        return ("Clean modern dark-themed studio setting, soft blue neon accents with a subtle red warning accent to highlight the common mistake, animated text overlays.")
    if i == 5:
        return ("Clean modern dark-themed studio setting with a laptop and code editor beside the presenter, soft blue neon accents, animated workflow checkmark steps.")
    return _PRESENTER_BG


def template_storyboard(day: int, topic: Topic) -> Storyboard:
    hook = (
        f"'{topic.title}' ka asli faida jaante ho? {topic.takeaway[:60]}..."
    )
    refs = _ref_images()
    sb = Storyboard(day=day, topic=topic, hook=hook)
    for i in range(1, SCENES + 1):
        narration = _presenter_narration(i, topic)
        if i in _PRESENTER_SCENES:
            # rotate through the available reference images ("kabhi koi, kabhi koi")
            ref = refs[(i - 1) % len(refs)] if refs else None
            prompt = _PRESENTER_TEMPLATE.format(
                background=_presenter_background(i), narration=narration
            )
            scene = Scene(
                number=i, duration_s=DURATION_S, voiceover=narration,
                flow_prompt=prompt, needs_presenter=True, reference_image=ref,
                background=_presenter_background(i),
            )
        else:
            desc = (
                "Showing it live on the terminal — how the agent actually behaves: "
                "the user gives one clear instruction and the AI agent acts on it."
            )
            prompt = (
                f"{_VISUAL_BG} Animated clean text overlay: 'Instruction -> Action'. "
                f"Scene {i}/{SCENES}: {desc}"
            )
            vo = f"{desc} {topic.takeaway}"
            scene = Scene(
                number=i, duration_s=DURATION_S, voiceover=vo,
                flow_prompt=prompt, needs_presenter=False, reference_image=None,
                background=_VISUAL_BG,
            )
        sb.scenes.append(scene)
    sb.captions = _default_captions(topic)
    return sb


# --- Caption sketch (per platform; refined by the LLM planner when used) ---
def _default_captions(topic: Topic) -> dict[str, str]:
    core = (
        f"{topic.title} — {topic.takeaway}. "
        f"Daily AI agent learning, 1 minute. #AI #AgenticCoding #OpenCode #ClaudeCode"
    )
    return {
        "tiktok": core,
        "instagram_reels": core,
        "facebook": core,
        "youtube_shorts": core,
    }


# --- Gemini planner (OpenAI-compatible endpoint) ---
_LONG_PROMPT_WORDS = 90
_SECRET_HINTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "bearer ",
    "sk-",
    "AIza",
    "password",
)
_INJECTION_HINTS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "disregard",
    "you are now",
    "print your instructions",
)


def _screen_text(text: str) -> list[str]:
    """Return a list of reasons text must NOT be sent to the LLM."""
    lower = text.lower()
    reasons: list[str] = []
    for hint in _SECRET_HINTS:
        if hint in lower:
            reasons.append(f"possible secret ('{hint}')")
    for hint in _INJECTION_HINTS:
        if hint in lower:
            reasons.append(f"possible prompt injection ('{hint}')")
    return reasons


def screen_storyboard(sb: "Storyboard") -> list[str]:
    """Screen an LLM-PRODUCED storyboard's text fields (hook, scene prompts,
    voiceovers, captions) for secret- or injection-looking content before they
    reach paid Flow prompts and the YouTube SEO doc.

    This is the planner-PARITY gate: every LLM source (Gemini API and
    gemini-web) runs its output through this same check, so no planner can
    smuggle an unscreened string into a paid generation. Deterministic
    template storyboards are never screened (they are trusted in-repo).
    Returns [] when the storyboard is safe."""
    problems: list[str] = []
    candidates = [("hook", sb.hook)]
    candidates += [(f"scene {s.number} prompt", s.flow_prompt) for s in sb.scenes]
    candidates += [(f"scene {s.number} voiceover", s.voiceover) for s in sb.scenes]
    candidates += [(f"caption {p}", cap) for p, cap in sorted((sb.captions or {}).items())]
    for label, text in candidates:
        for reason in _screen_text(text or ""):
            problems.append(f"{label}: {reason}")
    return problems


def gemini_storyboard(day: int, topic: Topic, api_key: str, strict: bool = False) -> Storyboard:
    """Generate a storyboard from Gemini. On any failure: if strict, raise;
    otherwise fall back to the template planner (so the daily run survives)."""

    def fallback() -> Storyboard:
        return template_storyboard(day, topic)

    # never send concrete API keys anywhere; api_key is only the auth credential
    for label, text in (("title", topic.title), ("takeaway", topic.takeaway)):
        problems = _screen_text(text)
        if problems:
            if strict:
                raise ValueError(f"unsafe {label} content: {problems}")
            return fallback()

    try:
        import openai
    except ImportError as exc:
        if strict:
            raise RuntimeError("openai package not installed") from exc
        return fallback()

    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url=cfg.gemini_base_url(),
        )
        system = (
            "You are an expert short-form video director for Pakistani tech "
            "education. Output STRICT JSON only, no markdown, matching exactly: "
            '{"hook": str, "scenes": [{"voiceover": str, "flow_video_prompt": str} x 6], '
            '"captions": {"tiktok": str, "instagram_reels": str, "facebook": str, '
            '"youtube_shorts": str}}. Urdu/English mixed voiceovers for a Pakistani '
            "audience. PRESENTER STYLE: scenes 1,2,4,5,6 feature a young male "
            "presenter on screen (dark studio, soft blue neon accents, realistic "
            "lip-sync, Urdu/Hindi narration); scene 3 is a pure dark-terminal "
            "visual with voiceover only (no presenter). Each flow_video_prompt: "
            "tall 9:16 vertical, keep a consistent look so the 6 clips feel like "
            f"one video, camera + mood. Keep prompts under {_LONG_PROMPT_WORDS} words."
        )
        user = (
            f"Day {day}. Course topic: '{topic.title}'. One-sentence takeaway: "
            f"{topic.takeaway}. Source course: "
            "https://agentfactory.panaversity.org/docs/agentic-coding-crash-course "
            "(15 concepts; never leave the course framing). 6 scenes x 10s."
        )
        resp = client.chat.completions.create(
            model=cfg.gemini_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.6,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - network, JSON, API errors -> degrade
        if strict:
            raise
        print(f"[planner] Gemini failed ({type(exc).__name__}), using template")
        return fallback()

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
            is_presenter = (i in _PRESENTER_SCENES)
            ref_img = (refs[(i - 1) % len(refs)] if (is_presenter and refs) else None)
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
    # pad to exactly 6
    template_sb = template_storyboard(day, topic)
    while len(scenes) < SCENES:
        scenes.append(template_sb.scenes[len(scenes)])

    sb = Storyboard(day=day, topic=topic, hook=hook, scenes=scenes)
    sb.captions = captions or _default_captions(topic)

    # Output gate (planner parity): never let an unscreened LLM string reach
    # paid Flow prompts or the YouTube SEO doc. strict => fail the run;
    # otherwise degrade to the known-good deterministic template.
    problems = screen_storyboard(sb)
    if problems:
        if strict:
            raise ValueError(f"unsafe storyboard content: {problems}")
        print(f"[planner] unscreened content in Gemini output ({problems}); using template")
        return fallback()
    return sb


def storyboard_for(day: int, topic: Topic, api_key: str | None = None, strict: bool = False) -> Storyboard:
    """Pick the planner. An explicit `api_key` opts into Gemini; `api_key=None`
    means TEMPLATE even if GEMINI_API_KEY/GOOGLE_API_KEY sit in env — opting into
    the Gemini API is a deliberate, explicit choice (config.use_gemini gates it
    in the orchestrator), never an implicit side effect of a stray env var."""
    if api_key:
        return gemini_storyboard(day, topic, api_key, strict=strict)
    return template_storyboard(day, topic)