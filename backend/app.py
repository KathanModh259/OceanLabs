import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

# Auto-fix shadowing issue: the local 'resemblyzer' folder breaks the python module import.
legacy_resemblyzer_dir = os.path.join(SCRIPT_DIR, 'resemblyzer')
legacy_resemblyzer_init = os.path.join(legacy_resemblyzer_dir, '__init__.py')
target_model_dir = os.path.join(SCRIPT_DIR, 'resemblyzer_model')

if os.path.exists(legacy_resemblyzer_dir) and os.path.isdir(legacy_resemblyzer_dir) and not os.path.exists(legacy_resemblyzer_init):
    try:
        os.rename(legacy_resemblyzer_dir, target_model_dir)
        print("✅ Fixed module shadowing: renamed 'resemblyzer' to 'resemblyzer_model'")
    except Exception as e:
        print(f"Failed to rename 'resemblyzer' directory: {e}")

import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from resemblyzer import VoiceEncoder
from resemblyzer.audio import preprocess_wav
from faster_whisper import WhisperModel
import tempfile
from datetime import datetime
from indicnlp.normalize import indic_normalize
from indicnlp.tokenize import indic_tokenize
import re
import wave
import time
import threading
import asyncio
from urllib.parse import urlparse

# Azure & Dotenv
from azure.ai.inference import ChatCompletionsClient
from dotenv import load_dotenv
# Load .env from repo root first, then allow backend/.env to override.
load_dotenv(os.path.join(REPO_ROOT, ".env"))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"), override=True)
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

# Supabase
try:
    from supabase import create_client, Client
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if sb_url and sb_key:
        supabase_client: Client = create_client(sb_url, sb_key)
    else:
        print("[Supabase Warning] SUPABASE_URL or SUPABASE key is missing. Database sync is disabled.")
        supabase_client = None
except ImportError as import_error:
    print(f"[Supabase Warning] Python package 'supabase' is not installed. Database sync is disabled. Details: {import_error}")
    supabase_client = None

# Optional dependencies for Online Bot Mode
try:
    import pyaudiowpatch as pyaudio
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    ONLINE_BOT_AVAILABLE = True
except ImportError:
    ONLINE_BOT_AVAILABLE = False
    PlaywrightTimeoutError = TimeoutError

try:
    from integrations import run_post_meeting_integrations
except Exception as integration_import_error:  # noqa: BLE001
    run_post_meeting_integrations = None
    print(f"[Integrations Warning] Integrations module unavailable: {integration_import_error}")


PLATFORM_ALIASES = {
    "google meet": "meet",
    "google_meet": "meet",
    "gmeet": "meet",
    "meet": "meet",
    "microsoft teams": "teams",
    "microsoft_teams": "teams",
    "ms teams": "teams",
    "ms_teams": "teams",
    "teams": "teams",
    "zoom": "zoom",
    "zoom meeting": "zoom",
    "zoom_meeting": "zoom",
    "local": "local",
    "offline": "local",
}

PLATFORM_HOST_RULES = {
    "meet": ["meet.google.com"],
    "teams": ["teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"],
    "zoom": ["zoom.us", "zoomgov.com", "zoom.com.cn"],
}


def normalize_platform_name(platform: str) -> str:
    key = (platform or "").strip().lower()
    return PLATFORM_ALIASES.get(key, key)


def detect_platform_from_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return "meet"

    if not candidate.lower().startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    try:
        host = (urlparse(candidate).hostname or "").lower()
    except Exception:
        host = ""

    for platform, domains in PLATFORM_HOST_RULES.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return platform

    return "meet"


def normalize_person_name(raw_name: str) -> str | None:
    candidate = (raw_name or "").replace("\n", " ").strip()
    candidate = re.sub(r"\s{2,}", " ", candidate)
    candidate = re.sub(r"[:\-|\u2013\u2014\s]+$", "", candidate).strip()
    if not candidate:
        return None

    lowered = candidate.lower()
    blocked_fragments = (
        "meeting chat",
        "caption",
        "microphone",
        "unmuted",
        "muted",
        "video off",
        "controls",
        "more options",
        "raise hand",
        "participants",
    )
    if any(fragment in lowered for fragment in blocked_fragments):
        return None

    if lowered in {"you", "you (you)"}:
        return "Meeting Host"

    if len(candidate) < 2 or len(candidate) > 60:
        return None

    return candidate


def click_first_visible(page, selectors: list[str], timeout: int = 2500) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def fill_first_visible(page, selectors: list[str], value: str, timeout: int = 2500) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).first.fill(value, timeout=timeout)
            return True
        except Exception:
            continue
    return False


def hosts_compatible(expected_host: str, current_host: str) -> bool:
    if not expected_host or not current_host:
        return False
    if expected_host == current_host:
        return True
    return current_host.endswith(f".{expected_host}") or expected_host.endswith(f".{current_host}")


def navigate_with_fallback(page, target_url: str, label: str, timeout_ms: int = 45000):
    expected_host = ""
    try:
        expected_host = (urlparse(target_url).hostname or "").lower()
    except Exception:
        expected_host = ""

    last_error = None
    for wait_mode in ("domcontentloaded", "commit", "load"):
        try:
            print(f"[BOT] Navigating to {label} (wait mode: {wait_mode})")
            page.goto(target_url, wait_until=wait_mode, timeout=timeout_ms)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
            print(f"[BOT] Navigation timeout for {label} with wait mode '{wait_mode}'.")
        except Exception as exc:
            last_error = exc
            print(f"[BOT] Navigation warning for {label}: {exc}")
            break

        try:
            page.wait_for_timeout(1200)
            current_host = (urlparse(page.url).hostname or "").lower()
            if hosts_compatible(expected_host, current_host):
                print(f"[BOT] Continuing after timeout because host resolved to {current_host}.")
                return
        except Exception:
            pass

    current_url = "unknown"
    try:
        current_url = page.url
    except Exception:
        pass

    raise RuntimeError(
        f"Could not open {label}. Last navigation error: {last_error}. Current URL: {current_url}"
    )


