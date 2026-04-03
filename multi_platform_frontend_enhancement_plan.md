# Implementation Plan: Multi-Platform Meeting Bot & Enhanced UI

## Context

Your project is a **Smart Meeting Notes** system with:
- **Backend (Python)**: `app.py` - Records audio from local mic OR automates browser-based meeting join via Playwright + WASAPI loopback. Currently only supports Google Meet.
- **Frontend (React)**: Dashboard to view meetings stored in Supabase. Currently shows a kanban board of meetings with transcript panel.
- **Database**: Supabase with `meetings` and `transcripts` tables.

The request is:
1. **Enhance frontend UI** - make it look better
2. **Add Microsoft Teams and Zoom support** to the bot (backend)

---

## Part A: Frontend UI Improvements

### Current State Analysis
- **Stack**: React 19, Tailwind CSS, Radix UI components, Tabler icons
- **Layout**: Sidebar navigation + main content area
- **Components**: 
  - DashboardLayout (with AppSidebar)
  - MeetingsBoard (kanban columns)
  - MeetingCard (displays platform, date, host, duration, summary preview)
  - TranscriptPanel (right slide-over panel)
- **Data Source**: Supabase realtime subscriptions
- **Missing**: Ability to **start** a new recording from the UI (currently only CLI)

### Proposed UI Enhancements

#### 1. Add "Start Meeting" Floating Action Button (FAB)
- Add a prominent FAB in the bottom-right corner when viewing the meetings board
- On click, opens a dialog with form fields:
  - Meeting Title (text input)
  - Platform (select: Google Meet, Microsoft Teams, Zoom)
  - Language (select: English, Hindi, Gujarati)
  - Duration (optional, or just a "Start Recording" button)
  - Meeting URL (for online bot mode) OR "Local Microphone" option
- "Start Recording" button triggers backend API (to be created)

#### 2. Improved Meeting Card Design
- Add platform-specific colorful icons/badges (Google Meet blue, Teams purple, Zoom blue)
- Show recording status with live indicator
- Add hover effects and better spacing
- Show participant count if available
- Add quick-action buttons on card: Join (if URL stored), View Transcript, Delete

#### 3. Enhanced Transcript Panel
- Add speaker identification with avatars (initials)
- Show timestamps in a clearer format
- Add copy-to-clipboard button for transcript and summary
- Add download button (export as .txt)
- Better responsive sizing

#### 4. Dashboard Statistics Bar
- Add a top bar showing:
  - Total meetings
  - Total recording hours
  - Number of unique speakers
  - Most used platform

#### 5. Platform Filter Dropdown
- Current platform filter shows icons but need actual filtering logic
- Add checkboxes: All, Google Meet, Microsoft Teams, Zoom
- Filter meetings by platform in real-time

#### 6. Create Backend API for Triggering Recordings
**IMPORTANT**: The current frontend cannot trigger recordings because the backend has no web server. We need to add a **FastAPI server** (already in requirements.txt) that:
- Provides REST endpoints:
  - `POST /api/start-recording` - starts a meeting recording (local or online)
  - `GET /api/meetings` - list meetings (optional, Supabase already used)
  - `POST /api/stop-recording/:id` - stops an active recording
- The frontend will call these endpoints instead of just displaying data
- The existing CLI mode (`python app.py`) can remain for standalone use, but the web server should also work

---

## Part B: Backend - Multi-Platform Support

### Current Google Meet Implementation (Lines 287-457 in app.py)

Key components:
1. **Authentication Check**: Navigates to Google accounts page, checks for email input field
2. **Browser Setup**: Chromium with persistent context (bot_profile), fake UI for media, WASAPI loopback
3. **Join Flow**: Navigate to URL → Ctrl+D/Ctrl+E (disable media) → Fill name → Click "Ask to join" or "Join now"
4. **Speaker Detection**: 
   - Uses DOM mutation log to map active speaker timestamps to names
   - Selectors: `.zs7s8d, .abjB1e` for captions; `.IisKId, .FxcRjc` for volume bars; `[data-allocation-index]`
5. **Captions**: Presses 'c' to enable captions

