# Smart Meeting Notes - Hackathon Documentation

---

## 1. PROJECT OVERVIEW

**Smart Meeting Notes** is an AI-powered system that captures live audio discussions, performs real-time speech-to-text transcription with automatic speaker identification, and generates structured meeting summaries with actionable insights using LLM intelligence.

**Tagline:** _"Never miss a word. Never miss an action."_

**Problem Statement:**  
Meetings consume 15% of an organization's time, yet 73% of professionals do other work during meetings, and most action items are forgotten within 24 hours. Manual note-taking is unreliable, biased, and excludes participants from active engagement.

**Solution:**  
An intelligent, multilingual meeting assistant that automatically records, transcribes with speaker attribution, and generates structured summaries — turning every conversation into accountable, actionable documentation.

---

## 2. FUNCTIONAL REQUIREMENTS (FR)

### FR-01: Audio Capture & Recording
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01.1 | System shall capture live audio via microphone at 16kHz sample rate | P0 - Must |
| FR-01.2 | System shall support configurable recording duration (minimum 0.1 minutes) | P0 - Must |
| FR-01.3 | System shall save raw audio as WAV format temporarily for processing | P0 - Must |
| FR-01.4 | System shall detect silent/empty audio and handle gracefully | P1 - Should |
| FR-01.5 | System shall support multiple audio input devices | P2 - Could |

### FR-02: Speech-to-Text Transcription
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-02.1 | System shall transcribe audio to text using Whisper ASR models | P0 - Must |
| FR-02.2 | System shall support **English** transcription (base.en model) | P0 - Must |
| FR-02.3 | System shall support **Hindi** transcription (small model with language hint) | P0 - Must |
| FR-02.4 | System shall support **Tagalog** transcription (small model with language hint) | P1 - Should |
| FR-02.5 | System shall produce timestamped segments with start/end times (HH:MM:SS) | P0 - Must |
| FR-02.6 | System shall normalize Hindi text (Unicode normalization + Indic tokenization) | P1 - Should |
| FR-02.7 | System shall filter and validate Hindi characters using Unicode range [\u0900-\u097F] | P1 - Should |

### FR-03: Speaker Diarization (Who Spoke When)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-03.1 | System shall generate voice embeddings for each speech segment using Resemblyzer | P0 - Must |
| FR-03.2 | System shall identify and label unique speakers (Speaker 1, Speaker 2, ...) | P0 - Must |
| FR-03.3 | System shall compare voice embeddings using cosine similarity (dot product) | P0 - Must |
| FR-03.4 | System shall use a configurable similarity threshold (default: 0.80) for speaker matching | P0 - Must |
| FR-03.5 | System shall assign new speaker label when similarity falls below threshold | P0 - Must |
| FR-03.6 | System shall skip segments shorter than 0.25 seconds to avoid noise | P1 - Should |

### FR-04: AI-Powered Meeting Summarization
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-04.1 | System shall send full transcript to LLM (GPT-4.1 via Azure AI Inference) | P0 - Must |
| FR-04.2 | System shall generate structured summary containing: | P0 - Must |
|    | - Meeting Summary | |
|    | - Agenda | |
|    | - Key Points and Decisions | |
|    | - Speakers and Roles | |
|    | - Action Items | |
|    | - Notable Quotes or Insights | |
|    | - Future Recommendations | |
|    | - Number of Unique Speakers | |
| FR-04.3 | System shall generate summary in the **same language** as the transcript | P0 - Must |
| FR-04.4 | System shall use appropriate system prompts for each supported language | P1 - Should |

### FR-05: Output & Export
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-05.1 | System shall save transcript + summary to a timestamped .txt file | P0 - Must |
| FR-05.2 | File naming convention: `YYYYMMDD_HHMMSS_Title.txt` | P0 - Must |
| FR-05.3 | System shall display transcript and summary in console/UI | P0 - Must |
| FR-05.4 | Output file shall contain clearly separated TRANSCRIPT and SUMMARY sections | P0 - Must |

### FR-06: User Interaction
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-06.1 | System shall allow user to set a meeting/conversation title | P1 - Should |
| FR-06.2 | System shall allow user to select transcription language | P0 - Must |
| FR-06.3 | System shall default to English when invalid language is selected | P1 - Should |