# ==================== Platform Strategy Pattern ====================
class PlatformStrategy:
    def get_auth_check_url(self):
        return None

    def is_logged_in(self, page):
        """Return True if authenticated, False otherwise."""
        raise NotImplementedError

    def enable_captions(self, page):
        """Enable captions on the meeting page."""
        pass

    def get_join_actions(self, page, url, bot_name):
        """Perform actions to join the meeting (after navigation to URL)."""
        raise NotImplementedError

    def get_active_speaker(self, page):
        """Extract active speaker name from DOM. Return None if not found."""
        raise NotImplementedError

    def get_latest_caption(self, page):
        """Extract latest caption snippet. Return dict with speaker/text or None."""
        return None

    def get_meeting_ended_selector(self):
        """Return text that indicates meeting ended."""
        return "You left the meeting"

    def get_meeting_end_indicators(self):
        return [self.get_meeting_ended_selector()]

    def has_meeting_ended(self, page) -> bool:
        try:
            for indicator in self.get_meeting_end_indicators():
                if page.locator(f'text={indicator}').first.is_visible(timeout=250):
                    return True
        except Exception:
            pass
        return False

    def get_platform_name(self):
        raise NotImplementedError


class GoogleMeetStrategy(PlatformStrategy):
    def get_auth_check_url(self):
        return "https://accounts.google.com/"

    def is_logged_in(self, page):
        # If email input is visible, we are NOT logged in
        return not page.locator('input[type="email"]').is_visible()

    def enable_captions(self, page):
        page.keyboard.press('c')

    def get_join_actions(self, page, url, bot_name):
        # Disable mic/cam
        try:
            page.keyboard.press('Control+d')
            page.keyboard.press('Control+e')
        except:
            pass
        # Fill bot name
        try:
            page.fill('input[placeholder="Your name"]', bot_name, timeout=2000)
        except:
            pass
        # Click join button
        try:
            page.click('span:has-text("Ask to join")', timeout=2000)
        except:
            try:
                page.click('span:has-text("Join now")', timeout=2000)
            except:
                pass

    def get_active_speaker(self, page):
        active_label = page.evaluate('''() => {
            let captionNames = document.querySelectorAll('.zs7s8d, .abjB1e, div[style*="font-weight: bold"]');
            if (captionNames.length > 0) {
                let latestCaptionName = captionNames[captionNames.length - 1].innerText;
                if (latestCaptionName) return latestCaptionName;
            }
            let volumeBars = document.querySelectorAll('.IisKId, .FxcRjc');
            if (volumeBars.length > 0) {
                let parent = volumeBars[0].closest('[data-allocation-index]');
                if (parent) return parent.innerText;
            }
            return "";
        }''')
        return normalize_person_name(active_label.split('\\n')[0] if active_label else "")

    def get_latest_caption(self, page):
        payload = page.evaluate('''() => {
            const speakerSelectors = [
                '.zs7s8d',
                '.abjB1e',
                '[data-self-name]'
            ];
            const textSelectors = [
                '.iTTPOb',
                '.a4cQT',
                '.bh44bd',
                '[jsname="YS01Ge"]',
                '[class*="caption"] [class*="text"]'
            ];

            const latestTextNode = (() => {
                for (const selector of textSelectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (let i = nodes.length - 1; i >= 0; i -= 1) {
                        const value = (nodes[i]?.innerText || nodes[i]?.textContent || '').trim();
                        if (value) return value;
                    }
                }
                return '';
            })();

            const latestSpeakerNode = (() => {
                for (const selector of speakerSelectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (let i = nodes.length - 1; i >= 0; i -= 1) {
                        const value = (nodes[i]?.innerText || nodes[i]?.textContent || '').trim();
                        if (value) return value;
                    }
                }
                return '';
            })();

            if (!latestTextNode && !latestSpeakerNode) return null;
            return { speaker: latestSpeakerNode, text: latestTextNode };
        }''')

        if not isinstance(payload, dict):
            return None

        speaker = normalize_person_name((payload.get("speaker") or "").strip())
        text = re.sub(r"\s+", " ", (payload.get("text") or "").strip())
        if not text:
            return None
        return {"speaker": speaker, "text": text}

    def get_meeting_ended_selector(self):
        return "You left the meeting"

    def get_meeting_end_indicators(self):
        return ["You left the meeting", "The meeting has ended", "Call ended"]

    def get_platform_name(self):
        return "Google Meet"


