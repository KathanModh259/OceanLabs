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
        supabase_client = None
except ImportError:
    supabase_client = None

# Optional dependencies for Online Bot Mode
try:
    import pyaudiowpatch as pyaudio
    from playwright.sync_api import sync_playwright
    ONLINE_BOT_AVAILABLE = True
except ImportError:
    ONLINE_BOT_AVAILABLE = False


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

    def get_meeting_ended_selector(self):
        """Return text that indicates meeting ended."""
        return "You left the meeting"

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
        if active_label:
            cleaned_name = active_label.split('\\n')[0].strip()
            if "You" in cleaned_name or "you" in cleaned_name:
                cleaned_name = "Meeting Host"
            if len(cleaned_name) > 1 and len(cleaned_name) < 25:
                return cleaned_name.title()
        return None

    def get_meeting_ended_selector(self):
        return "You left the meeting"

    def get_platform_name(self):
        return "Google Meet"


class TeamsStrategy(PlatformStrategy):
    def get_auth_check_url(self):
        return "https://login.microsoftonline.com/"

    def is_logged_in(self, page):
        # Simple check: if email input visible or sign-in text, not logged in
        try:
            if page.locator('input[type="email"]').is_visible():
                return False
            if page.locator('text=Sign in').is_visible():
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
        # Fill name if prompted
        try:
            page.fill('input[name="name"]', bot_name, timeout=2000)
        except:
            try:
                page.fill('input[placeholder="Enter your name"]', bot_name, timeout=2000)
            except:
                pass
        # Click join buttons
        try:
            page.click('button:has-text("Join now")', timeout=3000)
        except:
            try:
                page.click('button:has-text("Continue")', timeout=3000)
            except:
                pass

    def get_active_speaker(self, page):
        active_name = page.evaluate('''() => {
            // Look for active speaker indicator
            let activeIndicator = document.querySelector('[data-tid*="active-speaker"], [data-tid*="speaker"], .active-speaker, [aria-selected="true"]');
            if (activeIndicator) {
                let container = activeIndicator.closest('[data-tid*="participant-"]');
                if (container) {
                    let nameEl = container.querySelector('[data-tid*="name"], .name, .participant-name, [aria-label*="name"]');
                    if (nameEl) return nameEl.innerText.trim();
                }
            }
            // Fallback: live subtitles
            let subtitleEl = document.querySelector('.live-subtitles .subtitleSpeakerName, .subtitle-speaker-name, .caption-text-speaker');
            if (subtitleEl) return subtitleEl.innerText.trim();
            return "";
        }''')
        if active_name and len(active_name) > 1:
            return active_name.title()
        return None

    def get_meeting_ended_selector(self):
        return "You have been removed"

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
        # Click "Join from Your Browser" if present
        try:
            page.click('a:has-text("Join from Your Browser")', timeout=5000)
        except:
            pass
        # Fill name
        try:
            page.fill('input[name="name"]', bot_name, timeout=2000)
        except:
            try:
                page.fill('input[placeholder="Enter your name"]', bot_name, timeout=2000)
            except:
                pass
        # Click Join button
        try:
            page.click('button:has-text("Join")', timeout=3000)
        except:
            pass

    def get_active_speaker(self, page):
        active_name = page.evaluate('''() => {
            let activeVideo = document.querySelector('[aria-selected="true"], .active-speaker, .video-holder.active');
            if (activeVideo) {
                let nameEl = activeVideo.querySelector('.name-text, .participant-name, [aria-label*="name"], .caption-text-speaker');
                if (nameEl) return nameEl.innerText.trim();
            }
            return "";
        }''')
        if active_name and len(active_name) > 1:
            return active_name.title()
        return None

    def get_meeting_ended_selector(self):
        return "You have been removed from the meeting"

    def get_platform_name(self):
        return "Zoom"


def get_strategy(platform):
    strategies = {
        "meet": GoogleMeetStrategy(),
        "teams": TeamsStrategy(),
        "zoom": ZoomStrategy(),
    }
    return strategies.get(platform, GoogleMeetStrategy())


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

