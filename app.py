#!/usr/bin/env python3
"""
DTU Course Registration - Control Dashboard
Run with: python app.py
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

bot_process = None
log_lines = []
log_lock = threading.Lock()


def append_log(text):
    with log_lock:
        log_lines.append(text)
        if len(log_lines) > 800:
            log_lines.pop(0)


def read_current_config():
    roll, pwd = "", ""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ROLL_NUMBER="):
                    roll = line.split("=", 1)[1].strip()
                elif line.startswith("PASSWORD="):
                    pwd = line.split("=", 1)[1].strip()

    courses = []
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            content = f.read()
        match = re.search(r"COURSES_TO_ADD\s*=\s*(\[.*?\])", content, re.DOTALL)
        if match:
            try:
                raw = match.group(1)
                norm = re.sub(r"None", "null", raw)
                norm = re.sub(r"'", '"', norm)
                norm = re.sub(r",\s*]", "]", norm)
                courses = json.loads(norm)
            except Exception:
                pass

    if not courses:
        courses = [
            {"code": "HU306", "slot": "E1"},
            {"code": "HU328", "slot": "E2"},
            {"code": "HU426", "slot": "E4"},
            {"code": "HU308", "slot": "E4"},
            {"code": "HU404", "slot": "E4"},
            {"code": "HU312", "slot": "E5"},
        ]

    return {"roll": roll, "password": pwd, "courses": courses}


def save_config(roll, pwd, courses):
    if roll or pwd:
        with open(ENV_FILE, "w") as f:
            f.write(f"ROLL_NUMBER={roll.strip()}\n")
            f.write(f"PASSWORD={pwd.strip()}\n")

    courses_repr = "COURSES_TO_ADD = [\n"
    for c in courses:
        slot_val = f'"{c.get("slot")}"' if c.get("slot") else "None"
        courses_repr += f'    {{"code": "{c.get("code","").strip()}", "slot": {slot_val}}},\n'
    courses_repr += "]"

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            content = f.read()
        new_content = re.sub(
            r"COURSES_TO_ADD\s*=\s*\[.*?\]", courses_repr, content, flags=re.DOTALL
        )
        with open(CONFIG_FILE, "w") as f:
            f.write(new_content)


def stream_process_output(proc):
    global bot_process
    for line in iter(proc.stdout.readline, ""):
        if line:
            clean = line.rstrip()
            append_log(clean)
            print(clean, flush=True)
    proc.stdout.close()
    proc.wait()
    with log_lock:
        bot_process = None


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence server request logs

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
            data = read_current_config()
            self._json(data)

        elif self.path.startswith("/api/status"):
            is_running = bot_process is not None and bot_process.poll() is None
            with log_lock:
                recent_logs = list(log_lines)

            status_info = {}
            if os.path.exists(STATUS_FILE):
                try:
                    with open(STATUS_FILE, "r") as sf:
                        status_info = json.load(sf)
                except Exception:
                    pass

            self._json({"running": is_running, "logs": recent_logs, "status": status_info})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global bot_process
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if self.path == "/api/start":
            roll = payload.get("roll", "")
            pwd = payload.get("password", "")
            courses = payload.get("courses", [])

            save_config(roll, pwd, courses)

            if bot_process is not None and bot_process.poll() is None:
                self._json({"ok": False, "msg": "Already running!"})
                return

            with log_lock:
                log_lines.clear()

            # Remove stale status file
            try:
                if os.path.exists(STATUS_FILE):
                    os.remove(STATUS_FILE)
            except Exception:
                pass

            append_log(f"[{time.strftime('%H:%M:%S')}] 🚀 Starting automation for {roll}...")

            venv_python = os.path.join(BASE_DIR, "venv", "bin", "python3")
            python_bin = venv_python if os.path.exists(venv_python) else sys.executable
            bot_script = os.path.join(BASE_DIR, "bot.py")

            bot_process = subprocess.Popen(
                [python_bin, "-u", bot_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=BASE_DIR,
                bufsize=1,
            )

            t = threading.Thread(target=stream_process_output, args=(bot_process,), daemon=True)
            t.start()

            self._json({"ok": True, "msg": "Bot started"})

        elif self.path == "/api/stop":
            if bot_process is not None and bot_process.poll() is None:
                append_log(f"[{time.strftime('%H:%M:%S')}] 🛑 Stopping automation...")
                try:
                    bot_process.send_signal(signal.SIGINT)
                except Exception:
                    try:
                        bot_process.terminate()
                    except Exception:
                        pass
                self._json({"ok": True, "msg": "Stopped"})
            else:
                self._json({"ok": False, "msg": "Not running"})

    def _json(self, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


# ─────────────────────────────────────────────────────────────────────────────
# HTML UI
# ─────────────────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DTU Course Registration Bot</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    :root {
      --bg: #05080f;
      --surface: #0d1424;
      --surface2: #111827;
      --border: #1f2d45;
      --border2: #263348;
      --text: #f1f5f9;
      --text2: #94a3b8;
      --text3: #64748b;
      --accent: #6366f1;
      --accent-dim: rgba(99,102,241,0.15);
      --accent-hover: #4f46e5;
      --green: #22c55e;
      --green-dim: rgba(34,197,94,0.12);
      --green-border: rgba(34,197,94,0.35);
      --amber: #f59e0b;
      --amber-dim: rgba(245,158,11,0.12);
      --amber-border: rgba(245,158,11,0.35);
      --red: #ef4444;
      --red-dim: rgba(239,68,68,0.12);
      --red-border: rgba(239,68,68,0.35);
      --blue: #3b82f6;
      --blue-dim: rgba(59,130,246,0.12);
      --blue-border: rgba(59,130,246,0.35);
      --input-bg: #080d18;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      padding: 20px 16px 40px;
      display: flex;
      justify-content: center;
    }

    .container { width: 100%; max-width: 860px; display: flex; flex-direction: column; gap: 16px; }

    /* ── Header ── */
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .header-left { display: flex; align-items: center; gap: 12px; }
    .header-logo {
      width: 38px; height: 38px;
      background: var(--accent-dim);
      border: 1px solid rgba(99,102,241,0.3);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px;
    }
    .header-title { font-size: 17px; font-weight: 700; color: var(--text); }
    .header-sub { font-size: 12px; color: var(--text3); margin-top: 1px; }

    .status-pill {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 5px 12px; border-radius: 999px;
      font-size: 12px; font-weight: 600;
      background: var(--surface2); border: 1px solid var(--border2);
      color: var(--text2); transition: all 0.3s;
    }
    .status-pill.running {
      background: var(--green-dim); border-color: var(--green-border);
      color: #4ade80;
    }
    .status-pill.warning {
      background: var(--amber-dim); border-color: var(--amber-border);
      color: #fbbf24;
    }
    .dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: currentColor;
    }
    .dot.pulse { animation: dot-pulse 1.3s ease-in-out infinite; }
    @keyframes dot-pulse {
      0%,100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.3; transform: scale(1.5); }
    }

    /* ── Verification Alert Banner ── */
    .verify-banner {
      display: none;
      background: linear-gradient(135deg, #1a0a00 0%, #1f1200 100%);
      border: 1.5px solid var(--amber-border);
      border-radius: 12px;
      padding: 16px 20px;
      animation: banner-glow 2s ease-in-out infinite alternate;
    }
    .verify-banner.show { display: flex; align-items: flex-start; gap: 14px; }
    @keyframes banner-glow {
      from { box-shadow: 0 0 10px rgba(245,158,11,0.15); }
      to   { box-shadow: 0 0 24px rgba(245,158,11,0.35); }
    }
    .verify-icon { font-size: 28px; flex-shrink: 0; margin-top: 2px; }
    .verify-title {
      font-size: 14px; font-weight: 700; color: #fbbf24;
      text-transform: uppercase; letter-spacing: 0.06em;
    }
    .verify-msg { font-size: 13px; color: #fde68a; margin-top: 4px; line-height: 1.5; }
    .verify-step {
      margin-top: 8px; font-size: 12px; color: #fcd34d;
      background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2);
      border-radius: 6px; padding: 6px 10px; display: inline-block;
    }

    /* ── Live Phase Banner ── */
    .phase-banner {
      border-radius: 12px; padding: 14px 18px;
      display: flex; align-items: center; gap: 14px;
      border: 1px solid var(--border2);
      background: var(--surface);
      transition: all 0.4s;
    }
    .phase-icon { font-size: 24px; flex-shrink: 0; }
    .phase-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text3); }
    .phase-msg { font-size: 14px; font-weight: 600; color: var(--text); margin-top: 3px; }

    /* ── Cards ── */
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px 20px;
    }
    .card-title {
      font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.08em;
      color: var(--text3); margin-bottom: 14px;
      display: flex; align-items: center; gap: 7px;
    }
    .card-title-dot {
      width: 5px; height: 5px; border-radius: 50%;
      background: var(--accent); display: inline-block;
    }

    /* ── Form ── */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
    @media (max-width: 540px) { .grid-2 { grid-template-columns: 1fr; } }

    .field { display: flex; flex-direction: column; gap: 5px; }
    label { font-size: 12px; font-weight: 600; color: #cbd5e1; }

    input[type="text"], input[type="password"] {
      background: var(--input-bg);
      border: 1px solid var(--border2);
      color: var(--text);
      padding: 10px 13px;
      border-radius: 8px;
      font-size: 13.5px;
      font-family: inherit;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(99,102,241,0.12);
    }

    .pwd-wrap { position: relative; display: flex; align-items: center; }
    .pwd-wrap input { width: 100%; padding-right: 40px; }
    .pwd-toggle {
      position: absolute; right: 10px;
      background: none; border: none;
      color: var(--text3); cursor: pointer; font-size: 14px; padding: 2px;
    }
    .pwd-toggle:hover { color: var(--text2); }

    /* ── Courses ── */
    .courses-wrap { display: flex; flex-direction: column; gap: 8px; }
    .course-row {
      display: flex; gap: 8px; align-items: center;
      background: var(--input-bg); border: 1px solid var(--border2);
      border-radius: 8px; padding: 6px 8px;
      transition: border-color 0.15s;
    }
    .course-row:focus-within { border-color: var(--accent); }
    .course-row-num {
      font-size: 11px; font-weight: 700; color: var(--text3);
      min-width: 20px; text-align: center;
    }
    .course-row input {
      border: none; background: transparent;
      padding: 5px 8px; border-radius: 5px; flex: 1;
    }
    .course-row input:focus { box-shadow: none; }
    .course-sep { width: 1px; height: 20px; background: var(--border2); }
    .btn-remove {
      background: none; border: none;
      color: var(--text3); cursor: pointer;
      width: 28px; height: 28px;
      border-radius: 6px; display: flex; align-items: center; justify-content: center;
      font-size: 14px; transition: all 0.15s; flex-shrink: 0;
    }
    .btn-remove:hover { background: var(--red-dim); color: var(--red); }

    .btn-add-course {
      display: flex; align-items: center; gap: 7px;
      margin-top: 10px; padding: 8px 14px;
      background: none; border: 1px dashed var(--border2);
      color: var(--text3); font-size: 12.5px; font-family: inherit;
      border-radius: 8px; cursor: pointer; font-weight: 500;
      transition: all 0.15s;
    }
    .btn-add-course:hover { border-color: var(--accent); color: var(--accent); }

    /* ── Action Buttons ── */
    .actions { display: flex; gap: 12px; }
    .btn {
      flex: 1; padding: 13px 20px;
      border-radius: 10px; font-size: 14.5px;
      font-weight: 700; border: none; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      gap: 8px; transition: all 0.18s; font-family: inherit;
      position: relative; overflow: hidden;
    }
    .btn::after {
      content: '';
      position: absolute; inset: 0;
      background: rgba(255,255,255,0); transition: background 0.15s;
    }
    .btn:hover::after { background: rgba(255,255,255,0.05); }
    .btn-start {
      background: var(--accent);
      color: #fff;
      box-shadow: 0 4px 16px rgba(99,102,241,0.35);
    }
    .btn-start:hover { background: var(--accent-hover); box-shadow: 0 4px 22px rgba(99,102,241,0.5); }
    .btn-stop {
      background: var(--surface2); color: var(--red);
      border: 1px solid var(--red-border);
    }
    .btn-stop:hover { background: var(--red-dim); }
    .btn:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
    .btn:disabled:hover::after { background: none; }

    /* ── Monitor Grid ── */
    .monitor-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 10px;
    }
    .monitor-card {
      background: var(--input-bg);
      border: 1px solid var(--border);
      border-radius: 8px; padding: 11px 13px;
      display: flex; align-items: center; justify-content: space-between;
      transition: all 0.3s;
    }
    .monitor-card.grabbed {
      border-color: var(--green-border);
      background: var(--green-dim);
    }
    .monitor-card.searching {
      border-color: var(--blue-border);
      background: var(--blue-dim);
    }
    .mc-left h4 { font-size: 14px; font-weight: 700; }
    .mc-left span { font-size: 11px; color: var(--text3); margin-top: 2px; display: block; }

    .pill {
      font-size: 10.5px; font-weight: 700;
      padding: 3px 9px; border-radius: 999px;
    }
    .pill.grabbed { background: var(--green-dim); color: #4ade80; border: 1px solid var(--green-border); }
    .pill.searching { background: var(--blue-dim); color: #60a5fa; border: 1px solid var(--blue-border); }
    .pill.idle { background: #0d1424; color: var(--text3); border: 1px solid var(--border); }

    /* ── Terminal ── */
    .terminal {
      background: #030507;
      border: 1px solid var(--border);
      border-radius: 10px; overflow: hidden;
    }
    .term-header {
      background: var(--surface2);
      border-bottom: 1px solid var(--border);
      padding: 8px 14px;
      display: flex; align-items: center; justify-content: space-between;
    }
    .term-title { font-size: 11px; font-weight: 600; color: var(--text3); display: flex; align-items: center; gap: 7px; }
    .term-dots { display: flex; gap: 5px; }
    .term-dot { width: 10px; height: 10px; border-radius: 50%; }
    .term-dot.red { background: #ef4444; }
    .term-dot.yellow { background: #f59e0b; }
    .term-dot.green { background: #22c55e; }
    .term-clear {
      background: none; border: none; color: var(--text3);
      font-size: 11px; cursor: pointer; font-family: inherit;
    }
    .term-clear:hover { color: var(--text2); }
    .term-body {
      padding: 12px 16px;
      font-family: 'SF Mono', 'Fira Mono', Menlo, Consolas, monospace;
      font-size: 11.5px; color: #94a3b8;
      height: 180px; overflow-y: auto;
      line-height: 1.6; white-space: pre-wrap;
      scroll-behavior: smooth;
    }
    /* color log lines */
    .log-grabbed { color: #4ade80; }
    .log-warn    { color: #fbbf24; }
    .log-error   { color: #f87171; }
    .log-info    { color: #60a5fa; }

    /* ── Results ── */
    .results-banner {
      display: none;
      background: linear-gradient(135deg, #071a0e 0%, #0a1f10 100%);
      border: 1.5px solid var(--green-border);
      border-radius: 12px; padding: 18px 20px;
    }
    .results-banner.show { display: block; }
    .results-header {
      display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;
    }
    .results-title { font-size: 12px; font-weight: 700; color: #4ade80; text-transform: uppercase; letter-spacing: 0.07em; }
    .btn-copy {
      background: none; border: 1px solid var(--green-border);
      color: #4ade80; font-size: 11px; font-weight: 600;
      padding: 5px 10px; border-radius: 6px; cursor: pointer; font-family: inherit;
    }
    .btn-copy:hover { background: var(--green-dim); }
    .results-body {
      font-family: 'SF Mono', Menlo, monospace;
      font-size: 12.5px; color: #d1fae5;
      line-height: 1.7; white-space: pre-wrap;
      background: rgba(0,0,0,0.3); border-radius: 6px; padding: 10px 14px;
    }

    /* ── Toast ── */
    .toast-container {
      position: fixed; bottom: 24px; right: 24px;
      display: flex; flex-direction: column; gap: 8px; z-index: 9999;
    }
    .toast {
      padding: 11px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
      max-width: 300px; border: 1px solid;
      animation: toast-in 0.25s ease;
      cursor: pointer;
    }
    .toast.success { background: var(--green-dim); border-color: var(--green-border); color: #4ade80; }
    .toast.error   { background: var(--red-dim);   border-color: var(--red-border);   color: #f87171; }
    .toast.info    { background: var(--blue-dim);  border-color: var(--blue-border);  color: #60a5fa; }
    @keyframes toast-in {
      from { opacity: 0; transform: translateY(12px); }
      to   { opacity: 1; transform: translateY(0); }
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
        <div class="header-sub">exam-setu.dtu.ac.in &nbsp;·&nbsp; Automation Center</div>
      </div>
    </div>
    <div id="statusPill" class="status-pill">
      <span class="dot" id="statusDot"></span>
      <span id="statusText">Idle</span>
    </div>
  </div>

  <!-- Verification Alert (shows when Cloudflare check is needed) -->
  <div id="verifyBanner" class="verify-banner">
    <div class="verify-icon">🔔</div>
    <div>
      <div class="verify-title">Action Required — Verify You Are Human</div>
      <div class="verify-msg">The browser has a Cloudflare verification checkbox.<br>Switch to the browser window and click the checkbox to continue.</div>
      <div class="verify-step">Step: Switch to Chrome → Click the checkbox → Automation resumes automatically ✅</div>
    </div>
  </div>

  <!-- Live Phase Banner -->
  <div class="phase-banner" id="phaseBanner">
    <div class="phase-icon" id="phaseIcon">⚡</div>
    <div>
      <div class="phase-label">Current Status</div>
      <div class="phase-msg" id="phaseMsg">Ready — fill in your details below and hit Start Automation</div>
    </div>
  </div>

  <!-- Credentials & Courses Card -->
  <div class="card">
    <div class="card-title"><span class="card-title-dot"></span> Credentials & Target Courses</div>

    <div class="grid-2">
      <div class="field">
        <label for="rollInput">Roll Number</label>
        <input type="text" id="rollInput" placeholder="e.g. 23/IT/94" autocomplete="off" spellcheck="false" />
      </div>
      <div class="field">
        <label for="pwdInput">Password</label>
        <div class="pwd-wrap">
          <input type="password" id="pwdInput" placeholder="Your portal password" />
          <button class="pwd-toggle" type="button" onclick="togglePwd()" title="Show/Hide">👁</button>
        </div>
      </div>
    </div>

    <div class="card-title" style="margin-bottom:10px"><span class="card-title-dot"></span> Courses to Grab <span style="font-weight:400;font-size:10px;color:var(--text3)">(top = highest priority)</span></div>
    <div id="coursesList" class="courses-wrap"></div>
    <button class="btn-add-course" type="button" onclick="addCourseRow('','')">
      ＋ Add Course
    </button>
  </div>

  <!-- Action Buttons -->
  <div class="actions">
    <button id="btnStart" class="btn btn-start" onclick="startAutomation()">
      🚀&nbsp; Start Automation
    </button>
    <button id="btnStop" class="btn btn-stop" onclick="stopAutomation()" disabled>
      ⏹&nbsp; Stop
    </button>
  </div>

  <!-- Live Monitoring Grid -->
  <div class="card">
    <div class="card-title"><span class="card-title-dot"></span> Live Course Monitor</div>
    <div id="monitorGrid" class="monitor-grid"></div>
  </div>

  <!-- Results Banner (shown after session ends) -->
  <div id="resultsBanner" class="results-banner">
    <div class="results-header">
      <span class="results-title">🎉 Session Results</span>
      <button class="btn-copy" onclick="copyResults()">📋 Copy</button>
    </div>
    <div id="resultsBody" class="results-body"></div>
  </div>

  <!-- Terminal -->
  <div class="terminal">
    <div class="term-header">
      <div class="term-title">
        <div class="term-dots">
          <div class="term-dot red"></div>
          <div class="term-dot yellow"></div>
          <div class="term-dot green"></div>
        </div>
        Activity Log
      </div>
      <button class="term-clear" onclick="clearTerm()">Clear</button>
    </div>
    <div id="termBody" class="term-body">Waiting for automation to start…</div>
  </div>

</div>

<!-- Toast container -->
<div class="toast-container" id="toastContainer"></div>

<script>
  let isRunning = false;
  let prevRunning = false;
  let needsVerify = false;

  /* ── Helpers ─────────────────────────────────────────── */
  function toast(msg, type = 'info', dur = 3500) {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    t.onclick = () => t.remove();
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateY(8px)'; t.style.transition = 'all 0.3s'; setTimeout(() => t.remove(), 320); }, dur);
  }

  function clearTerm() {
    document.getElementById('termBody').textContent = '';
  }

  function togglePwd() {
    const p = document.getElementById('pwdInput');
    p.type = p.type === 'password' ? 'text' : 'password';
  }

  /* ── Course rows ─────────────────────────────────────── */
  function addCourseRow(code = '', slot = '') {
    const list = document.getElementById('coursesList');
    if (!list) return;
    const idx  = list.children.length + 1;
    const div  = document.createElement('div');
    div.className = 'course-row';
    div.innerHTML = `
      <span class="course-row-num">${idx}</span>
      <input type="text" class="course-code" placeholder="Code (e.g. HU306)" value="${code}" spellcheck="false" autocomplete="off" />
      <div class="course-sep"></div>
      <input type="text" class="course-slot" placeholder="Slot (e.g. E1)" value="${slot}" spellcheck="false" autocomplete="off" style="max-width:120px" />
      <button class="btn-remove" type="button" title="Remove" onclick="removeCourse(this)">✕</button>
    `;

    const codeInp = div.querySelector('.course-code');
    const slotInp = div.querySelector('.course-slot');

    codeInp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        slotInp.focus();
      }
    });

    slotInp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        addCourseRow('', '');
      }
    });

    list.appendChild(div);
    renumberRows();

    if (!code) {
      codeInp.focus();
    }
  }

  function removeCourse(btn) {
    btn.parentElement.remove();
    renumberRows();
  }

  function renumberRows() {
    document.querySelectorAll('#coursesList .course-row').forEach((r, i) => {
      r.querySelector('.course-row-num').textContent = i + 1;
    });
  }

  function getCourses() {
    const rows = document.querySelectorAll('#coursesList .course-row');
    const out = [];
    rows.forEach(r => {
      const code = r.querySelector('.course-code').value.trim().toUpperCase();
      const slot = r.querySelector('.course-slot').value.trim().toUpperCase();
      if (code) out.push({ code, slot: slot || null });
    });
    return out;
  }

  /* ── Render helpers ─────────────────────────────────── */
  function renderMonitorGrid(courses, running) {
    const grid = document.getElementById('monitorGrid');
    grid.innerHTML = '';
    courses.forEach(c => {
      const isGrabbed   = c.status === 'GRABBED';
      const isSearching = running && !isGrabbed;
      const div = document.createElement('div');
      div.className = `monitor-card${isGrabbed ? ' grabbed' : isSearching ? ' searching' : ''}`;
      let pill;
      if (isGrabbed)        pill = '<span class="pill grabbed">✅ GRABBED</span>';
      else if (isSearching) pill = '<span class="pill searching">🔍 Searching…</span>';
      else                  pill = '<span class="pill idle">— Not grabbed</span>';
      div.innerHTML = `
        <div class="mc-left">
          <h4>${c.code}</h4>
          <span>Slot: ${c.slot || 'ANY'}</span>
        </div>
        ${pill}
      `;
      grid.appendChild(div);
    });
  }

  function renderResults(courses) {
    const banner = document.getElementById('resultsBanner');
    const body   = document.getElementById('resultsBody');
    let out = '══════════════════════════════════════════\n';
    out    += '  RESULTS\n';
    out    += '══════════════════════════════════════════\n';
    courses.forEach(c => {
      const st = c.status === 'GRABBED' ? '✅ GRABBED    ' : '❌ NOT GRABBED';
      out += `  ${st}  ${c.code.padEnd(8)} (slot: ${c.slot || 'ANY'})\n`;
    });
    out += '══════════════════════════════════════════';
    body.textContent = out;
    banner.classList.add('show');
  }

  function copyResults() {
    navigator.clipboard.writeText(document.getElementById('resultsBody').textContent);
    toast('Results copied!', 'success', 2500);
  }

  /* ── Load saved config ──────────────────────────────── */
  async function loadConfig() {
    try {
      const res  = await fetch('/api/config');
      const data = await res.json();
      document.getElementById('rollInput').value = data.roll || '';
      document.getElementById('pwdInput').value  = data.password || '';
      document.getElementById('coursesList').innerHTML = '';
      (data.courses || []).forEach(c => addCourseRow(c.code, c.slot || ''));
      renderMonitorGrid((data.courses || []).map(c => ({...c, status:'IDLE'})), false);
    } catch(e) {}
  }

  /* ── Start / Stop ───────────────────────────────────── */
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
  }

  async function stopAutomation() {
    document.getElementById('btnStop').disabled = true;
    await fetch('/api/stop', { method: 'POST' });
    toast('Stopping automation…', 'info');
  }

  /* ── Phase banner helper ────────────────────────────── */
  function setPhase(icon, msg) {
    document.getElementById('phaseIcon').textContent = icon;
    document.getElementById('phaseMsg').textContent  = msg;
  }

  /* ── Poll status ────────────────────────────────────── */
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

      /* Detect verification needed */
      const action = (data.status && data.status.action) ? data.status.action.toLowerCase() : '';
      const isVerify = action.includes('verify') || action.includes('action required') || action.includes('click');

      if (isVerify && running) {
        if (!needsVerify) { toast('⚠️ Please click the verification box in Chrome!', 'info', 8000); }
        needsVerify = true;
        verifyBanner.classList.add('show');
        pill.className = 'status-pill warning';
        dot.className  = 'dot pulse';
        pillTxt.textContent = 'Needs Verification';
      } else {
        needsVerify = false;
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

      /* Buttons */
      document.getElementById('btnStart').disabled = running;
      document.getElementById('btnStop').disabled  = !running;

      /* Phase banner */
      if (data.status && data.status.action) {
        const a = data.status.action;
        let icon = '⚡';
        if (a.includes('🔑') || a.toLowerCase().includes('log')) icon = '🔑';
        else if (a.includes('🎉') || a.toLowerCase().includes('grab')) icon = '🎉';
        else if (a.includes('🔍') || a.toLowerCase().includes('fetch') || a.toLowerCase().includes('scan')) icon = '🔍';
        else if (a.toLowerCase().includes('verif') || a.toLowerCase().includes('click')) icon = '🛡️';
        else if (a.toLowerCase().includes('stop')) icon = '🛑';
        else if (a.includes('🚀')) icon = '🚀';
        setPhase(icon, a.replace(/^[^a-zA-Z0-9]*/, ''));
      } else if (!running && !prevRunning) {
        setPhase('⚡', 'Ready — fill in your details below and hit Start Automation');
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

      /* Terminal logs */
      if (data.logs && data.logs.length > 0) {
        const term = document.getElementById('termBody');
        const atBottom = term.scrollTop + term.clientHeight >= term.scrollHeight - 40;

        // Colorize lines
        const colored = data.logs.map(line => {
          const e = document.createElement('span');
          if (line.includes('✅') || line.includes('GRABBED'))    e.className = 'log-grabbed';
          else if (line.includes('⚠️') || line.includes('🔔'))    e.className = 'log-warn';
          else if (line.includes('❌') || line.includes('FATAL')) e.className = 'log-error';
          else if (line.includes('🔑') || line.includes('🌐') || line.includes('🚀') || line.includes('ℹ️')) e.className = 'log-info';
          e.textContent = line;
          return e.outerHTML;
        }).join('\n');

        term.innerHTML = colored;
        if (atBottom) term.scrollTop = term.scrollHeight;
      }

    } catch(e) { /* network hiccup, ignore */ }
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