class TeamsStrategy(PlatformStrategy):
    def get_auth_check_url(self):
        return "https://login.microsoftonline.com/"

    def is_logged_in(self, page):
        # Simple check: if email input visible or sign-in text, not logged in
        try:
            if page.locator('input[type="email"]').first.is_visible():
                return False
            if page.locator('text=Sign in').first.is_visible():
                return False
            if page.locator('button:has-text("Use another account")').first.is_visible():
                return False
            return True
        except:
            return True  # Assume logged in if check fails

    def enable_captions(self, page):
        # Teams captions: Ctrl+Shift+L
        try:
            page.keyboard.press('Control+Shift+L')
        except:
            pass

    def get_join_actions(self, page, url, bot_name):
        click_first_visible(
            page,
            [
                'button:has-text("Continue on this browser")',
                'a:has-text("Continue on this browser")',
                'button:has-text("Join on the web instead")',
                'a:has-text("Join on the web instead")',
            ],
            timeout=4000,
        )

        click_first_visible(
            page,
            [
                'button[aria-label*="Microphone" i]',
                'button[aria-label*="mute" i]',
                'button[data-tid*="toggle-mute"]',
            ],
            timeout=2000,
        )
        click_first_visible(
            page,
            [
                'button[aria-label*="Camera" i]',
                'button[aria-label*="video" i]',
                'button[data-tid*="toggle-video"]',
            ],
            timeout=2000,
        )

        fill_first_visible(
            page,
            [
                'input[name="name"]',
                'input[placeholder*="name" i]',
                'input[data-tid*="display-name"]',
            ],
            bot_name,
            timeout=2500,
        )

        click_first_visible(
            page,
            [
                'button:has-text("Join now")',
                'button:has-text("Join")',
                'button:has-text("Continue")',
                'button[data-tid*="prejoin-join-button"]',
            ],
            timeout=4000,
        )

    def get_active_speaker(self, page):
        active_name = page.evaluate('''() => {
            const directSelectors = [
                '[data-tid="active-speaker-name"]',
                '[data-tid*="active-speaker"] [data-tid*="display-name"]',
                '.subtitle-speaker-name',
                '.caption-text-speaker',
                '.ts-live-transcription-speaker'
            ];
            for (const selector of directSelectors) {
                const el = document.querySelector(selector);
                if (el && el.innerText) return el.innerText.trim();
            }

            const ariaSpeaking = document.querySelector('[aria-label*=" is speaking" i], [aria-label*=" is talking" i]');
            if (ariaSpeaking) {
                const label = (ariaSpeaking.getAttribute('aria-label') || '').trim();
                if (label) {
                    return label
                        .replace(/ is speaking.*/i, '')
                        .replace(/ is talking.*/i, '')
                        .trim();
                }
            }

            return "";
        }''')
        return normalize_person_name(active_name)

    def get_latest_caption(self, page):
        payload = page.evaluate('''() => {
            const speakerSelectors = [
                '.caption-text-speaker',
                '.ts-live-transcription-speaker',
                '[data-tid*="closed-caption-speaker"]',
                '[data-tid*="transcription-speaker"]'
            ];
            const textSelectors = [
                '.caption-text-line',
                '.ts-live-transcription-text',
                '[data-tid*="closed-caption-text"]',
                '[data-tid*="transcription-text"]'
            ];

            const pickLatest = (selectors) => {
                for (const selector of selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (let i = nodes.length - 1; i >= 0; i -= 1) {
                        const value = (nodes[i]?.innerText || nodes[i]?.textContent || '').trim();
                        if (value) return value;
                    }
                }
                return '';
            };

            const speaker = pickLatest(speakerSelectors);
            const text = pickLatest(textSelectors);
            if (!speaker && !text) return null;
            return { speaker, text };
        }''')

        if not isinstance(payload, dict):
            return None

        speaker = normalize_person_name((payload.get("speaker") or "").strip())
        text = re.sub(r"\s+", " ", (payload.get("text") or "").strip())
        if not text:
            return None
        return {"speaker": speaker, "text": text}

    def get_meeting_end_indicators(self):
        return [
            "You have been removed",
            "You left the meeting",
            "The meeting has ended",
            "This meeting has ended",
        ]

    def get_platform_name(self):
        return "Microsoft Teams"


class ZoomStrategy(PlatformStrategy):
    def get_auth_check_url(self):
        # Zoom usually doesn't require SSO for joining as guest
        return None

    def is_logged_in(self, page):
        return True  # Not applicable

    def enable_captions(self, page):
        try:
            page.keyboard.press('Alt+C')
        except:
            pass

    def get_join_actions(self, page, url, bot_name):
        click_first_visible(
            page,
            [
                'a:has-text("Launch Meeting")',
                'button:has-text("Launch Meeting")',
            ],
            timeout=2500,
        )

        click_first_visible(
            page,
            [
                'a:has-text("Join from Your Browser")',
                'button:has-text("Join from Your Browser")',
                'a:has-text("join from your browser")',
            ],
            timeout=6000,
        )

        fill_first_visible(
            page,
            [
                'input[name="name"]',
                'input#input-for-name',
                'input[placeholder*="name" i]',
            ],
            bot_name,
            timeout=2500,
        )

        click_first_visible(
            page,
            [
                'button:has-text("Join")',
                'button:has-text("Join Meeting")',
                'button:has-text("Continue")',
            ],
            timeout=4000,
        )

    def get_active_speaker(self, page):
        active_name = page.evaluate('''() => {
            const ariaSpeaking = document.querySelector('[aria-label*=" is talking" i], [aria-label*=" is speaking" i]');
            if (ariaSpeaking) {
                const label = (ariaSpeaking.getAttribute('aria-label') || '').trim();
                if (label) {
                    return label
                        .replace(/ is talking.*/i, '')
                        .replace(/ is speaking.*/i, '')
                        .trim();
                }
            }

            const captionSelectors = [
                '.caption-speaker-name',
                '.caption-text-speaker',
                '[data-speaker-name]',
                '[aria-live="polite"] .speaker-name',
                '[aria-live="polite"] [class*="speaker"]'
            ];
            for (const selector of captionSelectors) {
                const nodes = Array.from(document.querySelectorAll(selector));
                if (nodes.length > 0) {
                    const latest = nodes[nodes.length - 1];
                    const text = (latest?.innerText || latest?.textContent || '').trim();
                    if (text) return text;
                }
            }

            const activeVideo = document.querySelector('[aria-selected="true"], .active-speaker, .video-holder.active');
            if (activeVideo) {
                const nameEl = activeVideo.querySelector('.name-text, .participant-name, [aria-label*="name"], .caption-text-speaker, .caption-speaker-name');
                if (nameEl && nameEl.innerText) return nameEl.innerText.trim();
            }

            return "";
        }''')
        return normalize_person_name(active_name)

    def get_latest_caption(self, page):
        payload = page.evaluate('''() => {
            const speakerSelectors = [
                '.caption-speaker-name',
                '.caption-text-speaker',
                '[data-speaker-name]',
                '[aria-live="polite"] [class*="speaker"]'
            ];
            const textSelectors = [
                '.caption-line-text',
                '.caption-text',
                '[aria-live="polite"] [class*="caption"] [class*="text"]',
                '[aria-live="polite"] [class*="line"]'
            ];

            const pickLatest = (selectors) => {
                for (const selector of selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (let i = nodes.length - 1; i >= 0; i -= 1) {
                        const value = (nodes[i]?.innerText || nodes[i]?.textContent || '').trim();
                        if (value) return value;
                    }
                }
                return '';
            };

            const speaker = pickLatest(speakerSelectors);
            const text = pickLatest(textSelectors);
            if (!speaker && !text) return null;
            return { speaker, text };
        }''')

        if not isinstance(payload, dict):
            return None

        speaker = normalize_person_name((payload.get("speaker") or "").strip())
        text = re.sub(r"\s+", " ", (payload.get("text") or "").strip())
        if not text:
            return None
        return {"speaker": speaker, "text": text}

    def get_meeting_end_indicators(self):
        return [
            "You have been removed from the meeting",
            "This meeting has ended",
            "Meeting has ended",
            "The host has ended this meeting",
            "The host has ended the meeting",
            "You have left the meeting",
            "This webinar has ended",
            "Thanks for attending",
        ]

    def has_meeting_ended(self, page) -> bool:
        if super().has_meeting_ended(page):
            return True

        try:
            current_url = (page.url or "").lower()
        except Exception:
            current_url = ""

        # Zoom often navigates to leave/end URLs when the session closes.
        if any(token in current_url for token in ("/wc/leave", "/wc/end", "/ended", "/postattendee")):
            return True

        try:
            return bool(page.evaluate('''() => {
                const bodyText = (document.body?.innerText || "").toLowerCase();
                const endMarkers = [
                    "this meeting has ended",
                    "meeting has ended",
                    "the host has ended this meeting",
                    "the host has ended the meeting",
                    "you have left the meeting",
                    "you have been removed from the meeting",
                    "this webinar has ended",
                    "thanks for attending"
                ];
                return endMarkers.some((marker) => bodyText.includes(marker));
            }'''))
        except Exception:
            return False

    def get_platform_name(self):
        return "Zoom"


