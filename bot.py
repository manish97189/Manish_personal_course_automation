#!/usr/bin/env python3
"""
DTU Course Registration Bot
  • Logs in automatically
  • Monitors and grabs target courses
  • Handles Cloudflare verification (user clicks once, bot resumes)
  • Auto-recovers from crashes, timeouts, and logouts
"""

import json
import os
import signal
import sys
import time
from datetime import datetime

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
CURRENT_GRABBED: set = set()

load_dotenv(override=True)
ROLL_NUMBER = os.getenv("ROLL_NUMBER", "").strip()
PASSWORD = os.getenv("PASSWORD", "").strip()

if not ROLL_NUMBER or not PASSWORD:
    sys.exit("[FATAL] ROLL_NUMBER or PASSWORD missing from .env — aborting.")


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def write_status(running: bool, grabbed: set, action: str = "") -> None:
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
            courses_status.append({"code": c["code"], "slot": c["slot"], "status": st})

        data = {
            "running": running,
            "action": action,
            "grabbed_count": len(grabbed),
            "total_count": len(config.COURSES_TO_ADD),
            "courses": courses_status,
            "updated_at": ts(),
        }
        # Write atomically via temp file to avoid partial reads
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STATUS_FILE)
    except Exception:
        pass


# ── Security Challenge detection ────────────────────────────
def is_security_challenge(page) -> bool:
    try:
        title = (page.title() or "").lower()
        if "just a moment" in title:
            return True
        if page.locator("text=/performing security verification|verifying you are not a bot/i").count() > 0:
            return True
        if page.locator("#challenge-stage, #cf-challenge-running, .cf-turnstile-wrapper").count() > 0:
            return True
    except Exception:
        pass
    return False


def wait_for_challenge_to_pass(page) -> None:
    if not is_security_challenge(page):
        return

    try:
        page.bring_to_front()
    except Exception:
        pass

    write_status(True, CURRENT_GRABBED, "🔔 ACTION REQUIRED: Click 'Verify you are human' in the browser window")
    print(f"\n[{ts()}] 🔔 CLOUDFLARE CHECK — Switch to Chrome and click the checkbox!")
    print(f"[{ts()}] ⏳ Automation will resume automatically once verified…\n")

    last_notify = time.time()
    while is_security_challenge(page):
        page.wait_for_timeout(1000)
        if time.time() - last_notify >= 10:
            print(f"[{ts()}] ⏳ Still waiting… please click the 'Verify you are human' checkbox in Chrome.")
            last_notify = time.time()

    write_status(True, CURRENT_GRABBED, "🚀 Verified! Resuming course monitoring…")
    print(f"\n[{ts()}] ✅ Verified! Resuming automation…\n")
    page.wait_for_timeout(1000)


# ── Logout detection ────────────────────────────────────────
def is_logged_out(page) -> bool:
    if is_security_challenge(page):
        return False
    try:
        if "login" in page.url.lower():
            return True
        if page.locator('input[type="password"]').count() > 0:
            return True
        if page.locator("text=/session.*expired|please.*login/i").count() > 0:
            return True
    except Exception:
        return True
    return False


# ── Login ───────────────────────────────────────────────────
def login(page) -> bool:
    wait_for_challenge_to_pass(page)
    write_status(True, CURRENT_GRABBED, f"🔑 Logging in as {ROLL_NUMBER}…")
    print(f"[{ts()}] 🔑  Logging in as {ROLL_NUMBER}…")
    try:
        page.wait_for_selector('input[type="text"]', timeout=10000)
        page.locator('input[type="text"]').first.fill(ROLL_NUMBER)
        page.locator('input[type="password"]').first.fill(PASSWORD)

        try:
            checkbox = page.locator('input[type="checkbox"]').first
            if checkbox.is_visible(timeout=1500) and not checkbox.is_checked():
                checkbox.click()
        except Exception:
            pass

        page.locator('button:has-text("Sign in")').first.click()
        page.wait_for_timeout(2500)
        wait_for_challenge_to_pass(page)

        if "login" in page.url.lower():
            write_status(True, CURRENT_GRABBED, "⚠️ Login failed — check your roll number and password")
            print(f"[{ts()}] ⚠️  Still on login page — wrong credentials or captcha?")
            return False

        write_status(True, CURRENT_GRABBED, "✅ Logged in! Navigating to registration portal…")
        print(f"[{ts()}] ✅  Logged in successfully.")
        return True

    except Exception as exc:
        print(f"[{ts()}] ⚠️  Login error: {exc}")
        return False


# ── Navigation ──────────────────────────────────────────────
def ensure_register_page(page) -> None:
    if is_security_challenge(page):
        return
    url = page.url.lower()
    if "register" not in url and "login" not in url:
        write_status(True, CURRENT_GRABBED, "🌐 Navigating to registration portal…")
        print(f"[{ts()}] 🔄  Going to registration page…")
        try:
            page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(1500)
            wait_for_challenge_to_pass(page)
        except PwTimeout:
            print(f"[{ts()}] ⚠️  Registration page timed out — retrying.")