### Platform Differences to Handle

#### 1. Microsoft Teams
- **URL pattern**: `https://teams.microsoft.com/l/meetup-join/...` or `https://teams.microsoft.com/_#/...`
- **Authentication**: Uses Microsoft Account (MSA) or Azure AD SSO. Similar to Google - check `login.microsoftonline.com`. Need to handle possibly more complex SSO flows.
- **Join Flow**:
  - May need to click "Join now" or "Join as guest"
  - Permissions dialog (camera/mic) appears - need to click "Allow" or "Continue" (browser handles with fake UI)
- **Active Speaker Detection**:
  - Teams highlights active speaker with a blue border on the video tile
  - DOM structure: Each participant in a grid item with `data-tid` attributes
  - Look for `[data-tid="participant-"]` with `role="img"` or aria-labels
  - Active speaker might have `data-tid="active-speaker-indicator"` or class `"active"`/`"speaking"`
  - Alternative: Caption bar at bottom shows speaker name (`.live-subtitles` container with `.subtitle-` classes)
- **Keyboard Shortcuts**: 
  - Toggle mic: Ctrl+Shift+M
  - Toggle camera: Ctrl+Shift+O
- **Captions**: Can be enabled via UI; caption shortcuts: Ctrl+Shift+L (maybe)

#### 2. Zoom
- **URL pattern**: `https://zoom.us/j/...` or `https://us05web.zoom.us/j/...`
- **Authentication**: Usually not required for participant joining; can join as guest with name
- **Join Flow**:
  - Click "Join from Your Browser" if not using client
  - Enter name in prompt
  - Click "Join"
  - May need to click "Continue" on "Zoom is trying to access your microphone" dialog
- **Active Speaker Detection**:
  - Zoom web client shows active speaker with a name label below video
  - DOM: Video container `[class*="video-"]` with associated name display
  - Active participant might have `class="active-speaker"` or `aria-selected="true"`
  - Also: Caption pane (if enabled) shows speaker name
- **Keyboard Shortcuts**:
  - Mute/unmute: Alt+A
  - Video on/off: Alt+V
- **Captions**: Can be toggled with `Alt+C` or via UI

### Implementation Strategy

#### Step 1: Refactor `join_meeting_and_record()` to Platform-Agnostic

Current: Function is hardcoded for Google Meet. We'll:

1. **Extract a `PlatformStrategy` interface** (abstract base class or dict of callables) with methods:
   - `check_auth(page)` → bool
   - `perform_join(page, url, bot_name)` → None
   - `get_active_speaker(page)` → str (speaker name) or None
   - `enable_captions(page)` → None
   - `get_platform_name()` → str

2. **Implement strategies**:
   - `GoogleMeetStrategy`
   - `TeamsStrategy`
   - `ZoomStrategy`

3. **Main loop polling**: Use strategy's `get_active_speaker()` instead of hardcoded DOM eval

4. **Factory function**: `get_strategy(platform)` returns appropriate strategy based on URL or explicit platform param

#### Step 2: Platform-Specific Implementation Details

**Common pattern**:
```python
class PlatformStrategy:
    def check_auth(self, page):
        """Check if we're logged in; if not, prompt user to login manually"""
        raise NotImplementedError
    
    def perform_join(self, page, url, bot_name):
        """Navigate and join the meeting"""
        raise NotImplementedError
    
    def get_active_speaker(self, page):
        """Extract active speaker name from DOM. Return None if not found."""
        raise NotImplementedError
    
    def enable_captions(self, page):
        """Enable captions/subtitles if needed"""
        raise NotImplementedError
    
    def get_platform_name(self):
        return "Generic"
```

**GoogleMeetStrategy** (existing logic, just move/refactor):
- `check_auth`: goto `https://accounts.google.com/`, look for email input
- `perform_join`: goto URL → Ctrl+D, Ctrl+E → fill name → click "Ask to join"/"Join now"
- `get_active_speaker`: eval script returning caption name or volume indicator parent text
- `enable_captions`: press 'c'
- `get_platform_name`: "Google Meet"