def get_strategy(platform):
    normalized_platform = normalize_platform_name(platform)
    strategies = {
        "meet": GoogleMeetStrategy(),
        "teams": TeamsStrategy(),
        "zoom": ZoomStrategy(),
    }
    return strategies.get(normalized_platform, GoogleMeetStrategy())


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = SCRIPT_DIR
    return os.path.join(base_path, relative_path)

# Load models
model_path = resource_path("resemblyzer_model/pretrained.pt")
if not os.path.exists(model_path):
    print("\nError: Pretrained model file not found!")
    sys.exit(1)

encoder = VoiceEncoder(device="cpu")

# Constants
SAMPLE_RATE = 16000
SIMILARITY_THRESHOLD = 0.7
AZURE_AI_ENDPOINT = "https://models.github.ai/inference"
AZURE_AI_MODEL = "openai/gpt-4.1"


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or str(default)).strip())
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or str(default)).strip())
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = (os.environ.get(name) or "").strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


ONLINE_MAX_DURATION_SECONDS = max(600, _env_int("ONLINE_MAX_DURATION_SECONDS", 10800))
ONLINE_IDLE_STOP_SECONDS = max(60, _env_int("ONLINE_IDLE_STOP_SECONDS", 180))
ONLINE_IDLE_MIN_RUNTIME_SECONDS = max(30, _env_int("ONLINE_IDLE_MIN_RUNTIME_SECONDS", 90))
AUDIO_ACTIVITY_RMS_THRESHOLD = max(0.0005, _env_float("AUDIO_ACTIVITY_RMS_THRESHOLD", 0.003))
PLAYWRIGHT_HEADLESS = _env_bool("PLAYWRIGHT_HEADLESS", False)
PLAYWRIGHT_CHANNEL = (os.environ.get("PLAYWRIGHT_CHANNEL") or "chrome").strip()

models = {
    "english": WhisperModel("base.en", device="cpu", compute_type="float32"),
    "multilingual": WhisperModel("small", device="cpu", compute_type="float32")
}

# Accept common user-entered language variants from the UI text box.
LANGUAGE_ALIASES = {
    "en": "english",
    "eng": "english",
    "english": "english",
    "hi": "hindi",
    "hin": "hindi",
    "hindi": "hindi",
    "gu": "gujarati",
    "guj": "gujarati",
    "gujarati": "gujarati",
    "gujrati": "gujarati",
}

language_map = {
    "english": "en",
    "hindi": "hi",
    "gujarati": "gu"
}

hindi_normalizer = indic_normalize.IndicNormalizerFactory().get_normalizer("hi")
gujarati_normalizer = indic_normalize.IndicNormalizerFactory().get_normalizer("gu")
HINDI_CHAR_RANGE = r'[\u0900-\u097F]'
GUJARATI_CHAR_RANGE = r'[\u0A80-\u0AFF]'

class SpeakerDiarizer:
    """Per-recording speaker identification using voice embeddings.

    This class maintains isolated state for a single recording session,
    preventing cross-contamination between concurrent recordings.
    """
    def __init__(self):
        self.embeddings = []
        self.labels = []
        self.counter = 1

    def identify_speaker(self, new_embed) -> str:
        """Identify or register a speaker based on voice embedding."""
        if not self.embeddings:
            self.embeddings.append(new_embed)
            self.labels.append("Speaker 1")
            return "Speaker 1"
        similarities = [np.dot(embed, new_embed) for embed in self.embeddings]
        max_sim = max(similarities)
        if max_sim > SIMILARITY_THRESHOLD:
            return self.labels[similarities.index(max_sim)]

        self.counter += 1
        new_label = f"Speaker {self.counter}"
        self.embeddings.append(new_embed)
        self.labels.append(new_label)
        return new_label

def is_hindi_text(text: str) -> bool: return bool(re.search(HINDI_CHAR_RANGE, text))
def is_gujarati_text(text: str) -> bool: return bool(re.search(GUJARATI_CHAR_RANGE, text))