# ── Course grabber ──────────────────────────────────────────
def try_add_courses(page, grabbed: set) -> list:
    newly_grabbed = []
    write_status(
        True, CURRENT_GRABBED,
        f"🔍 Scanning courses ({len(CURRENT_GRABBED)}/{len(config.COURSES_TO_ADD)} secured)…"
    )

    for course in config.COURSES_TO_ADD:
        key = f"{course['slot']}:{course['code']}"
        if key in grabbed:
            continue

        try:
            row = page.locator("li", has_text=course["code"]).filter(
                has=page.locator('button:has-text("Add"):not([disabled])')
            )
            if row.count() > 0:
                btn = row.first.locator('button:has-text("Add")').first
                btn.click()
                grabbed.add(key)
                CURRENT_GRABBED.add(key)
                newly_grabbed.append(key)
                write_status(True, CURRENT_GRABBED, f"🎉 GRABBED {course['code']} (Slot: {course['slot']})!")
                print(f"[{ts()}] ✅  GRABBED ➜ {course['code']} (slot: {course['slot']})")
                page.wait_for_timeout(600)
        except Exception as exc:
            print(f"[{ts()}] ⚠️  Error checking {course['code']}: {exc}")

    return newly_grabbed


# ── Page recovery ───────────────────────────────────────────
def full_reload(page) -> None:
    print(f"[{ts()}] 🔄  Reloading page…")
    try:
        page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_timeout(2000)
    except PwTimeout:
        print(f"[{ts()}] ⚠️  Reload timed out — will keep retrying.")


# ── Main ────────────────────────────────────────────────────
def main():
    grabbed: set = set()
    total = len(config.COURSES_TO_ADD)
    login_failures = 0

    print("=" * 60)
    print("  DTU Course Registration Bot")
    print(f"  Roll: {ROLL_NUMBER}  |  Targeting {total} course(s)")
    for c in config.COURSES_TO_ADD:
        print(f"    • {c['code']}  (slot: {c['slot']})")
    print("=" * 60 + "\n")

    profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_data")
    is_attached_cdp = False

    with sync_playwright() as p:
        browser = None
        context = None
        page = None

        # Strategy 1: Attach to open Chrome via CDP
        if getattr(config, "ATTACH_TO_OPEN_CHROME", False):
            try:
                browser = p.chromium.connect_over_cdp(config.CDP_URL)
                context = browser.contexts[0]
                for pg in context.pages:
                    if "exam-setu" in pg.url.lower():
                        page = pg
                        print(f"[{ts()}] 🔗  Reusing existing DTU tab: {page.url}")
                        break
                if not page:
                    page = context.new_page()
                    page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
                is_attached_cdp = True
                print(f"[{ts()}] 🔗  Attached to your open Chrome!")
            except Exception:
                print(f"[{ts()}] ℹ️  Chrome on port 9222 not found — starting fresh profile…")

        # Strategy 2: Launch with persistent profile
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
                print(f"[{ts()}] ⚠️  Chrome not found, falling back to Chromium: {e}")
                browser = p.chromium.launch(
                    headless=config.HEADLESS,
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                )
                context = browser.new_context()
                page = context.new_page()

            print(f"[{ts()}] 🌐  Opening {config.REGISTER_URL}")
            try:
                page.goto(config.REGISTER_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)
            except PwTimeout:
                print(f"[{ts()}] ⚠️  Initial load timed out — will retry in loop.")

        print(f"[{ts()}] 🤖  Bot running … (Ctrl+C to stop)\n")
        write_status(True, grabbed, "🔍 Scanning for courses…")

        try:
            while len(grabbed) < total:
                try:
                    wait_for_challenge_to_pass(page)

                    if is_logged_out(page):
                        ok = login(page)
                        if not ok:
                            login_failures += 1
                            if login_failures >= config.MAX_LOGIN_RETRIES:
                                print(f"[{ts()}] 🔄  Too many login failures — reloading page.")
                                full_reload(page)
                                login_failures = 0
                            else:
                                time.sleep(config.LOGIN_RETRY_DELAY_SEC)
                            continue
                        login_failures = 0

                    ensure_register_page(page)
                    wait_for_challenge_to_pass(page)

                    newly = try_add_courses(page, grabbed)
                    if newly:
                        remaining = total - len(grabbed)
                        if remaining > 0:
                            print(f"[{ts()}] 📋  Progress: {len(grabbed)}/{total} — {remaining} remaining\n")

                    if not is_security_challenge(page):
                        try:
                            page.reload(timeout=config.PAGE_LOAD_TIMEOUT_MS)
                            page.wait_for_timeout(800)
                        except PwTimeout:
                            pass

                except PwTimeout:
                    print(f"[{ts()}] ⚠️  Timeout — reloading.")
                    full_reload(page)

                except Exception as exc:
                    print(f"[{ts()}] ❌  Error: {exc}")
                    time.sleep(2)
                    full_reload(page)

                time.sleep(config.POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            print(f"\n[{ts()}] 🛑  Stopped by user.")

        # ── Write final status ──
        write_status(False, grabbed, "Stopped")

        # ── Print summary ──
        print("\n" + "=" * 60)
        print("  RESULTS")
        print("=" * 60)
        for c in config.COURSES_TO_ADD:
            key = f"{c['slot']}:{c['code']}"
            status = "✅ GRABBED    " if key in grabbed else "❌ NOT GRABBED"
            print(f"    {status}  {c['code']}  (slot: {c['slot']})")
        print("=" * 60 + "\n")

        if grabbed:
            print(f"[{ts()}] 👀  Done! Review your selections in the browser and submit.")

        # ── Cleanup ──
        if is_attached_cdp:
            print(f"[{ts()}] ℹ️  Detached — your browser stays open.")
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
        print("\n[Bot] Exited.")
