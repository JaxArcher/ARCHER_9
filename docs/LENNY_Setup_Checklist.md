# LENNY Setup Checklist (ARCHER's Desk)

This plain-language checklist guides you through setting up LENNY as ARCHER's dedicated desk machine (Spec Section 11).

> [!NOTE]
> **Why this setup exists:**
> Setting up LENNY gives ARCHER its own independent mouse, keyboard, screen, Office suite, and web browser. This allows ARCHER to work on tasks (e.g., generating Word documents, manipulating spreadsheets, browsing websites) without moving your mouse or interrupting what you are doing on your primary PC.

---

### What to Prepare
- **The Machine:** LENNY (Windows 11 Pro, i5-10310U, 40GB RAM, Office installed).
- **Network:** Connected to your home network (wired ethernet is preferred for smooth ~30 FPS video streaming).
- **Account:** Your regular Windows login on LENNY (Office is already licensed and signed in under your account).

---

### Step-by-Step Instructions on LENNY

#### 1. Transfer the Setup Files to LENNY
Copy the following two files from your Main PC (`D:\ARCHER_9\`) to a temporary folder or USB drive, and place them on LENNY:
- `D:\ARCHER_9\scripts\lenny_setup.ps1`
- `D:\ARCHER_9\scripts\lenny\hands.py` (place this in the same folder as `lenny_setup.ps1`)

#### 2. Open PowerShell as Administrator on LENNY
- On LENNY, click **Start**, search for **PowerShell**.
- Right-click **Windows PowerShell** and choose **Run as Administrator**.
- Navigate to the folder where you placed the setup files:
  ```powershell
  cd C:\path\to\copied\files
  ```

#### 3. Run the Setup Script
Run the script:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\lenny_setup.ps1 -MainPcIp 192.168.4.41
```

*What the script does automatically:*
- Disables sleep, screen timeout, hibernation, and lid-close sleep so LENNY stays awake.
- Sets up `C:\archer_lenny\` for tools, artifacts, and a clean browser profile.
- Installs necessary Python packages and Playwright Chromium.
- Restricts Windows Firewall inbound access on ports **8203** (Hands) and **9222** (Browser CDP) strictly to your Main PC (`192.168.4.41`).
- Registers a scheduled task (`ArcherHands`) so ARCHER's hands start automatically in your session at boot.

#### 4. Enable Autologon When Prompted
- The official Microsoft Sysinternals Autologon dialog will open.
- Enter your Windows login password and click **Enable**.
- *Note:* This ensures that if LENNY is restarted or power cycles, ARCHER's desk automatically logs back in and restores itself without needing physical intervention.

#### 5. Pair LENNY with ARCHER
- When the script finishes, ARCHER Hands starts and displays a **6-digit pairing code** (e.g., `482910`).
- Open ARCHER on your Main PC (`http://localhost:8200` or the ARCHER desktop app).
- Switch to the **LENNY** tab.
- Enter LENNY's IP address and the **6-digit pairing code**, then click **Pair**.
- Once paired, ARCHER saves the persistent auth token. You never have to pair it again.

---

### That's It!
ARCHER now has its own private desk. You can watch ARCHER work in the **LENNY tab**, click into the stream to take over control at any time, or let ARCHER complete Office documents and web research in the background while you use your Main PC undisturbed.