def normalize_text(text: str, language: str) -> str:
    if language == "Hindi":
        normalized = hindi_normalizer.normalize(text)
        chars = ''.join(re.findall(HINDI_CHAR_RANGE, normalized))
    else:
        normalized = gujarati_normalizer.normalize(text)
        chars = ''.join(re.findall(GUJARATI_CHAR_RANGE, normalized))
    tokens = indic_tokenize.trivial_tokenize(chars)
    return " ".join(tokens)


def normalize_language_choice(language: str):
    selected = (language or "Auto").strip()
    selected_lower = selected.lower()
    canonical_key = LANGUAGE_ALIASES.get(selected_lower, selected_lower)

    if canonical_key == "english":
        return "English", "english"
    if canonical_key == "hindi":
        return "Hindi", "hindi"
    if canonical_key == "gujarati":
        return "Gujarati", "gujarati"

    return selected if selected else "Auto", canonical_key


def transcribe_segments_with_fallback(model, wav_path: str, language_hint: str | None):
    segments, info = model.transcribe(wav_path, language=language_hint)
    segment_list = list(segments)
    has_text = any((getattr(seg, "text", "") or "").strip() for seg in segment_list)

    # Forced language can occasionally yield no text for short/noisy clips; retry in auto mode.
    if has_text or language_hint is None:
        return segment_list, info, language_hint

    print(f"[Transcription Warning] No text with forced language '{language_hint}'. Retrying with auto language detection...")
    retry_segments, retry_info = model.transcribe(wav_path, language=None)
    retry_list = list(retry_segments)
    return retry_list, retry_info, None

def resolve_transcription_mode(language: str):
    mode_label, canonical_key = normalize_language_choice(language)

    if canonical_key == "english":
        return models["english"], "en", "English"

    language_hint = language_map.get(canonical_key)
    return models["multilingual"], language_hint, mode_label


def get_summary(text: str, language: str = "Auto", participants=None) -> str:
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return "Error: GITHUB_TOKEN environment variable not set in .env."

        client = ChatCompletionsClient(endpoint=AZURE_AI_ENDPOINT, credential=AzureKeyCredential(token))

        extra_context = f"\nList of Participants detected: {', '.join(participants)}" if participants else ""
        preferred_language = (language or "Auto").strip()
        if preferred_language.lower() == "auto":
            preferred_language = "Use the dominant language in the transcript"

        user_msg = (
            "Summarize the following meeting transcript in a clear and structured format.\n"
            f"Preferred response language: {preferred_language}.\n"
            "If the transcript contains multiple languages, preserve important names and quotes exactly.\n\n"
            f"Transcript:\n{text}{extra_context}"
        )

        messages = [
            SystemMessage('''You are an expert meeting assistant. Analyze the transcript and provide:
- Meeting Summary
- Agenda
- Key Points and Decisions
- Speakers and Roles
- Action Items
- Number of Unique Speakers'''),
            UserMessage(user_msg)
        ]
        response = client.complete(messages=messages, temperature=0.7, top_p=1, model=AZURE_AI_MODEL)
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error connecting to Azure AI: {str(e)}"

def speaker_id(new_embed):
    global speaker_embeddings, speaker_labels, speaker_counter
    if not speaker_embeddings:
        speaker_embeddings.append(new_embed)
        speaker_labels.append(f"Speaker 1")
        return "Speaker 1"
    similarities = [np.dot(embed, new_embed) for embed in speaker_embeddings]
    max_sim = max(similarities)
    if max_sim > SIMILARITY_THRESHOLD:
        return speaker_labels[similarities.index(max_sim)]
    
    speaker_counter += 1
    new_label = f"Speaker {speaker_counter}"
    speaker_embeddings.append(new_embed)
    speaker_labels.append(new_label)
    return new_label

