import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
from resemblyzer import preprocess_wav, VoiceEncoder
from faster_whisper import WhisperModel
import os
import tempfile
from datetime import datetime
from indicnlp.normalize import indic_normalize
from indicnlp.tokenize import indic_tokenize
import re
import sys
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Load models
model_path = resource_path("resemblyzer/pretrained.pt")
if not os.path.exists(model_path):
    print("\nError: Pretrained model file not found!")
    print(f"Expected path: {model_path}")
    print("\nSteps to fix:")
    print("1. Create a directory named 'resemblyzer' next to this script")
    print("2. Download 'pretrained.pt' from: https://github.com/resemble-ai/Resemblyzer")
    print("3. Place it in the 'resemblyzer' folder")
    sys.exit(1)

encoder = VoiceEncoder(device="cpu")

# Constants
SAMPLE_RATE = 16000
SIMILARITY_THRESHOLD = 0.8

AZURE_AI_ENDPOINT = "https://models.github.ai/inference"
AZURE_AI_MODEL = "openai/gpt-4.1"

models = {
    "English": WhisperModel("base.en", device="cpu", compute_type="float32"),
    "Hindi": WhisperModel("small", device="cpu", compute_type="float32"),
    "Gujarati": WhisperModel("small", device="cpu", compute_type="float32")
}

language_map = {
    "English": None,
    "Hindi": "hi",
    "Gujarati": "gu"
}

hindi_normalizer = indic_normalize.IndicNormalizerFactory().get_normalizer("hi")
gujarati_normalizer = indic_normalize.IndicNormalizerFactory().get_normalizer("gu")
HINDI_CHAR_RANGE = r'[\u0900-\u097F]'
GUJARATI_CHAR_RANGE = r'[\u0A80-\u0AFF]'

# Global speaker state
speaker_embeddings = []
speaker_labels = []
speaker_counter = 1

def is_hindi_text(text: str) -> bool:
    return bool(re.search(HINDI_CHAR_RANGE, text))

def is_gujarati_text(text: str) -> bool:
    return bool(re.search(GUJARATI_CHAR_RANGE, text))

def normalize_hindi_text(text: str) -> str:
    normalized_text = hindi_normalizer.normalize(text)
    hindi_chars = re.findall(HINDI_CHAR_RANGE, normalized_text)
    filtered_text = ''.join(hindi_chars)
    tokens = indic_tokenize.trivial_tokenize(filtered_text)
    return " ".join(tokens)

def normalize_gujarati_text(text: str) -> str:
    normalized_text = gujarati_normalizer.normalize(text)
    gujarati_chars = re.findall(GUJARATI_CHAR_RANGE, normalized_text)
    filtered_text = ''.join(gujarati_chars)
    tokens = indic_tokenize.trivial_tokenize(filtered_text)
    return " ".join(tokens)

def get_summary(text: str, language: str = "English") -> str:
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return "Error: GITHUB_TOKEN environment variable not set."

        client = ChatCompletionsClient(
            endpoint=AZURE_AI_ENDPOINT,
            credential=AzureKeyCredential(token),
        )

        if language == "Hindi":
            user_message_content = f"""निम्नलिखित हिंदी टेक्स्ट का सारांश हिंदी में लिखें:\n{text}"""
        elif language == "Gujarati":
            user_message_content = f"""નીચેના ગુજરાતી ટેક્સ્ટનો સારાંશ ગુજરાતીમાં લખો:\n{text}"""
        else:
            user_message_content = f"""Summarize the following text:\n{text}"""

        messages = [
            SystemMessage('''
You are an expert meeting assistant. Analyze the following meeting transcript and provide a structured summary with:

- Meeting Summary
- Agenda
- Key Points and Decisions
- Speakers and Roles
- Action Items
- Notable Quotes or Insights
- Future Recommendations
- Number of Unique Speakers

Use bullet points or clear headings where appropriate.
'''),
            UserMessage(user_message_content)
        ]

        response = client.complete(
            messages=messages,
            temperature=0.7,
            top_p=1,
            model=AZURE_AI_MODEL
        )

        if response.choices and response.choices[0].message and response.choices[0].message.content:
            return response.choices[0].message.content.strip()
        else:
            return "Error: Could not retrieve summary from Azure AI."
    except Exception as e:
        return f"Error connecting to Azure AI Inference: {str(e)}"

