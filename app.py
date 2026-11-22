#!/usr/bin/env python3
"""
DTU Course Registration - Control Dashboard
Run with: python app.py  (or python3 app.py)
Opens http://localhost:8765
"""

import http.server
import json
import os
import re
import signal
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser

PORT = 8765
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
CONFIG_FILE = os.path.join(BASE_DIR, "config.py")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")
IS_WINDOWS = sys.platform.startswith("win")

bot_process = None
log_lines = []
log_lock = threading.Lock()


def append_log(text: str):
    with log_lock:
        log_lines.append(text)
        if len(log_lines) > 500:
            log_lines.pop(0)


def get_venv_python() -> str:
    """Return the venv Python executable path cross-platform."""
    if IS_WINDOWS:
        p = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
    else:
        p = os.path.join(BASE_DIR, "venv", "bin", "python3")
    return p if os.path.exists(p) else sys.executable


def read_current_config() -> dict:
    roll, pwd = "", ""
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ROLL_NUMBER="):
                        roll = line.split("=", 1)[1].strip()
                    elif line.startswith("PASSWORD="):
                        pwd = line.split("=", 1)[1].strip()
        except Exception:
            pass

    courses = []
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                content = f.read()
            match = re.search(r"COURSES_TO_ADD\s*=\s*(\[.*?\])", content, re.DOTALL)
            if match:
                raw = match.group(1)
                norm = re.sub(r"\bNone\b", "null", raw)
                norm = re.sub(r"'", '"', norm)
                norm = re.sub(r",\s*\]", "]", norm)
                courses = json.loads(norm)
        except Exception:
            pass

    if not courses:
        courses = [
            {"code": "HU306", "slot": "E1"},
            {"code": "HU328", "slot": "E2"},
            {"code": "HU426", "slot": "E4"},
        ]

    return {"roll": roll, "password": pwd, "courses": courses}


def save_config(roll: str, pwd: str, courses: list):
    roll = (roll or "").strip()
    pwd = (pwd or "").strip()

    if roll or pwd:
        try:
            with open(ENV_FILE, "w") as f:
                f.write(f"ROLL_NUMBER={roll}\n")
                f.write(f"PASSWORD={pwd}\n")
        except Exception:
            pass

    if not isinstance(courses, list) or not courses:
        return

    courses_repr = "COURSES_TO_ADD = [\n"
    for c in courses:
        code = str(c.get("code", "")).strip()
        slot = c.get("slot")
        slot_val = f'"{str(slot).strip()}"' if slot else "None"
        courses_repr += f'    {{"code": "{code}", "slot": {slot_val}}},\n'
    courses_repr += "]"

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                content = f.read()
            new_content = re.sub(
                r"COURSES_TO_ADD\s*=\s*\[.*?\]",
                courses_repr,
                content,
                flags=re.DOTALL,
            )
            with open(CONFIG_FILE, "w") as f:
                f.write(new_content)
        except Exception:
            pass


def read_status_safe() -> dict:
    """Read status.json safely, handling partial writes."""
    if not os.path.exists(STATUS_FILE):
        return {}
    for _ in range(3):
        try:
            with open(STATUS_FILE, "r") as sf:
                return json.load(sf)
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return {}