def process_audio_file(
    wav_path: str,
    title: str,
    language: str,
    participants: list = None,
    dom_speaker_log: list = None,
    platform: str = "meet",
    requester_user_id: str = None,
    diarizer: SpeakerDiarizer = None,  # Per-recording state
):
    """Core translation pipeline separated from recording mechanism."""
    # Speaker diarizer is required unless DOM speaker log is provided (online bot)
    # (no global state; diarizer instance is passed per recording)

    # Read audio for segmentation processing
    samplerate, audio_data = wavfile.read(wav_path)
    
    # Convert to mono float32 for processing
    if len(audio_data.shape) > 1: audio_data = audio_data.mean(axis=1)
    if audio_data.dtype == np.int16: audio_data = audio_data.astype(np.float32) / 32768.0

    if not np.any(audio_data): return "Silent audio detected.", "No summary available.", None

    try:
        model, language_hint, mode_label = resolve_transcription_mode(language)
        hint_label = language_hint if language_hint else "auto"
        print(f"Transcribing with {mode_label} mode (language hint: {hint_label})...")
        segments, info, used_language_hint = transcribe_segments_with_fallback(model, wav_path, language_hint)
        detected_language = getattr(info, "language", None)
        language_for_storage = detected_language or mode_label
        
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + (title.replace(" ", "_") or "Untitled")
        full_text = ""
        
        meeting_db_id = None
        if supabase_client:
            base_payload = {
                "title": title or "Untitled Meeting",
                "language": language_for_storage,
                "status": "recording",
                "platform": platform,
            }

            insert_variants = []
            seen_payload_signatures = set()
            owner_columns = [None]
            if requester_user_id:
                owner_columns = ["user_id", "created_by", "owner_id", None]

            for owner_column in owner_columns:
                payload_with_owner = dict(base_payload)
                if owner_column:
                    payload_with_owner[owner_column] = requester_user_id

                for include_platform in (True, False):
                    candidate_payload = dict(payload_with_owner)
                    if not include_platform:
                        candidate_payload.pop("platform", None)

                    signature = tuple(sorted(candidate_payload.items()))
                    if signature in seen_payload_signatures:
                        continue

                    seen_payload_signatures.add(signature)
                    insert_variants.append(candidate_payload)

            print("[BOT] Syncing meeting to Supabase Database...")
            last_insert_error = None
            for attempt_payload in insert_variants:
                try:
                    res = supabase_client.table("meetings").insert(attempt_payload).execute()
                    if res.data and len(res.data) > 0:
                        meeting_db_id = res.data[0]["id"]
                    break
                except Exception as insert_error:
                    last_insert_error = insert_error

            if meeting_db_id is None and last_insert_error is not None:
                print(f"[Supabase Error] Could not create meeting: {last_insert_error}")

        if used_language_hint is None and language_hint is not None:
            print("[Transcription Info] Used auto language fallback after forced language produced no text.")

        print("Processing segments for speaker detection...")
        for seg in segments:
            start_idx = int(seg.start * samplerate)
            end_idx = int(seg.end * samplerate)
            segment_audio = audio_data[start_idx:end_idx].flatten()
            text = (seg.text or "").strip()

            if len(segment_audio) < samplerate // 4 and not text:
                continue
            if not text:
                continue

            speaker = "Unknown"
            # -----------------------------------------------------
            # BRANCH A: Online Bot (DOM Mutation Timestamp Mapping)
            # -----------------------------------------------------
            if dom_speaker_log and len(dom_speaker_log) > 0:
                best_match = None
                min_diff = 9999
                for ts, name in dom_speaker_log:
                    diff = abs(ts - seg.start)
                    if diff < min_diff:
                        min_diff = diff
                        best_match = name
                
                # Prefer nearest DOM marker with a wider sync window for practical alignment drift.
                if min_diff < 12.0 and best_match:
                    speaker = best_match
                else:
                    # Fallback: use latest known speaker before this segment when close enough.
                    latest_prior_name = None
                    latest_prior_ts = None
                    for ts, name in dom_speaker_log:
                        if ts <= seg.start and name:
                            latest_prior_ts = ts
                            latest_prior_name = name
                        elif ts > seg.start:
                            break

                    if latest_prior_name is not None and latest_prior_ts is not None and (seg.start - latest_prior_ts) <= 20.0:
                        speaker = latest_prior_name
                    else:
                        speaker = "Speaker"

            # -----------------------------------------------------
            # BRANCH B: Local Microphone (Resemblyzer AI Diarization)
            # -----------------------------------------------------
            else:
                try:
                    wav_seg = preprocess_wav(segment_audio, samplerate)
                    embed = encoder.embed_utterance(wav_seg)
                    if diarizer is None:
                        raise RuntimeError("Speaker diarizer not initialized for local recording")
                    speaker = diarizer.identify_speaker(embed)
                except:
                    speaker = "Unknown"

            start_ts = datetime.utcfromtimestamp(seg.start).strftime("%H:%M:%S")
            end_ts = datetime.utcfromtimestamp(seg.end).strftime("%H:%M:%S")
            
            # Sync individual line to Database
            if supabase_client and meeting_db_id:
                try:
                    supabase_client.table("transcripts").insert({
                        "meeting_id": meeting_db_id,
                        "speaker_name": speaker,
                        "spoken_text": text,
                        "start_time_seconds": seg.start
                    }).execute()
                except Exception as e:
                    pass
            
            full_text += f"[{start_ts} - {end_ts}] {speaker}: {text}\n"

        if not full_text.strip():
            print("[Transcription Warning] No speech text detected in recording.")
            summary = (
                "No speech could be transcribed from this recording. "
                "Please speak for at least 5 to 10 seconds, check microphone/system audio, "
                "and try again with Auto, Hindi, or Gujarati language mode."
            )
        else:
            print("Generating AI Summary...")
            summary = get_summary(full_text, language_for_storage, participants)
        
        # Save summary out to Database
        if supabase_client and meeting_db_id:
            try:
                supabase_client.table("meetings").update({
                    "summary": summary,
                    "status": "completed"
                }).eq("id", meeting_db_id).execute()
                print("[BOT] ✅ Successfully persisted final meeting state to Supabase!")
            except Exception as e:
                print(f"[Supabase Error] Could not finalize meeting summary: {e}")

        output_filename = f"{filename}.txt"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(f"=== {filename} ===\n\n")
            if participants: f.write(f"=== PARTICIPANTS ===\n{', '.join(participants)}\n\n")
            f.write("=== TRANSCRIPT ===\n\n" + full_text)
            f.write("\n\n=== SUMMARY ===\n\n" + summary)

        if run_post_meeting_integrations:
            try:
                integration_status = run_post_meeting_integrations(
                    title=title or "Untitled Meeting",
                    platform=platform,
                    language=language_for_storage,
                    summary=summary,
                    transcript=full_text,
                    participants=participants or [],
                    output_filename=output_filename,
                    requester_user_id=requester_user_id,
                )
                print(
                    f"[Integrations] Slack={integration_status.get('slack')} "
                    f"Jira={integration_status.get('jira')} "
                    f"Notion={integration_status.get('notion')}"
                )
                for warning in integration_status.get("warnings", []):
                    print(f"[Integrations Warning] {warning}")
            except Exception as integration_error:  # noqa: BLE001
                print(f"[Integrations Error] {integration_error}")
        
        return full_text, summary, output_filename
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        return str(e), "", None

