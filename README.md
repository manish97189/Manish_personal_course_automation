# DTU Course Registration Automation

An automated tool with a visual web dashboard to grab DTU courses as soon as they become available on `exam-setu.dtu.ac.in`.

---

## 🚀 Quick Start (For Anyone)

No programming knowledge or IDE required! Just make sure **Python 3.9+** is installed on your computer.

### 1. Download or Clone the Repository
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd "course registration automation"
```
*(Or simply download the ZIP from GitHub and extract it).*

### 2. Run the One-Click Launcher

- **macOS / Linux:**
  Open Terminal in the project folder and run:
  ```bash
  ./run.sh
  # or
  python3 start.py
  ```

- **Windows:**
  Double-click `run.bat` or run in Command Prompt:
  ```cmd
  python start.py
  ```

> 💡 **What this does automatically:**
> 1. Sets up an isolated local environment (`venv`).
> 2. Installs required libraries (`playwright`, `python-dotenv`).
> 3. Installs the browser driver.
> 4. Launches the dashboard at `http://localhost:8765` and opens it in your default browser.

---

## 🖥️ How to Use the Dashboard

1. **Enter Your Credentials:**
   - Type your **Student Roll Number** (e.g. `23/IT/94`).
   - Type your **Password**.
2. **Add Courses:**
   - Enter Course Code (e.g. `HU306`) and Slot (e.g. `E1`).
   - Put your most-wanted courses at the top (top = highest priority).
   - Use the **＋ Add Course** button to add more.
3. **Click 🚀 Start Automation:**
   - The bot starts monitoring the registration portal.
   - When Cloudflare shows a "Verify you are human" checkbox, switch to the Chrome browser window and click it once.
   - The bot will automatically resume and grab your courses in real time.
4. **Click ⏹️ Stop** anytime to finish.

---

## 🔒 Privacy & Security

Your Roll Number and Password are saved only on your local machine in `.env`. They are never sent to external servers or logged in Git.