**TeamsStrategy**:
- `check_auth`: goto `https://login.microsoftonline.com/` or `https://teams.microsoft.com/` and check for sign-in prompt
- `perform_join`: goto URL → wait → maybe click "Join as guest" or "Continue" → fill name → "Join now"
- `get_active_speaker`: 
  - Try: `document.querySelector('[data-tid="active-speaker-indicator"]')?.closest('[data-tid*="participant-"]')?.querySelector('.name')?.innerText`
  - Fallback: Look for `.live-subtitles .subtitleSpeakerName`
- `enable_captions`: click on captions button in toolbar or press `Ctrl+Shift+L` (verify)
- `get_platform_name`: "Microsoft Teams"

**ZoomStrategy**:
- `check_auth`: Not really needed; can skip or check for login prompt
- `perform_join`: goto URL → click "Join from Your Browser" → fill name → "Join"
- `get_active_speaker`:
  - Look for `[class*="video-container"]` with `aria-selected="true"` and extract name
  - Or: `document.querySelector('.caption-text-speaker')?.innerText` (captions)
- `enable_captions`: click "CC" button in UI or `Alt+C`
- `get_platform_name`: "Zoom"

#### Step 3: Update `join_meeting_and_record()` to Use Strategy Pattern

Pseudo-code:
```python
def join_meeting_and_record(url: str, title: str, language: str, platform: str = "meet"):
    strategy = get_strategy(platform)
    
    # ... (WASAPI setup)
    
    with sync_playwright() as pw:
        context = ...
        page = context.pages[0]
        
        # Auth check and manual login prompt if needed
        if not strategy.check_auth(page):
            print("Please log in manually...")
            input("Press Enter when done...")
        
        strategy.enable_captions(page)
        strategy.perform_join(page, url, "Smart Notes Bot")
        
        # Main recording loop
        while not stop_recording:
            speaker_name = strategy.get_active_speaker(page)
            if speaker_name:
                rel_timestamp = time.time() - recording_start_time
                dom_speaker_log.append((rel_timestamp, speaker_name.title()))
                participants.add(speaker_name.title())
            
            # Auto-stop if meeting ended
            ...
    
    # Process audio to transcript + summary
    ...
```

#### Step 4: Modify Main CLI to Ask for Platform or Auto-Detect

```python
def main():
    print("=== Audio Transcription System ===")
    print("1. Local Microphone Capture")
    print("2. Online Meeting Bot (Google Meet / Teams / Zoom)")
    
    choice = input(...)
    ...
    if choice == "2":
        url = input("Enter meeting URL: ").strip()
        # Determine platform from URL
        platform = "meet"
        if "teams.microsoft.com" in url: platform = "teams"
        elif "zoom.us" in url: platform = "zoom"
        # OR ask user to select
        ...
        transcript, summary, filename = join_meeting_and_record(url, title, language, platform=platform)
```

#### Step 5: Update Supabase Meeting Record with Platform Field

The `meetings` table currently has `platform` hardcoded to `'meet'` in App.jsx's `toCard()` function.

We need:
- **Database**: Add `platform` column to `meetings` table if not present (VARCHAR default 'meet')
- **Backend**: In `join_meeting_and_record()`, when creating meeting record, include `platform`:
  ```python
  supabase_client.table("meetings").insert({
      "title": title,
      "language": language,
      "status": "recording",
      "platform": platform  # NEW
  })
  ```
- **Frontend**: The `toCard()` function in App.jsx should read `m.platform` instead of hardcoding `'meet'`

---

## Part C: Frontend - Start Recording Integration

### 1. Add Backend API with FastAPI

Create a new file `api_server.py` (or extend `app.py` with an option to run as server):

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import threading
import uuid

app = FastAPI()

# In-memory store of active recording sessions (could also use DB)
active_recordings = {}

class StartRecordingRequest(BaseModel):
    title: str
    platform: str  # "meet", "teams", "zoom"
    url: str = None  # Required for online, None for local
    language: str = "English"

