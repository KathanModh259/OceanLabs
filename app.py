import os
import sys

# Auto-fix shadowing issue: the local 'resemblyzer' folder breaks the python module import.
if os.path.exists('resemblyzer') and os.path.isdir('resemblyzer') and not os.path.exists('resemblyzer/__init__.py'):
    try:
        os.rename('resemblyzer', 'resemblyzer_model')
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

# Azure & Dotenv
from azure.ai.inference import ChatCompletionsClient
from dotenv import load_dotenv
load_dotenv()
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

# Supabase
try:
    from supabase import create_client, Client
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_ANON_KEY")
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


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
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
    "English": WhisperModel("base.en", device="cpu", compute_type="float32"),
    "Hindi": WhisperModel("small", device="cpu", compute_type="float32"),
    "Gujarati": WhisperModel("small", device="cpu", compute_type="float32")
}
language_map = {"English": None, "Hindi": "hi", "Gujarati": "gu"}

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

def get_summary(text: str, language: str = "English", participants=None) -> str:
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return "Error: GITHUB_TOKEN environment variable not set in .env."

        client = ChatCompletionsClient(endpoint=AZURE_AI_ENDPOINT, credential=AzureKeyCredential(token))

        extra_context = f"\nList of Participants detected: {', '.join(participants)}" if participants else ""
        
        user_msg = f"Summarize the following text:\n{text}{extra_context}"
        if language == "Hindi": user_msg = f"निम्नलिखित हिंदी टेक्स्ट का सारांश हिंदी में लिखें:\n{text}{extra_context}"
        elif language == "Gujarati": user_msg = f"નીચેના ગુજરાતી ટેક્સ્ટનો સારાંશ ગુજરાતીમાં લખો:\n{text}{extra_context}"

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

def process_audio_file(wav_path: str, title: str, language: str, participants: list = None, dom_speaker_log: list = None):
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
        print(f"Transcribing with {language} model...")
        model = models[language]
        segments, _ = model.transcribe(wav_path, language=language_map.get(language))
        
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + (title.replace(" ", "_") or "Untitled")
        full_text = ""
        
        meeting_db_id = None
        if supabase_client:
            try:
                print("[BOT] Syncing meeting to Supabase Database...")
                res = supabase_client.table("meetings").insert({
                    "title": title or "Untitled Meeting",
                    "language": language,
                    "status": "recording"
                }).execute()
                if res.data and len(res.data) > 0:
                    meeting_db_id = res.data[0]['id']
            except Exception as e:
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
            
            if language in ["Hindi", "Gujarati"]:
                text = normalize_text(text, language)
            
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
        summary = get_summary(full_text, language, participants)
        
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
    
    res = process_audio_file(wav_path, title, language)
    if os.path.exists(wav_path): os.remove(wav_path)
    return res

