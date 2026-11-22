# ── Target URLs ──────────────────────────────────────────────
LOGIN_URL = "https://exam-setu.dtu.ac.in/login/"
REGISTER_URL = "https://exam-setu.dtu.ac.in/register/"

# ── Courses to grab (order = priority) ──────────────────────
# Set slot to None to match any slot.
COURSES_TO_ADD = [
    {"code": "HU306", "slot": "E1"},
    {"code": "MOOC406", "slot": "MOOC"},
    {"code": "EP210", "slot": "E1"},
]

# ── Timing ──────────────────────────────────────────────────
POLL_INTERVAL_SEC = 0.5          # how often to check for courses
LOGIN_RETRY_DELAY_SEC = 3        # wait before retrying login after failure
MAX_LOGIN_RETRIES = 5            # consecutive login failures before full page reload
PAGE_LOAD_TIMEOUT_MS = 30000     # max wait for page navigation
HEADLESS = False                 # False = open visible browser tab so you can click the verification box

# ── Browser Connection Mode ─────────────────────────────────
# Set to True to attach directly to your existing open Chrome window:
# (Launch Chrome with: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222)
ATTACH_TO_OPEN_CHROME = False
CDP_URL = "http://localhost:9222"