@app.post("/api/start-recording")
async def start_recording(req: StartRecordingRequest):
    """Start a meeting recording in a background thread."""
    recording_id = str(uuid.uuid4())
    
    def run_bot():
        try:
            if req.platform == "local":
                result = record_local(req.duration_minutes, req.title, req.language)
            else:
                result = join_meeting_and_record(
                    url=req.url,
                    title=req.title,
                    language=req.language,
                    platform=req.platform
                )
            # Update DB status to completed (already done in process_audio_file)
        except Exception as e:
            print(f"Recording failed: {e}")
    
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    active_recordings[recording_id] = {
        "thread": thread,
        "status": "recording",
        "platform": req.platform,
        "title": req.title
    }
    return {"recording_id": recording_id, "status": "started"}

@app.get("/api/recordings")
async def list_recordings():
    """List active recordings."""
    return [
        {"id": rid, **info}
        for rid, info in active_recordings.items()
    ]

# Optional: run with: uvicorn api_server:app --reload
```

**Deployment**: The backend can run as two processes:
- `python app.py` (CLI mode)
- `uvicorn api_server:app --host 0.0.0.0 --port 8000` (API server)
OR merge them: `python app.py --api-server` starts both.

### 2. Update Frontend to Call API

In `frontend/src/lib/` create `api.js`:
```javascript
export const API_BASE = 'http://localhost:8000';