def stream_process_output(proc):
    global bot_process
    try:
        for line in iter(proc.stdout.readline, ""):
            if line:
                append_log(line.rstrip())
                print(line.rstrip(), flush=True)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait()
        with log_lock:
            bot_process = None


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif self.path == "/api/config":
            self._json(read_current_config())

        elif self.path.startswith("/api/status"):
            is_running = bot_process is not None and bot_process.poll() is None
            with log_lock:
                recent_logs = list(log_lines[-300:])
            status_info = read_status_safe()
            self._json({"running": is_running, "logs": recent_logs, "status": status_info})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global bot_process
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            payload = json.loads(body)
        except Exception:
            payload = {}

        if self.path == "/api/start":
            roll = payload.get("roll", "")
            pwd = payload.get("password", "")
            courses = payload.get("courses", [])

            if not roll or not pwd:
                self._json({"ok": False, "msg": "Roll number and password are required."})
                return

            if not courses:
                self._json({"ok": False, "msg": "Add at least one course first."})
                return

            save_config(roll, pwd, courses)

            if bot_process is not None and bot_process.poll() is None:
                self._json({"ok": False, "msg": "Automation is already running!"})
                return

            with log_lock:
                log_lines.clear()

            # Remove stale status file
            try:
                if os.path.exists(STATUS_FILE):
                    os.remove(STATUS_FILE)
            except Exception:
                pass

            append_log(f"[{time.strftime('%H:%M:%S')}] 🚀 Starting for {roll}…")

            python_bin = get_venv_python()
            bot_script = os.path.join(BASE_DIR, "bot.py")

            try:
                bot_process = subprocess.Popen(
                    [python_bin, "-u", bot_script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=BASE_DIR,
                    bufsize=1,
                )
                t = threading.Thread(
                    target=stream_process_output, args=(bot_process,), daemon=True
                )
                t.start()
                self._json({"ok": True, "msg": "Bot started"})
            except Exception as e:
                self._json({"ok": False, "msg": f"Failed to start bot: {e}"})

        elif self.path == "/api/stop":
            stopped = False
            if bot_process is not None and bot_process.poll() is None:
                append_log(f"[{time.strftime('%H:%M:%S')}] 🛑 Stopping automation…")
                try:
                    bot_process.send_signal(signal.SIGINT)
                    stopped = True
                except Exception:
                    try:
                        bot_process.terminate()
                        stopped = True
                    except Exception:
                        pass
            # Always report ok so the UI re-enables Start
            self._json({"ok": True, "msg": "Stop signal sent" if stopped else "Bot was not running"})

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data: dict):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