---

## 3. NON-FUNCTIONAL REQUIREMENTS (NFR)

### NFR-01: Performance
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01.1 | Transcription processing time shall be ≤ 2x the audio duration | < 2x real-time |
| NFR-01.2 | Speaker embedding computation shall complete within 500ms per segment | < 500ms |
| NFR-01.3 | LLM summary generation shall complete within 30 seconds | < 30s |
| NFR-01.4 | System shall handle meetings up to 60 minutes in length | 60 min max |
| NFR-01.5 | System shall support up to 10 unique speakers per session | 10 speakers |

### NFR-02: Accuracy
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-02.1 | English transcription Word Error Rate (WER) | < 15% |
| NFR-02.2 | Hindi transcription accuracy for Devanagari script | > 80% |
| NFR-02.3 | Speaker identification accuracy (same speaker re-identification) | > 85% |
| NFR-02.4 | Summary shall capture all action items mentioned in transcript | > 90% recall |

### NFR-03: Reliability & Error Handling
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-03.1 | System shall gracefully handle missing pretrained models | Graceful exit with instructions |
| NFR-03.2 | System shall handle Azure AI API failures with error messages | No crashes |
| NFR-03.3 | System shall handle empty/silent audio without crashing | Graceful fallback |
| NFR-03.4 | System shall handle unknown speaker segments as "Unknown" | Labeled fallback |

### NFR-04: Scalability
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-04.1 | Architecture shall support adding new languages without code refactor | Plugin-style config |
| NFR-04.2 | System shall support swapping LLM provider (Azure → OpenAI → local) | Configurable endpoint |
| NFR-04.3 | System shall support both CPU and GPU inference | Device parameter |

### NFR-05: Security
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-05.1 | API keys shall be stored in environment variables, not hardcoded | Env var based |
| NFR-05.2 | Temporary audio files shall be deleted after processing | Auto-cleanup |
| NFR-05.3 | Meeting data shall not be stored on third-party servers beyond API calls | Data privacy |

### NFR-06: Usability
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-06.1 | System shall provide clear console progress indicators | Print statements |
| NFR-06.2 | Output files shall be human-readable with clear formatting | Structured .txt |
| NFR-06.3 | System shall run as a single executable (PyInstaller support) | .exe packaging |

### NFR-07: Compatibility
| ID | Requirement | Target |
|----|-------------|--------|
| NFR-07.1 | System shall run on Windows 10/11 | Tested |
| NFR-07.2 | System shall run on Python 3.9+ | 3.9+ |
| NFR-07.3 | System shall work with standard USB/built-in microphones | Standard audio devices |

---

## 4. PROJECT ARCHITECTURE

### 4.1 High-Level Architecture Diagram (Text)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SMART MEETING NOTES SYSTEM                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │          │    │              │    │    PROCESSING ENGINE      │  │
│  │  AUDIO   │───▶│  WAV BUFFER  │───▶│                          │  │
│  │  INPUT   │    │  (16kHz,     │    │  ┌────────────────────┐  │  │
│  │  (Mic)   │    │   Mono)      │    │  │  Faster Whisper    │  │  │
│  │          │    │              │    │  │  ASR Engine         │  │  │
│  └──────────┘    └──────────────┘    │  │  (Multi-language)   │  │  │
│                                      │  └────────┬───────────┘  │  │
│                                      │           │              │  │
│                                      │  ┌────────▼───────────┐  │  │
│                                      │  │  Resemblyzer       │  │  │
│                                      │  │  Speaker Diarizer  │  │  │
│                                      │  │  (Voice Embeddings)│  │  │
│                                      │  └────────┬───────────┘  │  │
│                                      │           │              │  │
│                                      │  ┌────────▼───────────┐  │  │
│                                      │  │  Indic NLP         │  │  │
│                                      │  │  (Hindi Normalize) │  │  │
│                                      │  └────────┬───────────┘  │  │
│                                      └───────────┼──────────────┘  │
│                                                  │                 │
│                                      ┌───────────▼──────────────┐  │
│                                      │   TIMESTAMPED TRANSCRIPT │  │
│                                      │   [HH:MM:SS] Speaker N: │  │
│                                      │   "transcribed text..."  │  │
│                                      └───────────┬──────────────┘  │
│                                                  │                 │
│                                      ┌───────────▼──────────────┐  │
│                                      │   AZURE AI / GPT-4.1     │  │
│                                      │   LLM Summarization      │  │
│                                      │   (Structured Prompt)    │  │
│                                      └───────────┬──────────────┘  │
│                                                  │                 │
│                                      ┌───────────▼──────────────┐  │
│                                      │   OUTPUT MODULE          │  │
│                                      │   ┌──────┐ ┌──────────┐ │  │
│                                      │   │.TXT  │ │ Console  │ │  │
│                                      │   │File  │ │ Display  │ │  │
│                                      │   └──────┘ └──────────┘ │  │
│                                      └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow Diagram