export async function startRecording(data) {
  const res = await fetch(`${API_BASE}/api/start-recording`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}
```

In `App.jsx` or a new component, add "Start Recording" button that opens dialog and calls API.

### 3. Platform Icons Already Exist

The `MeetingCard` component already has a `PlatformIcon` that supports 'meet', 'zoom', 'slack', 'discord', 'google'. We'll add:
- `'teams'` → Microsoft Teams icon (maybe a `IconBrandMicrosoft` from Tabler)
- Ensure `'zoom'` is correct

---

## Detailed File Change List

### Backend (Python)

1. **app.py**
   - Refactor: Extract `PlatformStrategy` classes (move Google logic to `GoogleMeetStrategy`)
   - Add `TeamsStrategy`, `ZoomStrategy`
   - Add `get_strategy(platform)` factory
   - Modify `join_meeting_and_record()` to accept `platform` parameter and use strategy
   - Auto-detect platform from URL in `main()` or add explicit prompt
   - Save `platform` to Supabase when creating meeting
   - Update imports

2. **api_server.py** (NEW)
   - Create FastAPI app with endpoints for starting recordings
   - Run in separate thread or as standalone

3. **requirements.txt** (already has FastAPI; ensure includes `uvicorn`)

4. **Supabase schema**
   - Ensure `meetings` table has `platform` column (VARCHAR/ TEXT)
   - If missing: Run SQL `ALTER TABLE meetings ADD COLUMN platform TEXT DEFAULT 'meet';`

### Frontend (React)

1. **frontend/src/App.jsx** (or better: create `StartRecordingDialog.jsx`)
   - Add state for dialog open/closed
   - Add FAB button that opens dialog (position: fixed bottom-4 right-4)
   - Create form with fields: title (input), platform (select: meet, teams, zoom), language (select), url (input for online mode, optional for local)
   - On submit: call `startRecording()` API, show success toast, maybe close dialog
   - After API call, the Supabase realtime subscription will automatically show the new meeting in the board

2. **frontend/src/lib/api.js** (NEW)
   - Define `API_BASE` (from env or default)
   - Export `startRecording(req)` function

3. **frontend/src/components/watermelon/meetings-dashboard/components/MeetingCard.jsx**
   - Add Teams icon: `IconBrandMicrosoft`
   - Ensure platform icons are visually distinct
   - (Optional) Add platform badge color to card border

4. **frontend/src/components/watermelon/meetings-dashboard/MeetingsBoard.jsx** (or App.jsx)
   - Add FAB if showing board
   - Add platform filter in SidebarFilters (checkboxes for platform)

5. **frontend/src/components/watermelon/meetings-dashboard/SidebarFilters.jsx**
   - Add filter section for Platform with checkboxes

6. **frontend/src/index.css** or Tailwind config
   - Add custom styles if needed for animations

7. **frontend/src/components/ui/badge.jsx** etc. remain unchanged

---

## Verification / Testing Plan

### Backend Tests

1. **Unit test strategies** (can be manual):
   - Test `GoogleMeetStrategy.get_active_speaker()` works (already works)
   - Test `TeamsStrategy.get_active_speaker()` with a sample Teams meeting page (dev environment)
   - Test `ZoomStrategy.get_active_speaker()` similarly

2. **Integration test**:
   - Start API server: `uvicorn api_server:app --reload`
   - POST to `/api/start-recording` with platform="meet", valid URL
   - Verify meeting appears in Supabase with correct platform
   - Verify transcript and summary generated

3. **Platform detection**:
   - Run with Teams URL, check that `TeamsStrategy` used
   - Run with Zoom URL, check that `ZoomStrategy` used
   - Check that auth prompts appear appropriately

### Frontend Tests

1. Start dev server: `npm run dev`
2. Navigate to meetings page
3. Click "Start Recording" FAB
4. Fill form with:
   - Title: "Test Meeting"
   - Platform: "Microsoft Teams"
   - Language: "English"
   - URL: (a test Teams meeting URL)
5. Submit
6. Frontend should show new meeting in "Recording" column
7. Wait for transcript to appear in transcript panel when clicked
8. Verify platform icon shows Teams logo

### UI Improvements Visual Check

- Confirm FAB is visible and styled nicely (gradient or accent color, shadow, rounded-full)
- Confirm MeetingCard has improved spacing, hover effects
- Confirm TranscriptPanel has copy/download buttons
- Confirm platform filter works across columns

---

## Timeline Estimate

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| **Backend - Refactor** | Extract strategies, implement Teams & Zoom classes | 2-3 hours |
| **Backend - API** | Create FastAPI server, endpoint | 1 hour |
| **Frontend - FAB & Dialog** | Create component, connect to API | 1-2 hours |
| **Frontend - UI Polish** | Improve cards, transcript panel, stats bar | 1-2 hours |
| **Database** | Add platform column, test | 0.5 hour |
| **Testing** | End-to-end test all platforms | 1-2 hours |
| **Total** | | **6-11 hours** |

---

## Risks & Mitigations

- **Teams authentication complexity**: Might require additional login steps (MFA). Mitigation: Prompt user to login manually in browser, similar to current Google approach.
- **Zoom frequent UI changes**: Zoom web client updates may break selectors. Mitigation: Use robust selectors, have multiple fallbacks, keep selectors in one place for easy updates.
- **Teams caption availability**: Captions might require a license or admin setting. Mitigation: Fallback to DOM-based speaker detection without captions.
- **API server concurrency**: Starting multiple recordings simultaneously. Mitigation: Use threading (already simple) or task queue (Celery) - but for MVP, threads OK.
- **Frontend CORS**: React on localhost:5173, FastAPI on localhost:8000 need CORS. Mitigation: Add CORS middleware in FastAPI.
- **Platform detection accuracy**: URL can be tricky (shortened links). Mitigation: Also allow user to explicitly select platform in UI, pass that to API.

---

## Next Steps

1. Confirm plan with user: Do you want to proceed with:
   - ✅ Frontend UI improvements (FAB, better cards, transcript panel)?
   - ✅ Add FastAPI backend server for remote triggering?
   - ✅ Platform selection in UI?
   - ✅ Teams and Zoom support as described?

2. Set up FastAPI CORS and environment config

3. Implement platform strategies one by one (Google refactor first, then Teams, then Zoom)

4. Test each platform with actual meeting URLs (need test meetings for each)

5. Polish frontend UI with better Tailwind classes and components

6. Deploy and run both frontend (npm run dev/build) and backend (uvicorn) together

---

## Notes

- Keep Python code modular so adding new platforms (Discord, Slack Huddles) is easy
- Use `ENV` variable `API_BASE_URL` in frontend to configure backend URL
- Consider storing bot profile in separate folders per platform? Currently uses `bot_profile` persistent context for Google. Teams and Zoom may need separate cookies to stay logged in. Solution: Use platform-specific user data dirs:
  - `bot_profile_google`
  - `bot_profile_teams`
  - `bot_profile_zoom`