# ─────────────────────────────────────────────────────────────────────────────
# HTML UI  (r-string so \n in JS strings are kept as-is)
# ─────────────────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DTU Course Bot</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    :root {
      --bg:            #05080f;
      --surface:       #0d1424;
      --surface2:      #111827;
      --border:        #1f2d45;
      --border2:       #263348;
      --text:          #f1f5f9;
      --text2:         #94a3b8;
      --text3:         #64748b;
      --accent:        #6366f1;
      --accent-dim:    rgba(99,102,241,0.15);
      --accent-hover:  #4f46e5;
      --green:         #22c55e;
      --green-dim:     rgba(34,197,94,0.12);
      --green-border:  rgba(34,197,94,0.35);
      --amber:         #f59e0b;
      --amber-dim:     rgba(245,158,11,0.12);
      --amber-border:  rgba(245,158,11,0.35);
      --red:           #ef4444;
      --red-dim:       rgba(239,68,68,0.12);
      --red-border:    rgba(239,68,68,0.35);
      --blue:          #3b82f6;
      --blue-dim:      rgba(59,130,246,0.12);
      --blue-border:   rgba(59,130,246,0.35);
      --input-bg:      #080d18;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      padding: 20px 16px 48px;
      display: flex;
      justify-content: center;
    }

    .container { width: 100%; max-width: 860px; display: flex; flex-direction: column; gap: 14px; }

    /* ── Header ── */
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding-bottom: 16px; border-bottom: 1px solid var(--border);
    }
    .header-left { display: flex; align-items: center; gap: 12px; }
    .header-logo {
      width: 40px; height: 40px;
      background: var(--accent-dim); border: 1px solid rgba(99,102,241,0.3);
      border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px;
    }
    .header-title { font-size: 17px; font-weight: 700; }
    .header-sub { font-size: 12px; color: var(--text3); margin-top: 2px; }

    .status-pill {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 5px 13px; border-radius: 999px; font-size: 12px; font-weight: 600;
      background: var(--surface2); border: 1px solid var(--border2); color: var(--text2);
      transition: all 0.35s;
    }
    .status-pill.running  { background: var(--green-dim); border-color: var(--green-border); color: #4ade80; }
    .status-pill.warning  { background: var(--amber-dim); border-color: var(--amber-border); color: #fbbf24; }

    .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .dot.pulse { animation: dot-pulse 1.3s ease-in-out infinite; }
    @keyframes dot-pulse {
      0%,100% { opacity:1; transform:scale(1); }
      50%      { opacity:0.3; transform:scale(1.6); }
    }

    /* ── Verification banner ── */
    .verify-banner {
      display: none;
      background: linear-gradient(135deg, #1a0a00, #1f1300);
      border: 1.5px solid var(--amber-border); border-radius: 12px;
      padding: 16px 20px; gap: 14px;
      animation: amber-glow 2s ease-in-out infinite alternate;
    }
    .verify-banner.show { display: flex; align-items: flex-start; }
    @keyframes amber-glow {
      from { box-shadow: 0 0 8px rgba(245,158,11,0.15); }
      to   { box-shadow: 0 0 22px rgba(245,158,11,0.4); }
    }
    .verify-icon { font-size: 28px; flex-shrink: 0; margin-top: 2px; }
    .verify-title { font-size: 13px; font-weight: 700; color: #fbbf24; text-transform: uppercase; letter-spacing:.06em; }
    .verify-msg   { font-size: 13px; color: #fde68a; margin-top: 5px; line-height: 1.55; }
    .verify-step  {
      margin-top: 10px; font-size: 12px; color: #fcd34d;
      background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2);
      border-radius: 6px; padding: 7px 11px; display: inline-block;
    }

    /* ── Phase banner ── */
    .phase-banner {
      border-radius: 12px; padding: 13px 18px;
      display: flex; align-items: center; gap: 14px;
      border: 1px solid var(--border2); background: var(--surface);
      transition: border-color 0.4s;
    }
    .phase-icon { font-size: 22px; flex-shrink: 0; }
    .phase-label { font-size: 10px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color: var(--text3); }
    .phase-msg   { font-size: 14px; font-weight:600; color: var(--text); margin-top: 3px; }

    /* ── Cards ── */
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 18px 20px;
    }
    .card-title {
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing:.08em;
      color: var(--text3); margin-bottom: 14px; display:flex; align-items:center; gap:7px;
    }
    .card-title-dot { width:5px; height:5px; border-radius:50%; background: var(--accent); }

    /* ── Form ── */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
    @media (max-width: 540px) { .grid-2 { grid-template-columns: 1fr; } }
    .field { display: flex; flex-direction: column; gap: 5px; }
    label { font-size: 12px; font-weight: 600; color: #cbd5e1; }

    input[type="text"], input[type="password"] {
      background: var(--input-bg); border: 1px solid var(--border2);
      color: var(--text); padding: 10px 13px; border-radius: 8px;
      font-size: 13.5px; font-family: inherit; outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(99,102,241,0.12); }
    input::placeholder { color: var(--text3); }

    .pwd-wrap { position: relative; display: flex; align-items: center; }
    .pwd-wrap input { width: 100%; padding-right: 40px; }
    .pwd-toggle {
      position: absolute; right: 10px; background: none; border: none;
      color: var(--text3); cursor: pointer; font-size: 15px; padding: 2px; line-height: 1;
    }
    .pwd-toggle:hover { color: var(--text2); }

    /* ── Courses ── */
    .courses-wrap { display: flex; flex-direction: column; gap: 8px; }
    .course-row {
      display: flex; gap: 8px; align-items: center;
      background: var(--input-bg); border: 1px solid var(--border2);
      border-radius: 8px; padding: 5px 8px; transition: border-color 0.15s;
    }
    .course-row:focus-within { border-color: var(--accent); }
    .course-num { font-size: 11px; font-weight: 700; color: var(--text3); min-width: 18px; text-align: center; }
    .course-row input { border: none; background: transparent; padding: 6px 8px; border-radius:5px; flex:1; }
    .course-row input:focus { box-shadow: none; }
    .course-sep { width: 1px; height: 20px; background: var(--border2); flex-shrink: 0; }
    .btn-remove {
      background: none; border: none; color: var(--text3); cursor: pointer;
      width: 28px; height: 28px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center; font-size: 14px;
      transition: all 0.15s; flex-shrink: 0;
    }
    .btn-remove:hover { background: var(--red-dim); color: var(--red); }

    .btn-add-course {
      display: flex; align-items: center; gap: 8px; margin-top: 10px;
      padding: 8px 14px; background: none; border: 1px dashed var(--border2);
      color: var(--text3); font-size: 12.5px; font-family: inherit;
      border-radius: 8px; cursor: pointer; font-weight: 500; transition: all 0.15s;
    }
    .btn-add-course:hover { border-color: var(--accent); color: var(--accent); }

    /* ── Action Buttons ── */
    .actions { display: flex; gap: 12px; }
    .btn {
      flex: 1; padding: 13px 20px; border-radius: 10px;
      font-size: 14.5px; font-weight: 700; border: none; cursor: pointer;
      display: flex; align-items: center; justify-content: center; gap: 8px;
      transition: all 0.18s; font-family: inherit;
    }
    .btn-start { background: var(--accent); color: #fff; box-shadow: 0 4px 16px rgba(99,102,241,0.35); }
    .btn-start:hover:not(:disabled) { background: var(--accent-hover); box-shadow: 0 4px 22px rgba(99,102,241,0.5); }
    .btn-stop  { background: var(--surface2); color: var(--red); border: 1px solid var(--red-border); }
    .btn-stop:hover:not(:disabled) { background: var(--red-dim); }
    .btn:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }

    /* ── Monitor grid ── */
    .monitor-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
    .monitor-card {
      background: var(--input-bg); border: 1px solid var(--border);
      border-radius: 8px; padding: 11px 13px;
      display: flex; align-items: center; justify-content: space-between;
      transition: all 0.3s;
    }
    .monitor-card.grabbed   { border-color: var(--green-border); background: var(--green-dim); }
    .monitor-card.searching { border-color: var(--blue-border);  background: var(--blue-dim); }
    .mc-code { font-size: 14px; font-weight: 700; }
    .mc-slot { font-size: 11px; color: var(--text3); margin-top: 2px; }
    .pill {
      font-size: 10.5px; font-weight: 700; padding: 3px 9px; border-radius: 999px;
    }
    .pill.grabbed   { background: var(--green-dim); color: #4ade80; border: 1px solid var(--green-border); }
    .pill.searching { background: var(--blue-dim);  color: #60a5fa; border: 1px solid var(--blue-border); }
    .pill.idle      { background: #0d1424; color: var(--text3); border: 1px solid var(--border); }

    /* ── Terminal ── */
    .terminal { background: #030507; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
    .term-header {
      background: var(--surface2); border-bottom: 1px solid var(--border);
      padding: 8px 14px; display: flex; align-items: center; justify-content: space-between;
    }
    .term-title { font-size: 11px; font-weight: 600; color: var(--text3); display: flex; align-items: center; gap: 8px; }
    .term-dots  { display: flex; gap: 5px; }
    .term-dot   { width: 10px; height: 10px; border-radius: 50%; }
    .term-dot.r { background: #ef4444; }
    .term-dot.y { background: #f59e0b; }
    .term-dot.g { background: #22c55e; }
    .term-clear { background: none; border: none; color: var(--text3); font-size: 11px; cursor: pointer; font-family: inherit; }
    .term-clear:hover { color: var(--text2); }
    .term-body {
      padding: 12px 16px; font-family: 'SF Mono', 'Fira Mono', Menlo, Consolas, monospace;
      font-size: 11.5px; color: #94a3b8; height: 200px; overflow-y: auto;
      line-height: 1.65; display: flex; flex-direction: column; gap: 1px;
    }
    .log-line { display: block; }
    .log-grabbed { color: #4ade80; }
    .log-warn    { color: #fbbf24; }
    .log-error   { color: #f87171; }
    .log-info    { color: #60a5fa; }

    /* ── Results ── */
    .results-banner {
      display: none; border: 1.5px solid var(--green-border); border-radius: 12px;
      background: linear-gradient(135deg, #071a0e, #0a1f10); padding: 18px 20px;
    }
    .results-banner.show { display: block; }
    .results-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .results-title { font-size: 12px; font-weight: 700; color: #4ade80; text-transform: uppercase; letter-spacing:.07em; }
    .btn-copy {
      background: none; border: 1px solid var(--green-border); color: #4ade80;
      font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 6px;
      cursor: pointer; font-family: inherit; transition: background 0.15s;
    }
    .btn-copy:hover { background: var(--green-dim); }
    .results-body {
      font-family: 'SF Mono', Menlo, monospace; font-size: 12.5px; color: #d1fae5;
      line-height: 1.7; white-space: pre-wrap;
      background: rgba(0,0,0,0.3); border-radius: 6px; padding: 10px 14px;
    }

    /* ── Toast ── */
    .toast-wrap {
      position: fixed; bottom: 24px; right: 24px;
      display: flex; flex-direction: column; gap: 8px; z-index: 9999;
      pointer-events: none;
    }
    .toast {
      padding: 11px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
      max-width: 320px; border: 1px solid; cursor: pointer; pointer-events: all;
      animation: toast-in 0.25s ease; transition: opacity 0.3s, transform 0.3s;
    }
    .toast.success { background: var(--green-dim); border-color: var(--green-border); color: #4ade80; }
    .toast.error   { background: var(--red-dim);   border-color: var(--red-border);   color: #f87171; }
    .toast.info    { background: var(--blue-dim);  border-color: var(--blue-border);  color: #60a5fa; }
    .toast.warning { background: var(--amber-dim); border-color: var(--amber-border); color: #fbbf24; }
    @keyframes toast-in {
      from { opacity:0; transform:translateY(10px); }
      to   { opacity:1; transform:translateY(0); }
    }
  </style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <div class="header-logo">🤖</div>
      <div>
        <div class="header-title">DTU Course Bot</div>
        <div class="header-sub">exam-setu.dtu.ac.in &nbsp;·&nbsp; Automation Dashboard</div>
      </div>
    </div>
    <div id="statusPill" class="status-pill">
      <span class="dot" id="statusDot"></span>
      <span id="statusText">Idle</span>
    </div>
  </div>

  <!-- Verification Banner -->
  <div id="verifyBanner" class="verify-banner">
    <div class="verify-icon">🔔</div>
    <div>
      <div class="verify-title">Action Required — Verify You Are Human</div>
      <div class="verify-msg">Cloudflare is showing a verification checkbox in your Chrome window.<br>Switch to Chrome and click the checkbox — automation resumes automatically!</div>
      <div class="verify-step">Switch to Chrome → Click the checkbox ✅</div>
    </div>
  </div>

  <!-- Phase Banner -->
  <div class="phase-banner">
    <div class="phase-icon" id="phaseIcon">⚡</div>
    <div>
      <div class="phase-label">Current Status</div>
      <div class="phase-msg" id="phaseMsg">Ready — enter your details below and hit Start Automation</div>
    </div>
  </div>

  <!-- Credentials & Courses -->
  <div class="card">
    <div class="card-title"><span class="card-title-dot"></span>Credentials &amp; Target Courses</div>

    <div class="grid-2">
      <div class="field">
        <label for="rollInput">Roll Number</label>
        <input type="text" id="rollInput" placeholder="e.g. 23/IT/94" autocomplete="off" spellcheck="false" />
      </div>
      <div class="field">
        <label for="pwdInput">Password</label>
        <div class="pwd-wrap">
          <input type="password" id="pwdInput" placeholder="Your portal password" autocomplete="current-password" />
          <button class="pwd-toggle" type="button" onclick="togglePwd()" title="Show/hide password">👁</button>
        </div>
      </div>
    </div>

    <div class="card-title" style="margin-bottom:10px">
      <span class="card-title-dot"></span>Courses to Grab
      <span style="font-weight:400;font-size:10px;color:var(--text3)">(top = highest priority)</span>
    </div>
    <div id="coursesList" class="courses-wrap"></div>
    <button class="btn-add-course" type="button" id="btnAddCourse">＋ Add Course</button>
  </div>

  <!-- Action Buttons -->
  <div class="actions">
    <button id="btnStart" class="btn btn-start" onclick="startAutomation()">🚀&nbsp; Start Automation</button>
    <button id="btnStop"  class="btn btn-stop"  onclick="stopAutomation()" disabled>⏹&nbsp; Stop</button>
  </div>

  <!-- Live Monitor -->
  <div class="card">
    <div class="card-title"><span class="card-title-dot"></span>Live Course Monitor</div>
    <div id="monitorGrid" class="monitor-grid"></div>
  </div>

  <!-- Results -->
  <div id="resultsBanner" class="results-banner">
    <div class="results-header">
      <span class="results-title">🎉 Session Results</span>
      <button class="btn-copy" onclick="copyResults()">📋 Copy</button>
    </div>
    <pre id="resultsBody" class="results-body"></pre>
  </div>

  <!-- Terminal -->
  <div class="terminal">
    <div class="term-header">
      <div class="term-title">
        <div class="term-dots">
          <div class="term-dot r"></div>
          <div class="term-dot y"></div>
          <div class="term-dot g"></div>
        </div>
        Activity Log
      </div>
      <button class="term-clear" onclick="clearTerm()">Clear</button>
    </div>
    <div id="termBody" class="term-body">
      <span class="log-line">Waiting for automation to start…</span>
    </div>
  </div>

</div>

<div class="toast-wrap" id="toastWrap"></div>

<script>
  /* ── State ─────────────────────────────────── */
  let prevRunning  = false;
  let verifyActive = false;
  let renderedLogCount = 0;

  /* ── Toast ──────────────────────────────────── */
  function toast(msg, type = 'info', dur = 3800) {
    const wrap = document.getElementById('toastWrap');
    const el   = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    el.onclick = () => fadeRemove(el);
    wrap.appendChild(el);
    setTimeout(() => fadeRemove(el), dur);
  }
  function fadeRemove(el) {
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 320);
  }

  /* ── Helpers ────────────────────────────────── */
  function clearTerm() {
    document.getElementById('termBody').innerHTML = '';
    renderedLogCount = 0;
  }

  function togglePwd() {
    const p = document.getElementById('pwdInput');
    p.type = p.type === 'password' ? 'text' : 'password';
  }

  function setPhase(icon, msg) {
    document.getElementById('phaseIcon').textContent = icon;
    document.getElementById('phaseMsg').textContent  = msg;
  }

  /* ── Course rows (safe DOM build — no innerHTML injection) ── */
  document.getElementById('btnAddCourse').addEventListener('click', () => addCourseRow('', ''));

  function addCourseRow(code, slot) {
    const list = document.getElementById('coursesList');
    const idx  = list.children.length + 1;

    const row = document.createElement('div');
    row.className = 'course-row';

    const num = document.createElement('span');
    num.className = 'course-num';
    num.textContent = idx;

    const codeInp = document.createElement('input');
    codeInp.type = 'text';
    codeInp.className = 'course-code';
    codeInp.placeholder = 'Course code (e.g. HU306)';
    codeInp.value = code || '';
    codeInp.spellcheck = false;
    codeInp.autocomplete = 'off';

    const sep = document.createElement('div');
    sep.className = 'course-sep';

    const slotInp = document.createElement('input');
    slotInp.type = 'text';
    slotInp.className = 'course-slot';
    slotInp.placeholder = 'Slot (e.g. E1)';
    slotInp.value = slot || '';
    slotInp.spellcheck = false;
    slotInp.autocomplete = 'off';
    slotInp.style.maxWidth = '120px';

    const rmBtn = document.createElement('button');
    rmBtn.type = 'button';
    rmBtn.className = 'btn-remove';
    rmBtn.title = 'Remove';
    rmBtn.textContent = '✕';
    rmBtn.addEventListener('click', () => { row.remove(); renumber(); });

    // Enter key navigation
    codeInp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); slotInp.focus(); }
    });
    slotInp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); addCourseRow('', ''); }
    });

    row.append(num, codeInp, sep, slotInp, rmBtn);
    list.appendChild(row);
    renumber();

    if (!code) codeInp.focus();
  }

  function renumber() {
    document.querySelectorAll('#coursesList .course-row').forEach((r, i) => {
      r.querySelector('.course-num').textContent = i + 1;
    });
  }

  function getCourses() {
    const out = [];
    document.querySelectorAll('#coursesList .course-row').forEach(r => {
      const code = r.querySelector('.course-code').value.trim().toUpperCase();
      const slot = r.querySelector('.course-slot').value.trim().toUpperCase();
      if (code) out.push({ code, slot: slot || null });
    });
    return out;
  }

  /* ── Monitor grid ───────────────────────────── */
  function renderMonitorGrid(courses, running) {
    const grid = document.getElementById('monitorGrid');
    grid.innerHTML = '';
    courses.forEach(c => {
      const isGrabbed   = c.status === 'GRABBED';
      const isSearching = running && !isGrabbed;

      const card = document.createElement('div');
      card.className = 'monitor-card' + (isGrabbed ? ' grabbed' : isSearching ? ' searching' : '');

      const left = document.createElement('div');
      const code = document.createElement('div');
      code.className = 'mc-code';
      code.textContent = c.code;
      const slotEl = document.createElement('div');
      slotEl.className = 'mc-slot';
      slotEl.textContent = 'Slot: ' + (c.slot || 'ANY');
      left.append(code, slotEl);

      const pill = document.createElement('span');
      if (isGrabbed) {
        pill.className = 'pill grabbed'; pill.textContent = '✅ GRABBED';
      } else if (isSearching) {
        pill.className = 'pill searching'; pill.textContent = '🔍 Searching…';
      } else {
        pill.className = 'pill idle'; pill.textContent = '— Not grabbed';
      }

      card.append(left, pill);
      grid.appendChild(card);
    });
  }

  /* ── Results ────────────────────────────────── */
  function renderResults(courses) {
    let out = '══════════════════════════════════════\n  RESULTS\n══════════════════════════════════════\n';
    courses.forEach(c => {
      const st = c.status === 'GRABBED' ? '✅ GRABBED    ' : '❌ NOT GRABBED';
      out += `  ${st}  ${c.code.padEnd(8)} (slot: ${c.slot || 'ANY'})\n`;
    });
    out += '══════════════════════════════════════';
    document.getElementById('resultsBody').textContent = out;
    document.getElementById('resultsBanner').classList.add('show');
  }

  function copyResults() {
    const text = document.getElementById('resultsBody').textContent;
    navigator.clipboard.writeText(text).then(() => toast('Copied!', 'success', 2000));
  }

  /* ── Load saved config (only when bot is not running) ── */
  async function loadConfig() {
    try {
      const { running } = await fetch('/api/status').then(r => r.json());
      if (running) return;  // don't overwrite live course list
    } catch (_) {}

    try {
      const data = await fetch('/api/config').then(r => r.json());
      document.getElementById('rollInput').value = data.roll || '';
      document.getElementById('pwdInput').value  = data.password || '';
      document.getElementById('coursesList').innerHTML = '';
      renderedLogCount = 0;
      (data.courses || []).forEach(c => addCourseRow(c.code, c.slot || ''));
      renderMonitorGrid((data.courses || []).map(c => ({...c, status: 'IDLE'})), false);
    } catch (_) {}
  }

  /* ── Start / Stop ───────────────────────────── */
  async function startAutomation() {
    const roll    = document.getElementById('rollInput').value.trim();
    const pwd     = document.getElementById('pwdInput').value.trim();
    const courses = getCourses();

    if (!roll || !pwd) { toast('Enter your Roll Number and Password first.', 'error'); return; }
    if (!courses.length) { toast('Add at least one course to grab.', 'error'); return; }

    document.getElementById('btnStart').disabled = true;
    document.getElementById('btnStop').disabled  = false;
    document.getElementById('resultsBanner').classList.remove('show');
    setPhase('🚀', 'Starting automation…');

    try {
      const res  = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ roll, password: pwd, courses })
      });
      const data = await res.json();
      if (data.ok) {
        toast('Automation started!', 'success');
      } else {
        toast(data.msg || 'Failed to start.', 'error');
        document.getElementById('btnStart').disabled = false;
        document.getElementById('btnStop').disabled  = true;
      }
    } catch (err) {
      toast('Network error — could not reach dashboard server.', 'error');
      document.getElementById('btnStart').disabled = false;
      document.getElementById('btnStop').disabled  = true;
    }
  }

  async function stopAutomation() {
    document.getElementById('btnStop').disabled = true;
    try {
      await fetch('/api/stop', { method: 'POST' });
    } catch (_) {}
    // Always re-enable Start so the user isn't stuck
    document.getElementById('btnStart').disabled = false;
    toast('Stopping automation…', 'info');
  }

  /* ── Poll status ────────────────────────────── */
  async function pollStatus() {
    try {
      const res  = await fetch('/api/status');
      const data = await res.json();
      const running = data.running;

      /* Status pill */
      const pill    = document.getElementById('statusPill');
      const dot     = document.getElementById('statusDot');
      const pillTxt = document.getElementById('statusText');
      const verifyBanner = document.getElementById('verifyBanner');

      /* Detect verification needed — look for the ACTION REQUIRED prefix set by bot */
      const action = (data.status && data.status.action) ? data.status.action : '';
      const isVerify = running && (
        action.includes('ACTION REQUIRED') ||
        action.toLowerCase().includes('verify you are human') ||
        action.toLowerCase().includes('click')
      );

      if (isVerify) {
        if (!verifyActive) { toast('⚠️ Please click the verification box in Chrome!', 'warning', 8000); }
        verifyActive = true;
        verifyBanner.classList.add('show');
        pill.className = 'status-pill warning';
        dot.className  = 'dot pulse';
        pillTxt.textContent = 'Needs Verification';
      } else {
        verifyActive = false;
        verifyBanner.classList.remove('show');
        if (running) {
          pill.className = 'status-pill running';
          dot.className  = 'dot pulse';
          pillTxt.textContent = 'Running';
        } else {
          pill.className = 'status-pill';
          dot.className  = 'dot';
          pillTxt.textContent = 'Idle';
        }
      }

      /* Buttons — keep in sync with actual running state */
      document.getElementById('btnStart').disabled = running;
      document.getElementById('btnStop').disabled  = !running;

      /* Phase banner */
      if (action) {
        let icon = '⚡';
        const a = action.toLowerCase();
        if (action.includes('🔑') || a.includes('log')) icon = '🔑';
        else if (action.includes('🎉') || a.includes('grab')) icon = '🎉';
        else if (action.includes('🔍') || a.includes('scan')) icon = '🔍';
        else if (action.includes('🔔') || a.includes('action required') || a.includes('verify')) icon = '🛡️';
        else if (action.includes('🚀') || a.includes('verified') || a.includes('resuming')) icon = '🚀';
        else if (a.includes('stop')) icon = '🛑';
        // Strip leading emoji/punctuation for display
        setPhase(icon, action.replace(/^[\s\p{Emoji_Presentation}\p{Extended_Pictographic}🔔🔑🎉🔍🚀🌐⚠️✅❌📋🤖⏳]+/u, '').trim() || action);
      } else if (!running && !prevRunning) {
        setPhase('⚡', 'Ready — enter your details below and hit Start Automation');
      }

      /* Monitor grid */
      if (data.status && data.status.courses) {
        renderMonitorGrid(data.status.courses, running);
        if (prevRunning && !running) {
          renderResults(data.status.courses);
          setPhase('✅', 'Session complete — check results below');
          toast('Automation finished!', 'success', 5000);
        }
      }

      prevRunning = running;

      /* Terminal logs — safe textContent per span, no innerHTML injection */
      if (data.logs && data.logs.length > 0) {
        const term = document.getElementById('termBody');
        const atBottom = term.scrollTop + term.clientHeight >= term.scrollHeight - 40;

        // Only append new lines since last render
        if (data.logs.length > renderedLogCount) {
          const newLines = data.logs.slice(renderedLogCount);
          newLines.forEach(line => {
            const span = document.createElement('span');
            span.className = 'log-line';
            if (line.includes('✅') || line.includes('GRABBED'))    span.classList.add('log-grabbed');
            else if (line.includes('⚠️') || line.includes('🔔'))    span.classList.add('log-warn');
            else if (line.includes('❌') || line.includes('FATAL')) span.classList.add('log-error');
            else if (line.includes('🔑') || line.includes('🌐') || line.includes('🚀') || line.includes('ℹ️')) span.classList.add('log-info');
            span.textContent = line;  // safe — no innerHTML
            term.appendChild(span);
          });
          renderedLogCount = data.logs.length;
          if (atBottom) term.scrollTop = term.scrollHeight;
        }
      }

    } catch(_) { /* network hiccup, ignore */ }
  }

  loadConfig();
  setInterval(pollStatus, 1000);
</script>
</body>
</html>
"""


def main():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
        print("=" * 64)
        print("  🎉 DTU Course Registration Bot — Dashboard Online!")
        print(f"  👉 Open in browser: http://localhost:{PORT}")
        print("  Press Ctrl+C to shut down the dashboard.")
        print("=" * 64)

        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down…")
            if bot_process is not None and bot_process.poll() is None:
                bot_process.terminate()
            httpd.server_close()


if __name__ == "__main__":
    main()