models = {
    "english": WhisperModel("base.en", device="cpu", compute_type="float32"),
    "multilingual": WhisperModel("small", device="cpu", compute_type="float32")
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

speaker_embeddings = []
speaker_labels = []
speaker_counter = 1

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

def resolve_transcription_mode(language: str):
    selected = (language or "Auto").strip()
    selected_lower = selected.lower()

    if selected_lower == "english":
        return models["english"], "en", "English"

    language_hint = language_map.get(selected_lower)
    mode_label = selected if selected else "Auto"
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

def process_audio_file(wav_path: str, title: str, language: str, participants: list = None, dom_speaker_log: list = None, platform: str = "meet"):
    """Core translation pipeline separated from recording mechanism."""
    global speaker_embeddings, speaker_labels, speaker_counter
    speaker_embeddings, speaker_labels, speaker_counter = [], [], 1
    
    # Read audio for segmentation processing
    samplerate, audio_data = wavfile.read(wav_path)
    
    # Convert to mono float32 for processing
    if len(audio_data.shape) > 1: audio_data = audio_data.mean(axis=1)
    if audio_data.dtype == np.int16: audio_data = audio_data.astype(np.float32) / 32768.0

    if not np.any(audio_data): return "Silent audio detected.", "No summary available.", None

    try:
        model, language_hint, mode_label = resolve_transcription_mode(language)
        print(f"Transcribing with {mode_label} mode...")
        segments, info = model.transcribe(wav_path, language=language_hint)
        detected_language = getattr(info, "language", None)
        language_for_storage = detected_language or mode_label
        
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + (title.replace(" ", "_") or "Untitled")
        full_text = ""
        
        meeting_db_id = None
        if supabase_client:
            meeting_insert_payload = {
                "title": title or "Untitled Meeting",
                "language": language_for_storage,
                "status": "recording",
                "platform": platform
            }
            try:
                print("[BOT] Syncing meeting to Supabase Database...")
                res = supabase_client.table("meetings").insert(meeting_insert_payload).execute()
                if res.data and len(res.data) > 0:
                    meeting_db_id = res.data[0]['id']
            except Exception as e:
                error_text = str(e).lower()
                if "platform" in error_text and "schema cache" in error_text:
                    try:
                        print("[Supabase Warning] 'platform' column missing. Retrying insert without platform field...")
                        legacy_payload = {
                            "title": meeting_insert_payload["title"],
                            "language": meeting_insert_payload["language"],
                            "status": meeting_insert_payload["status"],
                        }
                        res = supabase_client.table("meetings").insert(legacy_payload).execute()
                        if res.data and len(res.data) > 0:
                            meeting_db_id = res.data[0]['id']
                    except Exception as fallback_error:
                        print(f"[Supabase Error] Could not create meeting (legacy fallback failed): {fallback_error}")
                else:
                    print(f"[Supabase Error] Could not create meeting: {e}")

        print("Processing segments for speaker detection...")
        for seg in segments:
            start_idx = int(seg.start * samplerate)
            end_idx = int(seg.end * samplerate)
            segment_audio = audio_data[start_idx:end_idx].flatten()

            if len(segment_audio) < samplerate // 4: continue

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
                
                # If we mapped a DOM visual indicator within an arbitrary ~5 second sync window
                if min_diff < 5.0 and best_match:
                    speaker = best_match
                else:
                    speaker = "Speaker"

            # -----------------------------------------------------
            # BRANCH B: Local Microphone (Resemblyzer AI Diarization)
            # -----------------------------------------------------
            else:
                try:
                    wav_seg = preprocess_wav(segment_audio, samplerate)
                    embed = encoder.embed_utterance(wav_seg)
                    speaker = speaker_id(embed)
                except:
                    speaker = "Unknown"

            start_ts = datetime.utcfromtimestamp(seg.start).strftime("%H:%M:%S")
            end_ts = datetime.utcfromtimestamp(seg.end).strftime("%H:%M:%S")
            text = seg.text.strip()
            
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
        
        return full_text, summary, output_filename
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        return str(e), "", None

def record_local(minutes: float, title: str, language: str):
    """Workflow 1: Local Microphone Capture"""
    duration = int(minutes * 60)
    print(f"Recording from local microphone for {minutes:.2f} minutes...")
    audio = sd.rec(int(SAMPLE_RATE * duration), samplerate=SAMPLE_RATE, channels=1)
    sd.wait()
    print("Recording complete.")

    wav_path = "temp_local.wav"
    wavfile.write(wav_path, SAMPLE_RATE, (audio * 32767).astype(np.int16))
    
    res = process_audio_file(wav_path, title, language, None, None, platform="local")
    if os.path.exists(wav_path): os.remove(wav_path)
    return res

def join_meeting_and_record(url: str, title: str, language: str, platform: str = "meet"):
    """Workflow 2: Online Bot Capture (Playwright + WASAPI Loopback)"""
    if not ONLINE_BOT_AVAILABLE:
        raise RuntimeError(
            "Online bot dependencies are missing. Install: pip install playwright pyaudiowpatch, then run: python -m playwright install chromium"
        )

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    wav_path = "temp_meeting.wav"
    stop_recording = False
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

        def audio_callback(in_data, frame_count, time_info, status):
            if not stop_recording: wf.writeframes(in_data)
            return (in_data, pyaudio.paContinue)

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

            context = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_path,
                channel="chrome",
                headless=False,
                args=[
                    '--use-fake-ui-for-media-stream',
                    '--disable-blink-features=AutomationControlled',
                    '--profile-directory=Default',
                    '--disable-guest-mode'
                ],
                ignore_default_args=["--enable-automation"],
                permissions=['camera', 'microphone']
            )
            page = context.pages[0]

            # Authentication check (platform-specific)
            print("\n[BOT] Checking authentication status...")
            auth_url = strategy.get_auth_check_url()
            if auth_url:
                page.goto(auth_url)
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

            page.goto(url)

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
                while not stop_recording:
                    try:
                        if input().strip().lower() == 'q':
                            return
                    except EOFError:
                        # Non-interactive runs (like API servers) may not have stdin.
                        return
            threading.Thread(target=check_quit, daemon=True).start()

            dom_speaker_log = []

            # Enable captions (platform-specific)
            try:
                strategy.enable_captions(page)
                page.wait_for_timeout(1000)
            except:
                pass

            # Poll for participants while recording
            while not stop_recording:
                try:
                    speaker_name = strategy.get_active_speaker(page)
                    if speaker_name:
                        rel_timestamp = time.time() - recording_start_time
                        dom_speaker_log.append((rel_timestamp, speaker_name))
                        participants.add(speaker_name)
                except:
                    pass

                # Auto-stop if meeting ended indicator appears
                try:
                    if page.locator(f'text={strategy.get_meeting_ended_selector()}').is_visible(timeout=500):
                        print("[BOT] Meeting ended naturally.")
                        break
                except:
                    pass

                time.sleep(0.5)

            stop_recording = True
            stream.stop_stream()
            stream.close()
            wf.close()
            context.close()

    print("[BOT] Extraction finished.")
    res = process_audio_file(wav_path, title, language, list(participants), dom_speaker_log=dom_speaker_log, platform=platform)
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
        platform = "meet"
        if "teams.microsoft.com" in url:
            platform = "teams"
        elif "zoom.us" in url:
            platform = "zoom"
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