def join_meeting_and_record(url: str, title: str, language: str):
    """Workflow 2: Online Bot Capture (Playwright + WASAPI Loopback)"""
    if not ONLINE_BOT_AVAILABLE:
        print("Missing dependencies. Run: pip install playwright pyaudiowpatch")
        print("Then run: python -m playwright install chromium")
        return "", "", None

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    wav_path = "temp_meeting.wav"
    stop_recording = False
    participants = set()

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
            print(f"Audio device error: {e}. Check pyaudiowpatch installation.")
            return "", "", None

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
        with sync_playwright() as pw:
            user_data_path = os.path.join(os.getcwd(), "bot_profile")

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
            
            print("\n[BOT] Checking authentication status...")
            page.goto("https://accounts.google.com/")
            page.wait_for_timeout(3000)
            
            # The most foolproof check: If the email input box exists, we are NOT logged in!
            if page.locator('input[type="email"]').is_visible():
                print("\n[BOT] ⚠️ You are not logged in! Google's security blocks robots from typing passwords.")
                print("[BOT] 👉 PLEASE LOG IN MANUALLY right now in the Chrome window that just opened.")
                print("[BOT] 👉 YOU ONLY HAVE TO DO THIS ONCE! The cookies will be saved forever.")
                input("\n[BOT] >>> ONCE YOU ARE FULLY LOGGED IN, PRESS ENTER HERE TO CONTINUE <<<")
            else:
                print("\n[BOT] ✅ Profile is already authenticated. Skipping login!")
            stream.start_stream()
            recording_start_time = time.time()
            print("[BOT] Audio recording started (System Volume Loopback active)")

            page.goto(url)
            
            try:
                page.wait_for_timeout(3000)
                # Attempt to disable mic/cam
                page.keyboard.press('Control+d')
                page.keyboard.press('Control+e')
                
                try: page.fill('input[placeholder="Your name"]', "Smart Notes Bot", timeout=2000)
                except: pass

                try: page.click('span:has-text("Ask to join")', timeout=2000)
                except: page.click('span:has-text("Join now")', timeout=2000)
                    
                print("[BOT] Interaction completed. Hanging out in meeting...")
            except Exception as e:
                print(f"[BOT] Automated join buttons not found. You might need to click 'Join' manually in the browser. Error: {e}")

            print("\n>>> TYPE 'q' AND PRESS ENTER HERE AT ANY TIME TO END THE RECORDING <<<\n")

            # Simple Background Input Listener to stop manually
            def check_quit():
                while not stop_recording:
                    if input().strip().lower() == 'q':
                        return
            threading.Thread(target=check_quit, daemon=True).start()

            dom_speaker_log = []
            
            # Turn on Google Meet Captions to expose explicit names
            try:
                page.keyboard.press('c')
                page.wait_for_timeout(1000)
            except: pass
            
            # Poll for participants while recording
            while not stop_recording:
                try:
                    # Target the Active Speaker via Captions or Grid
                    active_label = page.evaluate('''() => {
                        // 1. Look for Caption speaker names (Google Meet typically bolds the active speaker in captions)
                        // Common caption speaker name classes: zs7s8d, abjB1e
                        let captionNames = document.querySelectorAll('.zs7s8d, .abjB1e, div[style*="font-weight: bold"]');
                        if (captionNames.length > 0) {
                            // Extract the most recently rendered caption name
                            let latestCaptionName = captionNames[captionNames.length - 1].innerText;
                            if (latestCaptionName) return latestCaptionName;
                        }
                        
                        // 2. Fallback to active tile classes (the blue circle that surrounds a speaking participant)
                        // KxKqVe, FxcRjc, or generic volume indicators
                        let volumeBars = document.querySelectorAll('.IisKId, .FxcRjc'); // The 3 bouncing bars
                        if (volumeBars.length > 0) {
                            // Traverse up to find the container that holds the name
                            let parent = volumeBars[0].closest('[data-allocation-index]');
                            if (parent) return parent.innerText;
                        }
                        
                        return "";
                    }''')
                    
                    if active_label:
                        cleaned_name = active_label.split('\\n')[0].strip() # Take just the first line (the name)
                        if "You" in cleaned_name or "you" in cleaned_name: cleaned_name = "Meeting Host"
                        if len(cleaned_name) > 1 and len(cleaned_name) < 25:
                            rel_timestamp = time.time() - recording_start_time
                            dom_speaker_log.append((rel_timestamp, cleaned_name.title()))
                            participants.add(cleaned_name.title())
                except:
                    pass
                
                # Auto-stop if 'You left the meeting' screen occurs
                try:
                    if page.locator('text=You left the meeting').is_visible(timeout=500):
                        print("[BOT] Meeting ended naturally.")
                        break
                except: pass
                
                time.sleep(0.5)

            stop_recording = True
            stream.stop_stream()
            stream.close()
            wf.close()
            context.close()

    print("[BOT] Extraction finished.")
    res = process_audio_file(wav_path, title, language, list(participants), dom_speaker_log=dom_speaker_log)
    if os.path.exists(wav_path): os.remove(wav_path)
    return res

def main():
    print("=== Audio Transcription System ===")
    print("1. Local Microphone Capture")
    print("2. Online Meeting Bot (Google Meet via Loopback)")
    
    choice = input("Select mode (1/2): ").strip()
    title = input("Enter conversation title (press Enter for 'Untitled'): ").strip()
    language = input("Select language (English/Hindi/Gujarati) [default: English]: ").strip().capitalize()
    if language not in models: language = "English"

    if choice == "2":
        url = input("Enter Google Meet URL: ").strip()
        transcript, summary, filename = join_meeting_and_record(url, title, language)
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
