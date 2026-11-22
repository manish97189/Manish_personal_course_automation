#!/usr/bin/env python3
"""
One-command setup and launcher for DTU Course Registration Bot.
Run with:
    python3 start.py
(or `python start.py` on Windows)

This script automatically:
  1. Creates a local virtual environment (.venv) if not present.
  2. Installs required dependencies (playwright, python-dotenv).
  3. Installs Playwright Chromium browser if needed.
  4. Launches the interactive Web Dashboard at http://localhost:8765.
"""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(BASE_DIR, "venv")
IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    VENV_PYTHON = os.path.join(VENV_DIR, "Scripts", "python.exe")
    VENV_PIP = os.path.join(VENV_DIR, "Scripts", "pip.exe")
else:
    VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")
    VENV_PIP = os.path.join(VENV_DIR, "bin", "pip")


def run(cmd, desc=""):
    if desc:
        print(f"👉 {desc}...")
    res = subprocess.run(cmd, cwd=BASE_DIR)
    if res.returncode != 0:
        print(f"\n❌ Step failed: {' '.join(cmd)}")
        sys.exit(res.returncode)


def main():
    print("=" * 60)
    print("  🚀 DTU Course Registration Automation Launcher")
    print("=" * 60)

    # 1. Create virtual environment if missing
    if not os.path.exists(VENV_PYTHON):
        run([sys.executable, "-m", "venv", VENV_DIR], "Creating local Python virtual environment")

    # 2. Check and install dependencies
    print("👉 Checking dependencies...")
    check = subprocess.run(
        [VENV_PYTHON, "-c", "import playwright, dotenv"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode != 0:
        req_file = os.path.join(BASE_DIR, "requirements.txt")
        run([VENV_PIP, "install", "-r", req_file], "Installing required Python packages")
        run([VENV_PYTHON, "-m", "playwright", "install", "chromium"], "Installing Chromium browser")

    # 3. Ensure .env exists so bot doesn't crash on start
    env_file = os.path.join(BASE_DIR, ".env")
    env_example = os.path.join(BASE_DIR, ".env.example")
    if not os.path.exists(env_file) and os.path.exists(env_example):
        with open(env_example, "r") as src, open(env_file, "w") as dst:
            dst.write(src.read())

    # 4. Launch web app
    app_script = os.path.join(BASE_DIR, "app.py")
    print("\n✅ Ready! Launching dashboard...\n")
    try:
        subprocess.run([VENV_PYTHON, app_script], cwd=BASE_DIR)
    except KeyboardInterrupt:
        print("\n[Launcher] Closed.")


if __name__ == "__main__":
    main()

