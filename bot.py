#!/usr/bin/env python3
"""
Course Registration Bot — optimised for reliability.
  • Auto-detects logout and re-logs in
  • Skips already-grabbed courses
  • Prints timestamped terminal notifications for every grab
  • Recovers from page crashes, network blips, stale elements
  • Runs until every course in config.COURSES_TO_ADD is grabbed
"""

import os
import signal
import sys
import time
from datetime import datetime

# Clean termination handler for both Ctrl+C and Web Dashboard Stop
def handle_shutdown(signum, frame):
    raise KeyboardInterrupt

try:
    signal.signal(signal.SIGTERM, handle_shutdown)
except Exception:
    pass

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

import config

STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")
CURRENT_GRABBED = set()

# ── Load credentials ────────────────────────────────────────
load_dotenv()
ROLL_NUMBER = os.getenv("ROLL_NUMBER")
PASSWORD = os.getenv("PASSWORD")

if not ROLL_NUMBER or not PASSWORD:
    sys.exit("[FATAL] ROLL_NUMBER or PASSWORD missing from .env — aborting.")


def ts():
    """Short timestamp for terminal logs."""
    return datetime.now().strftime("%H:%M:%S")


def write_status(running, grabbed, action=""):
    """Write current status to status.json so dashboard can display it in real time."""
    try:
        courses_status = []
        for c in config.COURSES_TO_ADD:
            key = f"{c['slot']}:{c['code']}"
            if key in grabbed:
                st = "GRABBED"
            elif running:
                st = "SEARCHING"
            else:
                st = "NOT_GRABBED"
            courses_status.append({
                "code": c["code"],
                "slot": c["slot"],
                "status": st
            })
        data = {
            "running": running,
            "action": action,
            "grabbed_count": len(grabbed),
            "total_count": len(config.COURSES_TO_ADD),
            "courses": courses_status,
            "updated_at": ts()
        }
        with open(STATUS_FILE, "w") as f:
            import json
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ── Login ───────────────────────────────────────────────────
def login(page):
    """Fill the login form and submit. Returns True on success."""
    wait_for_challenge_to_pass(page)
    write_status(True, CURRENT_GRABBED, f"🔑 Logging in as {ROLL_NUMBER}...")
    print(f"[{ts()}] 🔑  Logging in as {ROLL_NUMBER} ...")
    try:
        page.wait_for_selector('input[type="text"]', timeout=10000)
        page.locator('input[type="text"]').first.fill(ROLL_NUMBER)
        page.locator('input[type="password"]').first.fill(PASSWORD)

        checkbox = page.locator('input[type="checkbox"]').first
        if checkbox.is_visible(timeout=2000) and not checkbox.is_checked():
            checkbox.click()

        page.locator('button:has-text("Sign in")').first.click()
        page.wait_for_timeout(2000)
        wait_for_challenge_to_pass(page)

        # Check if we're still on login (bad credentials / captcha)
        if "login" in page.url.lower():
            write_status(True, CURRENT_GRABBED, "⚠️ Login unsuccessful — checking credentials or captcha...")
            print(f"[{ts()}] ⚠️  Still on login page — credentials may be wrong or captcha required.")
            return False

        write_status(True, CURRENT_GRABBED, "✅ Logged in successfully! Navigating to registration...")
        print(f"[{ts()}] ✅  Logged in successfully.")
        return True

    except (PwTimeout, Exception) as exc:
        print(f"[{ts()}] ⚠️  Login error: {exc}")
        return False


# ── Navigate to registration page ──────────────────────────
def ensure_register_page(page):
    """Navigate to the registration URL if we aren't already there."""
    if is_security_challenge(page):
        return
    url = page.url.lower()
    if "register" not in url and "login" not in url:
        write_status(True, CURRENT_GRABBED, "🌐 Opening registration portal...")
        print(f"[{ts()}] 🔄  Navigating to registration page ...")
        try:
            page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(1500)
            wait_for_challenge_to_pass(page)
        except PwTimeout:
            print(f"[{ts()}] ⚠️  Registration page load timed out — will retry.")


