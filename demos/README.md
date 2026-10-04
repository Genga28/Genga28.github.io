# Demos

Five runnable applications. Run them locally, screen-record them, drop the clips into
`assets/video/`, and point the portfolio at them from the editor's **Demo videos** tab.

Recording locally beats hosting these: no cloud bill, no cold starts, no webcam permissions
prompt for the viewer, and a 40-second clip shows the thing working better than a live app
that a recruiter would have to figure out.

| # | Demo | Video id | Shows |
|---|------|----------|-------|
| 1 | Desktop RPA: medical bill to Excel | `rpa` | PyAutoGUI scroll-and-find, colour anchoring, PDF OCR, typing into Excel |
| 2 | Web automation: drug reference table | `webauto` | Selenium, structured scraping, browser-driven PDF downloads, 3-sheet Excel |
| 3 | Voice agent with avatar | `voice` | ASR, TTS, animated avatar, optional Claude brain |
| 4 | Real-time proctoring | `proctoring` | MediaPipe face mesh, iris gaze direction and dwell timing, signal fusion |
| 5 | Layout-preserving OCR studio | `ocr` | Tesseract, column anchoring, table and figure detection |

## Setup

Python 3.10 is already on this machine. From the repo root:

```powershell
cd "C:\ZZZ Genga\LinkedIn\Portfolio\Genga28.github.io\demos"
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks the activate script:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### Two optional external installs

Neither blocks a demo from running; each one improves a demo if present.

- **Tesseract OCR** for demo 1's text extraction.
  [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki), default path
  `C:\Program Files\Tesseract-OCR\tesseract.exe`. Without it, demo 1 falls back to the
  sidecar JSON that ships with the generated bill and says so in the log.
- **Google Chrome** for demo 2. Selenium 4.6+ downloads the matching driver itself, so
  there is no chromedriver step.

## Running them

Demos 1, 2 and 4 open a window and run to completion. Demos 3 and 5 are
servers: start them, then open the URL.

```powershell
python 01_rpa_desktop/rpa_bill_to_excel.py
python 02_web_automation/drug_table.py
python 04_proctoring/proctor.py
python 03_voice_agent/server.py            # then open http://127.0.0.1:8080

cd 05_ocr_layout
python -m uvicorn app:app --port 8005      # then open http://127.0.0.1:8005
```

Each folder has its own README with flags and what to expect on screen.

## Recording

Windows has a built-in recorder: **Win+Alt+R** starts and stops it (Xbox Game Bar), and
clips land in `Videos\Captures`. For a region capture or a webcam inset, OBS is better.

Guidelines that make these read well on the portfolio:

- **30 to 60 seconds.** Long enough to show the thing working, short enough that nobody
  scrubs. Start recording after the window is already open.
- **1280x720.** The portfolio player is 16:9, and larger just costs bandwidth.
- **Keep it under 30 MB.** GitHub rejects files over 100 MB, and a recruiter on mobile data
  will not wait. `ffmpeg -i in.mp4 -vcodec libx264 -crf 28 -vf scale=1280:-2 out.mp4`
  usually lands a minute of screen capture around 8 MB.
- **No audio needed** except for demo 3, where the whole point is the conversation.

Then:

```powershell
copy recording.mp4 ..\assets\video\rpa.mp4
```

Open the site, press **Ctrl+Shift+E**, unlock, go to **Demo videos**, and set
`rpa` to `assets/video/rpa.mp4`. Save draft, download `content.json`, commit, push.

For clips over ~30 MB, upload to YouTube as unlisted and paste the **embed** URL
(`https://www.youtube.com/embed/VIDEO_ID`) instead of a path. The player handles both.

## A note on what these are

These are demonstration builds written to be recorded, not production systems. The
proctoring demo uses the same weighted-blend-plus-exponential-boost fusion shape described
on the portfolio, but its weights and thresholds are illustrative, and nothing here carries
over from any employer's codebase.