def speaker_id(new_embed):
    global speaker_embeddings, speaker_labels, speaker_counter

    if not speaker_embeddings:
        speaker_embeddings.append(new_embed)
        speaker_labels.append(f"Speaker {speaker_counter}")
        return f"Speaker {speaker_counter}"

    similarities = [np.dot(embed, new_embed) for embed in speaker_embeddings]
    max_sim = max(similarities)

    if max_sim > SIMILARITY_THRESHOLD:
        idx = similarities.index(max_sim)
        return speaker_labels[idx]
    else:
        speaker_counter += 1
        new_label = f"Speaker {speaker_counter}"
        speaker_embeddings.append(new_embed)
        speaker_labels.append(new_label)
        return new_label

def record_and_transcribe(minutes: float, title: str = "", language: str = "English"):
    global speaker_embeddings, speaker_labels, speaker_counter
    speaker_embeddings = []
    speaker_labels = []
    speaker_counter = 1

    duration = int(minutes * 60)
    print(f"Recording for {minutes:.2f} minutes...")
    audio = sd.rec(int(SAMPLE_RATE * duration), samplerate=SAMPLE_RATE, channels=1)
    sd.wait()
    print("Recording complete.")

    wav_path = "temp_chunk.wav"
    write(wav_path, SAMPLE_RATE, (audio * 32767).astype(np.int16))

    if not np.any(audio):
        print("No audio detected.")
        return "Silent audio detected.", "No summary available.", None

    try:
        print(f"Transcribing with {language} model...")
        model = models[language]
        lang_code = language_map.get(language)
        segments, _ = model.transcribe(wav_path, language=lang_code)
        os.remove(wav_path)

        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + (title.replace(" ", "_") or "Untitled")
        full_text = ""

        print("Processing segments for speaker detection...")
        for seg in segments:
            start = int(seg.start * SAMPLE_RATE)
            end = int(seg.end * SAMPLE_RATE)
            segment_audio = audio[start:end].flatten()

            if len(segment_audio) < SAMPLE_RATE // 4:
                continue

            try:
                wav_seg = preprocess_wav(segment_audio, SAMPLE_RATE)
                embed = encoder.embed_utterance(wav_seg)
                speaker = speaker_id(embed)
            except:
                speaker = "Unknown"

            start_ts = datetime.utcfromtimestamp(seg.start).strftime("%H:%M:%S")
            end_ts = datetime.utcfromtimestamp(seg.end).strftime("%H:%M:%S")
            text = seg.text.strip()
            if language == "Hindi" and is_hindi_text(text):
                text = normalize_hindi_text(text)
            elif language == "Gujarati" and is_gujarati_text(text):
                text = normalize_gujarati_text(text)
            full_text += f"[{start_ts} - {end_ts}] {speaker}: {text}\n"

        print("Generating summary...")
        summary = get_summary(full_text, language)

        output_filename = f"{filename}.txt"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(f"=== {filename} ===\n\n")
            f.write("=== TRANSCRIPT ===\n\n")
            f.write(full_text)
            f.write("\n\n=== SUMMARY ===\n\n")
            f.write(summary)

        print(f"Transcript saved to: {output_filename}")
        return full_text, summary, output_filename

    except Exception as e:
        print(f"Error during transcription: {str(e)}")
        return f"Error during transcription: {str(e)}", "Error getting summary", None

def main():
    print("=== Audio Transcription System ===")
    title = input("Enter conversation title (press Enter for 'Untitled'): ").strip()
    while True:
        try:
            minutes = float(input("Enter recording duration in minutes (minimum 0.1): "))
            if minutes >= 0.1:
                break
            print("Too short.")
        except ValueError:
            print("Invalid input.")

    language = input("Select language (English/Hindi/Gujarati) [default: English]: ").strip().capitalize()
    if language not in models:
        language = "English"

    transcript, summary, filename = record_and_transcribe(minutes, title, language)
    print("\n=== Transcription ===")
    print(transcript)
    print("\n=== Summary ===")
    print(summary)

if __name__ == "__main__":
    main()