# ── Course grabber ──────────────────────────────────────────
def try_add_courses(page, grabbed):
    """
    Scan the page for each target course.  Click 'Add' if available.
    Returns newly-grabbed course keys.
    """
    newly_grabbed = []
    write_status(True, CURRENT_GRABBED, f"🔍 Fetching & monitoring course availability ({len(CURRENT_GRABBED)}/{len(config.COURSES_TO_ADD)} secured)...")

    for course in config.COURSES_TO_ADD:
        key = f"{course['slot']}:{course['code']}"
        if key in grabbed:
            continue

        try:
            # Find list items matching the course code with an enabled Add btn
            row = page.locator("li", has_text=course["code"]).filter(
                has=page.locator('button:has-text("Add"):not([disabled])')
            )

            if row.count() > 0:
                btn = row.first.locator('button:has-text("Add")').first
                btn.click()
                grabbed.add(key)
                CURRENT_GRABBED.add(key)
                newly_grabbed.append(key)
                write_status(True, CURRENT_GRABBED, f"🎉 GRABBED {course['code']} ({course['slot']})!")
                print(
                    f"[{ts()}] ✅  GRABBED  ➜  {course['code']}  "
                    f"(slot: {course['slot']})  — will NOT look at this course again."
                )
                # Small pause so the page can process the click
                page.wait_for_timeout(500)

        except Exception as exc:
            print(f"[{ts()}] ⚠️  Error checking {course['code']}: {exc}")

    return newly_grabbed


# ── Security Challenge (Cloudflare / Turnstile) Detection ────
def is_security_challenge(page):
    """Detect if Cloudflare anti-bot verification page is currently displayed."""
    try:
        title = (page.title() or "").lower()
        if "just a moment" in title:
            return True
        if page.locator('text=/performing security verification|verifying you are not a bot/i').count() > 0:
            return True
        if page.locator('#challenge-stage, #cf-challenge-running, .cf-turnstile-wrapper').count() > 0:
            return True
    except Exception:
        pass
    return False


def wait_for_challenge_to_pass(page):
    """Wait while security verification is in progress without reloading or interrupting."""
    if not is_security_challenge(page):
        return

    # Focus and bring browser tab to the front
    try:
        page.bring_to_front()
    except Exception:
        pass

    write_status(True, CURRENT_GRABBED, "🔔 Action Required: Click 'Verify you are human' box in open browser tab")

    # Bring the browser window to front so user can see it
    try:
        page.bring_to_front()
    except Exception:
        pass

    # Sound terminal alert bell
    print("\a", end="", flush=True)
    print(f"\n[{ts()}] 🔔 ACTION REQUIRED: Cloudflare verification detected!")
    print(f"[{ts()}] 👆 Switch to Chrome → Click the 'Verify you are human' checkbox")
    print(f"[{ts()}] ⏳ Automation will resume automatically once verified…\n")

    last_notify = time.time()
    while is_security_challenge(page):
        page.wait_for_timeout(1000)
        if time.time() - last_notify >= 10:
            print("\a", end="", flush=True)
            print(f"[{ts()}] ⏳ Still waiting for verification… please click the checkbox in Chrome.")
            last_notify = time.time()

    write_status(True, CURRENT_GRABBED, "🚀 Automation started! Intezaar kro mitrr — fetching & monitoring courses...")
    print(f"\n[{ts()}] ✅ Verification cleared!")
    print(f"[{ts()}] 🚀 Automation started! Intezaar kro mitrr (इंतज़ार करो मित्र) — monitoring & grabbing courses...\n")
    page.wait_for_timeout(1500)


# ── Health check: detect logout / unexpected page ───────────
def is_logged_out(page):
    """Return True if the page looks like a login screen or session expired."""
    if is_security_challenge(page):
        return False
    try:
        url = page.url.lower()
        if "login" in url:
            return True
        # Check for login inputs or session-expired banner
        if page.locator('input[type="password"]').count() > 0:
            return True
        if page.locator('text=/session.*expired|please.*login/i').count() > 0:
            return True
    except Exception:
        return True
    return False


# ── Full page recovery ──────────────────────────────────────
def full_reload(page):
    """Hard-reload the registration URL (clears JS state)."""
    print(f"[{ts()}] 🔄  Full page reload ...")
    try:
        page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_timeout(2000)
    except PwTimeout:
        print(f"[{ts()}] ⚠️  Reload timed out — will keep trying.")