```
┌─────────┐     ┌──────────┐     ┌───────────┐     ┌──────────────┐
│  User   │────▶│  Config  │────▶│  Audio    │────▶│  Segment     │
│  Input  │     │  (Lang,  │     │  Record   │     │  Extraction  │
│         │     │  Title,  │     │  (16kHz)  │     │  (Whisper)   │
│         │     │  Duration)│     │           │     │              │
└─────────┘     └──────────┘     └───────────┘     └──────┬───────┘
                                                          │
    ┌─────────────────────────────────────────────────────┘
    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│  Per-Segment │────▶│  Speaker     │────▶│  Transcript Assembly │
│  Voice       │     │  Matching    │     │  [Time] Speaker: Text│
│  Embedding   │     │  (Cosine     │     │                      │
│  (Resemblyzer)│    │  Similarity) │     │                      │
└──────────────┘     └──────────────┘     └──────────┬───────────┘
                                                     │
    ┌────────────────────────────────────────────────┘
    ▼
┌──────────────────┐     ┌───────────────────┐     ┌──────────────┐
│  LLM API Call    │────▶│  Structured       │────▶│  File Export  │
│  (Azure GPT-4.1) │     │  Summary          │     │  + Display   │
│  System Prompt   │     │  Generation       │     │              │
└──────────────────┘     └───────────────────┘     └──────────────┘
```

### 4.3 Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  main() → CLI Interface / Gradio Web UI                   │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    BUSINESS LOGIC LAYER                          │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ record_and_     │  │ speaker_id() │  │ get_summary()    │  │
│  │ transcribe()    │  │              │  │                  │  │
│  │                 │  │ Voice Match  │  │ LLM Integration  │  │
│  │ Orchestrator    │  │ Engine       │  │ Engine           │  │
│  └─────────────────┘  └──────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    AI/ML MODEL LAYER                             │
│  ┌───────────┐  ┌───────────────┐  ┌────────────────────────┐  │
│  │ Faster    │  │ Resemblyzer   │  │ Azure AI Inference     │  │
│  │ Whisper   │  │ VoiceEncoder  │  │ (GPT-4.1)             │  │
│  │ (STT)     │  │ (Diarization) │  │ (Summarization)       │  │
│  └───────────┘  └───────────────┘  └────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    DATA/IO LAYER                                 │
│  ┌───────────┐  ┌───────────────┐  ┌────────────────────────┐  │
│  │ SoundDev  │  │ SciPy WAV    │  │ File System (Output)   │  │
│  │ (Audio In)│  │ (Audio Write)│  │ (.txt exports)         │  │
│  └───────────┘  └───────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 Technology Stack

```
┌──────────────────────────────────────────────────────────┐
│                  TECHNOLOGY STACK                          │
├────────────────────┬─────────────────────────────────────┤
│ Layer              │ Technology                            │
├────────────────────┼─────────────────────────────────────┤
│ Language           │ Python 3.9+                          │
│ Audio Capture      │ SoundDevice + SciPy                  │
│ Speech-to-Text     │ Faster Whisper (CTranslate2)         │
│ Speaker ID         │ Resemblyzer (d-vector embeddings)    │
│ Hindi NLP          │ Indic NLP Library                    │
│ LLM Summarization  │ Azure AI Inference (GPT-4.1)        │
│ Packaging          │ PyInstaller (.exe)                   │
│ Web UI (optional)  │ Gradio                               │
│ Compute            │ CPU (float32) / GPU (float16)        │
└────────────────────┴─────────────────────────────────────┘
```