def record_local(minutes: float, title: str, language: str, stop_event=None, requester_user_id: str = None, diarizer: SpeakerDiarizer = None):
    """Workflow 1: Local Microphone Capture.

    If stop_event is provided, recording continues until stop_event is set.
    """
    timed_mode = minutes is not None and minutes > 0
    if not timed_mode and stop_event is None:
        raise RuntimeError("Local recording requires a duration or a stop signal")

    if timed_mode and stop_event is None:
        duration = int(minutes * 60)
        print(f"Recording from local microphone for {minutes:.2f} minutes...")
        audio = sd.rec(int(SAMPLE_RATE * duration), samplerate=SAMPLE_RATE, channels=1)
        sd.wait()
    else:
        print("Recording from local microphone... Use Stop Recording in the app when done.")
        chunks = []
        started_at = time.time()
        # Safety cap avoids runaway recording if stop is never triggered.
        safety_limit_seconds = int(minutes * 60) if timed_mode else 4 * 60 * 60

        def callback(indata, frames, time_info, status):
            if status:
                print(f"Audio callback status: {status}")
            chunks.append(indata.copy())

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                if safety_limit_seconds and (time.time() - started_at) >= safety_limit_seconds:
                    print("Reached local recording safety limit. Stopping capture.")
                    break
                time.sleep(0.1)

        if not chunks:
            raise RuntimeError("No audio was captured from local microphone")
        audio = np.concatenate(chunks, axis=0)

    print("Recording complete. Processing transcription...")
    if audio.ndim > 1:
        audio = audio[:, 0]

    wav_path = "temp_local.wav"
    wavfile.write(wav_path, SAMPLE_RATE, (np.clip(audio, -1, 1) * 32767).astype(np.int16))

    res = process_audio_file(
        wav_path,
        title,
        language,
        None,
        None,
        platform="local",
        requester_user_id=requester_user_id,
        diarizer=diarizer,
    )
    if os.path.exists(wav_path): os.remove(wav_path)
    return res