# ── Main loop ──────────────────────────────────────────────
def main():
    grabbed = set()
    total = len(config.COURSES_TO_ADD)
    login_failures = 0

    print("=" * 60)
    print(f"  Course Registration Bot")
    print(f"  Target courses: {total}")
    for c in config.COURSES_TO_ADD:
        print(f"    • {c['code']}  (slot: {c['slot']})")
    print(f"  Poll interval : {config.POLL_INTERVAL_SEC}s")
    print("=" * 60)

    is_attached_cdp = False
    profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_data")

    with sync_playwright() as p:
        browser = None
        context = None
        page = None

        # ── Strategy 1: Attach to user's running Chrome if available ──
        if getattr(config, "ATTACH_TO_OPEN_CHROME", False):
            try:
                browser = p.chromium.connect_over_cdp(config.CDP_URL)
                context = browser.contexts[0]
                # Look for an existing tab with exam-setu
                for p_item in context.pages:
                    if "exam-setu" in p_item.url.lower():
                        page = p_item
                        print(f"[{ts()}] 🔗  Found existing DTU tab: {page.url}")
                        break
                if not page:
                    page = context.new_page()
                    page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
                is_attached_cdp = True
                print(f"[{ts()}] 🔗  Attached to your active Google Chrome!")
            except Exception:
                print(f"[{ts()}] ℹ️  Chrome on port 9222 not running. Starting persistent Chrome profile...")

        # ── Strategy 2: Launch Real Chrome with Persistent Profile & Anti-Detection ──
        if not page:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    channel="chrome",
                    headless=config.HEADLESS,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
                page = context.pages[0] if context.pages else context.new_page()
            except Exception as e:
                print(f"[{ts()}] ⚠️  Falling back to standard Chromium: {e}")
                browser = p.chromium.launch(
                    headless=config.HEADLESS,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                )
                context = browser.new_context()
                page = context.new_page()

            # Initial navigation
            print(f"[{ts()}] 🌐  Opening {config.REGISTER_URL}")
            try:
                page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
            except PwTimeout:
                print(f"[{ts()}] ⚠️  Initial load timed out — will retry in loop.")

        print(f"[{ts()}] 🤖  Bot running … press Ctrl+C to stop.\n")
        write_status(True, grabbed, "Scanning for courses...")

        try:
            while len(grabbed) < total:
                try:
                    # ── Step 0: Wait if Cloudflare / security verification is showing ──
                    wait_for_challenge_to_pass(page)

                    # ── Step 1: If logged out, log back in ──
                    if is_logged_out(page):
                        ok = login(page)
                        if not ok:
                            login_failures += 1
                            if login_failures >= config.MAX_LOGIN_RETRIES:
                                print(f"[{ts()}] 🔄  Too many login failures — doing full reload.")
                                full_reload(page)
                                login_failures = 0
                            else:
                                time.sleep(config.LOGIN_RETRY_DELAY_SEC)
                            continue
                        login_failures = 0

                    # ── Step 2: Make sure we're on the register page ──
                    ensure_register_page(page)
                    wait_for_challenge_to_pass(page)

                    # ── Step 3: Try to grab courses ──
                    newly = try_add_courses(page, grabbed)

                    if newly:
                        remaining = total - len(grabbed)
                        if remaining > 0:
                            print(f"[{ts()}] 📋  {len(grabbed)}/{total} done — {remaining} remaining.\n")

                    # ── Step 4: Refresh the page to get latest availability ──
                    if not is_security_challenge(page):
                        page.reload(timeout=config.PAGE_LOAD_TIMEOUT_MS)
                        page.wait_for_timeout(800)

                except PwTimeout:
                    print(f"[{ts()}] ⚠️  Page operation timed out — reloading.")
                    full_reload(page)

                except Exception as exc:
                    print(f"[{ts()}] ❌  Unexpected error: {exc}")
                    print(f"[{ts()}] 🔄  Attempting recovery ...")
                    time.sleep(2)
                    full_reload(page)

                time.sleep(config.POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            print(f"\n[{ts()}] 🛑  Stopped by user (Ctrl+C).")

        write_status(False, grabbed, "Stopped")

        # ── Summary ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("  RESULTS")
        print("=" * 60)
        for c in config.COURSES_TO_ADD:
            key = f"{c['slot']}:{c['code']}"
            status = "✅ GRABBED" if key in grabbed else "❌ NOT GRABBED"
            print(f"    {status}  —  {c['code']}  (slot: {c['slot']})")
        print("=" * 60)

        if grabbed:
            print(f"\n[{ts()}] 👀  All courses selected! Review & submit in the browser.")
            print(f"[{ts()}] ℹ️  Press Enter or Ctrl+C to close and exit.")
            if sys.stdin.isatty():
                try:
                    input()
                except (KeyboardInterrupt, EOFError):
                    print()
            else:
                # When running inside the web UI (app.py) or non-interactive shell
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass

        if is_attached_cdp:
            print(f"[{ts()}] ℹ️  Detached from Chrome (your browser stays open).")
        else:
            try:
                if context:
                    context.close()
                if browser:
                    browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Bot] Exited cleanly.")