---

## 5. SYSTEM FLOW (Step-by-Step)

```
START
  │
  ▼
[1] User launches app
  │
  ▼
[2] User enters: Title, Duration, Language
  │
  ▼
[3] Audio recording begins (sounddevice @ 16kHz mono)
  │
  ▼
[4] Recording completes → saved as temp WAV
  │
  ▼
[5] Whisper model loaded for selected language
  │
  ▼
[6] Audio transcribed into timestamped segments
  │
  ▼
[7] FOR EACH segment:
  │   ├── Extract audio slice
  │   ├── Generate voice embedding (Resemblyzer)
  │   ├── Compare with known speakers (cosine similarity)
  │   ├── If similarity > 0.80 → assign existing speaker
  │   └── If similarity ≤ 0.80 → create new speaker
  │
  ▼
[8] Assemble full transcript:
  │   "[HH:MM:SS - HH:MM:SS] Speaker N: text..."
  │
  ▼
[9] Send transcript to Azure AI GPT-4.1 with structured prompt
  │
  ▼
[10] Receive structured summary:
  │   • Meeting Summary
  │   • Agenda
  │   • Key Points & Decisions
  │   • Action Items
  │   • Recommendations
  │
  ▼
[11] Save transcript + summary to timestamped .txt file
  │
  ▼
[12] Display results to user
  │
  ▼
END
```

---

## 6. HACKATHON POSTER CONTENT

### Title Block
```
╔══════════════════════════════════════════════════════════════╗
║              🎙️ SMART MEETING NOTES                        ║
║   AI-Powered Multilingual Meeting Transcription & Insights  ║
║                                                              ║
║   "Never miss a word. Never miss an action."                 ║
╚══════════════════════════════════════════════════════════════╝
```

### Poster Layout (Sections)

#### SECTION 1: THE PROBLEM
- 73% of professionals multitask during meetings
- $37 billion lost annually to unproductive meetings  
- 63% of meetings have NO agenda documented
- Action items forgotten within 24 hours
- Manual notes are biased, incomplete, and non-shareable

#### SECTION 2: OUR SOLUTION
Smart Meeting Notes — an AI system that:
- **Records** live audio from any microphone
- **Transcribes** speech in English, Hindi & Tagalog
- **Identifies** who said what (speaker diarization)
- **Summarizes** into structured, actionable notes
- **Exports** timestamped, speaker-labeled documents

#### SECTION 3: KEY FEATURES
| Feature | Description |
|---------|-------------|
| 🎤 Live Audio Capture | Records directly from microphone at 16kHz |
| 🗣️ Speaker Diarization | Identifies unique speakers using voice embeddings |
| 🌐 Multilingual STT | Supports English, Hindi, Tagalog (extensible) |
| 🤖 AI Summarization | GPT-4.1 generates structured meeting summaries |
| 📋 Action Item Extraction | Automatically identifies tasks and owners |
| 📁 Auto-Export | Saves timestamped transcript + summary files |

#### SECTION 4: ARCHITECTURE (Mini Diagram)
```
  MIC → [Audio Capture] → [Whisper STT] → [Speaker ID] → [LLM Summary] → OUTPUT
              16kHz          Multi-lang     Resemblyzer      GPT-4.1        .txt
```

#### SECTION 5: TECH STACK (Visual)
```
  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐
  │  SoundDevice │  │Faster Whisper│  │ Resemblyzer  │  │Azure AI  │
  │  (Audio)     │  │(ASR/STT)     │  │(Speaker ID)  │  │(GPT-4.1) │
  └─────────────┘  └──────────────┘  └──────────────┘  └──────────┘
        │                 │                  │                │
        └─────────────────┴──────────────────┴────────────────┘
                              Python 3.9+
```

#### SECTION 6: SAMPLE OUTPUT
```
=== Meeting Transcript ===

[00:00:03 - 00:00:15] Speaker 1: Let's discuss the Q3 roadmap...
[00:00:16 - 00:00:28] Speaker 2: I think we should prioritize...
[00:00:29 - 00:00:45] Speaker 1: Agreed. Let's assign tasks...

=== AI Summary ===

📌 Meeting Summary: Q3 planning discussion with 2 participants
📋 Agenda: Roadmap prioritization
✅ Action Items:
  - Speaker 1: Finalize Q3 roadmap by Friday
  - Speaker 2: Prepare resource allocation report
💡 Key Decision: Mobile-first approach for Q3
```

