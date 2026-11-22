# 🎓 DTU Course Registration Automation

An automated tool with a visual web dashboard to grab DTU courses as soon as they become available on `exam-setu.dtu.ac.in`.

---

## ⚡ Quick Start Guide

No programming experience needed. All you need on your computer is **Python 3.9 or higher** (free from [python.org](https://www.python.org/downloads/)).

---

### 🪟 For Windows Users

#### Step 1: Download the Project
1. Click the green **Code** button at the top of the GitHub page.
2. Click **Download ZIP**.
3. Extract (unzip) the folder to your Desktop or Downloads.

#### Step 2: Open and Run
1. Open the extracted folder.
2. **Double-click `run.bat`**.
   *(Alternatively: Open Command Prompt inside the folder and type: `python start.py`)*

#### Step 3: That's It!
- The script automatically creates the environment, installs needed libraries, and opens the dashboard in your default browser at `http://localhost:8765`.

> ⚠️ **First time installing Python on Windows?**  
> Make sure to check the box **"Add Python to PATH"** at the bottom of the Python installer!

---

### 🍏 For macOS Users

#### Step 1: Download the Project
1. Click the green **Code** button on GitHub → **Download ZIP**, then extract it.  
   *(Or open Terminal and run `git clone <repo-url>`)*

#### Step 2: Run the Launcher
1. Open **Terminal**.
2. Drag and drop the folder into Terminal, or navigate to it:
   ```bash
   cd ~/Downloads/"course registration automation"
   ```
3. Run this command:
   ```bash
   ./run.sh
   ```
   *(or: `python3 start.py`)*

#### Step 3: That's It!
- Your browser will automatically pop open with the control dashboard at `http://localhost:8765`.

---

## 🖥️ How to Use the Dashboard

1. **Enter Your Details:**
   - **Roll Number:** e.g., `23/IT/94`
   - **Password:** Your DTU portal password
2. **Set Your Target Courses:**
   - Enter the **Course Code** (e.g., `HU306`) and **Slot** (e.g., `E1`).
   - Courses are grabbed in order from top to bottom (highest priority at the top).
   - Click **＋ Add Course** (or hit <kbd>Enter</kbd>) to add more courses.
3. **Start the Automation:**
   - Click **🚀 Start Automation**.
   - A Chrome browser window will open.
   - When Cloudflare shows a **"Verify you are human"** checkbox, the dashboard will flash an alert. Switch to the Chrome window and click the checkbox.
   - As soon as verified, the bot will automatically resume and monitor course availability!
4. **Stopping:**
   - Click **⏹️ Stop** anytime to pause or quit.

---

## ❓ Frequently Asked Questions (Troubleshooting)

**Q: 'python' is not recognized on Windows?**  
**A:** Reinstall Python from [python.org](https://www.python.org/downloads/) and make sure to check the box **"Add Python to PATH"** during installation.

**Q: Permission denied when running `./run.sh` on Mac?**  
**A:** Run `chmod +x run.sh` once in your terminal, then try `./run.sh` again, or simply run `python3 start.py`.

**Q: Are my password and roll number safe?**  
**A:** Yes. Your credentials stay strictly on your local machine in `.env` and are never shared or uploaded anywhere.