def join_meeting_and_record(
    url: str,
    title: str,
    language: str,
    platform: str = "meet",
    requester_user_id: str = None,
    live_event_callback=None,
    diarizer: SpeakerDiarizer = None,
):
    """Workflow 2: Online Bot Capture (Playwright + WASAPI Loopback)"""
    if not ONLINE_BOT_AVAILABLE:
        raise RuntimeError(
            "Online bot dependencies are missing. Install: pip install playwright pyaudiowpatch, then run: python -m playwright install chromium"
        )

    platform = normalize_platform_name(platform)
    if platform not in {"meet", "teams", "zoom"}:
        platform = detect_platform_from_url(url)

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    wav_path = "temp_meeting.wav"
    stop_signal = threading.Event()
    participants = set()

    # Get platform-specific strategy
    strategy = get_strategy(platform)

    with pyaudio.PyAudio() as p:
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

            # Find loopback
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break
        except Exception as e:
            raise RuntimeError(f"Audio device error: {e}. Check pyaudiowpatch installation and loopback device access.")

        wf = wave.open(wav_path, 'wb')
        wf.setnchannels(default_speakers["maxInputChannels"])
        wf.setsampwidth(pyaudio.get_sample_size(pyaudio.paInt16))
        wf.setframerate(int(default_speakers["defaultSampleRate"]))

        audio_state = {
            "last_activity_ts": time.time(),
            "last_rms": 0.0,
        }

        def audio_callback(in_data, frame_count, time_info, status):
            if not stop_signal.is_set():
                wf.writeframes(in_data)

                try:
                    samples = np.frombuffer(in_data, dtype=np.int16)
                    if samples.size > 0:
                        normalized = samples.astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(normalized * normalized)))
                        audio_state["last_rms"] = rms
                        if rms >= AUDIO_ACTIVITY_RMS_THRESHOLD:
                            audio_state["last_activity_ts"] = time.time()
                except Exception:
                    pass
            return (in_data, pyaudio.paContinue)

        def emit_live_event(payload: dict):
            if not callable(live_event_callback):
                return
            try:
                live_event_callback(payload)
            except Exception:
                pass

        stream = p.open(format=pyaudio.paInt16,
                        channels=default_speakers["maxInputChannels"],
                        rate=int(default_speakers["defaultSampleRate"]),
                        frames_per_buffer=512,
                        input=True,
                        input_device_index=default_speakers["index"],
                        stream_callback=audio_callback)

        print(f"\n[BOT] Opening meeting: {url}")

        # On Windows, Playwright browser subprocesses require Proactor loop policy.
        if os.name == "nt":
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass

        with sync_playwright() as pw:
            user_data_path = os.path.join(SCRIPT_DIR, "bot_profile")

            browser_launch_kwargs = {
                "user_data_dir": user_data_path,
                "headless": PLAYWRIGHT_HEADLESS,
                "args": [
                    '--use-fake-ui-for-media-stream',
                    '--disable-blink-features=AutomationControlled',
                    '--profile-directory=Default',
                    '--disable-guest-mode',
                ],
                "ignore_default_args": ["--enable-automation"],
                "permissions": ['camera', 'microphone'],
            }
            if PLAYWRIGHT_CHANNEL:
                browser_launch_kwargs["channel"] = PLAYWRIGHT_CHANNEL

            context = pw.chromium.launch_persistent_context(**browser_launch_kwargs)
            page = context.pages[0] if context.pages else context.new_page()

            # Authentication check (platform-specific)
            print("\n[BOT] Checking authentication status...")
            auth_url = strategy.get_auth_check_url()
            if auth_url:
                navigate_with_fallback(
                    page,
                    auth_url,
                    label=f"{strategy.get_platform_name()} auth page",
                    timeout_ms=60000,
                )
                page.wait_for_timeout(3000)
                if not strategy.is_logged_in(page):
                    print(f"\n[BOT] ⚠️ You are not logged in to {strategy.get_platform_name()}! The platform's security blocks robots from typing passwords.")
                    print("[BOT] 👉 PLEASE LOG IN MANUALLY right now in the Chrome window that just opened.")
                    print("[BOT] 👉 Waiting up to 120 seconds for manual login to complete...")

                    login_deadline = time.time() + 120
                    while time.time() < login_deadline:
                        page.wait_for_timeout(1500)
                        if strategy.is_logged_in(page):
                            break

                    if not strategy.is_logged_in(page):
                        raise RuntimeError(
                            f"Login required for {strategy.get_platform_name()}. Complete sign-in in the opened browser window, then retry."
                        )
                    print("[BOT] ✅ Manual login detected. Continuing to meeting join flow.")
                else:
                    print("\n[BOT] ✅ Profile is already authenticated. Skipping login!")
            else:
                print("\n[BOT] No authentication required for this platform.")

            stream.start_stream()
            recording_start_time = time.time()
            print("[BOT] Audio recording started (System Volume Loopback active)")

            navigate_with_fallback(
                page,
                url,
                label=f"{strategy.get_platform_name()} meeting page",
                timeout_ms=90000,
            )

            try:
                page.wait_for_timeout(3000)
                # Use strategy to perform join actions
                strategy.get_join_actions(page, url, bot_name="Smart Notes Bot")
                print("[BOT] Interaction completed. Hanging out in meeting...")
            except Exception as e:
                print(f"[BOT] Automated interaction failed: {e}. You might need to join manually in the browser.")

            print("\n>>> TYPE 'q' AND PRESS ENTER HERE AT ANY TIME TO END THE RECORDING <<<\n")

            # Simple Background Input Listener to stop manually
            def check_quit():
                while not stop_signal.is_set():
                    try:
                        if input().strip().lower() == 'q':
                            stop_signal.set()
                            return
                    except EOFError:
                        # Non-interactive runs (like API servers) may not have stdin.
                        return
            threading.Thread(target=check_quit, daemon=True).start()

            dom_speaker_log = []
            last_emitted_speaker = ""
            last_speaker_emit_ts = 0.0
            last_caption_signature = ""

            # Enable captions (platform-specific)
            try:
                strategy.enable_captions(page)
                page.wait_for_timeout(1000)
            except:
                pass

            # Poll for participants while recording
            while not stop_signal.is_set():
                now = time.time()

                if now - recording_start_time >= ONLINE_MAX_DURATION_SECONDS:
                    print("[BOT] Online recording reached configured max duration. Stopping capture.")
                    stop_signal.set()
                    break

                if (
                    now - recording_start_time >= ONLINE_IDLE_MIN_RUNTIME_SECONDS
                    and now - audio_state.get("last_activity_ts", now) >= ONLINE_IDLE_STOP_SECONDS
                ):
                    print("[BOT] No meeting audio detected for a while. Stopping recording.")
                    stop_signal.set()
                    break

                try:
                    if page.is_closed():
                        print("[BOT] Meeting page closed. Stopping recording.")
                        stop_signal.set()
                        break
                except Exception:
                    pass

                speaker_name = None

                try:
                    speaker_name = strategy.get_active_speaker(page)
                    if speaker_name:
                        rel_timestamp = time.time() - recording_start_time
                        dom_speaker_log.append((rel_timestamp, speaker_name))
                        participants.add(speaker_name)
                        if speaker_name != last_emitted_speaker or (time.time() - last_speaker_emit_ts) >= 2.0:
                            emit_live_event(
                                {
                                    "type": "speaker",
                                    "active_speaker": speaker_name,
                                    "participants": sorted(participants),
                                    "elapsed_seconds": rel_timestamp,
                                    "last_audio_rms": audio_state.get("last_rms", 0.0),
                                }
                            )
                            last_emitted_speaker = speaker_name
                            last_speaker_emit_ts = time.time()
                except:
                    pass

                try:
                    caption = strategy.get_latest_caption(page)
                    if caption and caption.get("text"):
                        rel_timestamp = time.time() - recording_start_time
                        caption_speaker = caption.get("speaker") or speaker_name or "Participant"
                        caption_text = re.sub(r"\s+", " ", caption.get("text", "")).strip()
                        if caption_text:
                            participants.add(caption_speaker)
                            signature = f"{caption_speaker.lower()}::{caption_text.lower()}"
                            if signature != last_caption_signature:
                                last_caption_signature = signature
                                emit_live_event(
                                    {
                                        "type": "caption",
                                        "active_speaker": caption_speaker,
                                        "caption_text": caption_text,
                                        "participants": sorted(participants),
                                        "elapsed_seconds": rel_timestamp,
                                        "last_audio_rms": audio_state.get("last_rms", 0.0),
                                    }
                                )
                except:
                    pass

                # Auto-stop if meeting ended indicator appears
                try:
                    if strategy.has_meeting_ended(page):
                        print(f"[BOT] {strategy.get_platform_name()} meeting ended. Stopping recording.")
                        stop_signal.set()
                        break
                except:
                    pass

                time.sleep(0.5)

            stop_signal.set()
            stream.stop_stream()
            stream.close()
            wf.close()
            context.close()

    print("[BOT] Extraction finished.")
    res = process_audio_file(
        wav_path,
        title,
        language,
        list(participants),
        dom_speaker_log=dom_speaker_log,
        platform=platform,
        requester_user_id=requester_user_id,
        diarizer=diarizer,
    )
    if os.path.exists(wav_path): os.remove(wav_path)
    return res

def main():
    print("=== Audio Transcription System ===")
    print("1. Local Microphone Capture")
    print("2. Online Meeting Bot (Google Meet / Teams / Zoom)")

    choice = input("Select mode (1/2): ").strip()
    title = input("Enter conversation title (press Enter for 'Untitled'): ").strip()
    language = input("Select language (Auto/English/Hindi/Gujarati or any language name) [default: Auto]: ").strip()
    if not language:
        language = "Auto"

    if choice == "2":
        url = input("Enter meeting URL: ").strip()
        # Auto-detect platform from URL
        platform = detect_platform_from_url(url)
        print(f"Detected platform: {strategy.get_platform_name() if (strategy := get_strategy(platform)) else 'Unknown'}")
        transcript, summary, filename = join_meeting_and_record(url, title, language, platform=platform)
    else:
        while True:
            try:
                minutes = float(input("Enter recording duration in minutes (minimum 0.1): "))
                if minutes >= 0.1: break
            except ValueError: pass
        transcript, summary, filename = record_local(minutes, title, language)
        
    print(f"\nOutput saved to {filename}")

if __name__ == "__main__":
    main()