#### SECTION 7: COMPETITIVE ADVANTAGES
| Feature | Our System | Otter.ai | Fireflies | Zoom AI |
|---------|-----------|----------|-----------|---------|
| Offline STT | ✅ | ❌ | ❌ | ❌ |
| Speaker ID | ✅ | ✅ | ✅ | ⚠️ |
| Hindi Support | ✅ | ❌ | ❌ | ❌ |
| Custom Summary Prompt | ✅ | ❌ | ⚠️ | ❌ |
| Self-Hosted/Private | ✅ | ❌ | ❌ | ❌ |
| Free/Open Source | ✅ | ❌ | ❌ | ❌ |
| Action Item Extraction | ✅ | ✅ | ✅ | ⚠️ |

#### SECTION 8: FUTURE SCOPE
- 🔴 Real-time streaming transcription (live mode)
- 🔴 Web-based dashboard with Gradio/Streamlit
- 🔴 Email/Slack integration for auto-sharing summaries
- 🔴 Calendar integration for automatic meeting capture
- 🔴 Sentiment analysis per speaker
- 🔴 Support for 20+ languages via Whisper large-v3
- 🔴 Local LLM support (Llama 3, Mistral) for full offline mode
- 🔴 Meeting analytics dashboard (talk-time ratios, interruption count)

---

## 7. UNIQUE SELLING POINTS (USPs) FOR JUDGES

1. **Privacy-First Design**: STT runs 100% locally (Faster Whisper on CPU/GPU) — no audio leaves the device for transcription
2. **Multilingual by Default**: Built-in support for 3 languages with trivial extensibility to 90+ via Whisper
3. **Speaker Attribution**: Not just "what was said" but "who said it" using voice biometric embeddings
4. **Structured Intelligence**: LLM doesn't just summarize — it extracts agenda, action items, recommendations, and speaker roles
5. **Zero Infrastructure**: Runs as a single Python script or packaged `.exe` — no servers, no setup
6. **Open & Extensible**: Easy to swap models (Whisper → Conformer), LLM providers (Azure → OpenAI → local), or add new languages

---

## 8. DEMO SCRIPT (2-3 min Hackathon Demo)

### Minute 1: Problem + Solution (30s)
> "Every day, millions of meetings happen with zero documentation. Our system solves this by automatically recording, transcribing, and generating actionable meeting summaries."

### Minute 2: Live Demo (90s)
1. Launch the app
2. Set title: "Hackathon Demo Meeting"
3. Set duration: 0.5 minutes
4. Select language: English
5. Have 2 team members speak alternately
6. Show real-time processing
7. Display the generated transcript with speaker labels
8. Show the AI-generated structured summary

### Minute 3: Differentiators (30s)
> "Unlike Otter.ai or Fireflies, our system runs STT completely offline for privacy, supports Hindi and Tagalog natively, and generates structured summaries with action items — all from a single executable."

---

## 9. RISK MITIGATION

| Risk | Mitigation |
|------|-----------|
| API Key exposure | Move to environment variables (os.getenv) |
| Azure API rate limit | Implement retry with exponential backoff |
| Whisper model download slow | Pre-download and bundle models |
| Microphone permission denied | Clear error message + troubleshooting guide |
| Similar speakers misidentified | Allow manual speaker label correction |
| Long meetings (60min+) | Chunk processing with sliding window |

---

## 10. METRICS FOR JUDGING

| Metric | How We Measure |
|--------|---------------|
| Innovation | Offline multilingual STT + speaker diarization + LLM summarization in one system |
| Technical Complexity | 4 AI models working in pipeline (Whisper + Resemblyzer + Indic NLP + GPT-4.1) |
| Completeness | End-to-end working system: input → process → output |
| Practicality | Solves real $37B/year problem with zero infrastructure cost |
| Scalability | Modular architecture supports new languages, models, and output formats |

---

*Generated for Hackathon Submission — Smart Meeting Notes*
