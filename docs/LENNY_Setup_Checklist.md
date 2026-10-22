# LENNY Setup Checklist (ARCHER's Desk)

This plain-language checklist guides you through setting up LENNY as ARCHER's dedicated desk machine (Spec Section 11).

> [!NOTE]
> **Why this setup exists:**
> Setting up LENNY gives ARCHER its own independent mouse, keyboard, screen, Office suite, and web browser. This allows ARCHER to work on tasks (e.g., generating Word documents, manipulating spreadsheets, browsing websites) without moving your mouse or interrupting what you are doing on your primary PC.

---

### Step 0: Prerequisite — Reserve Fixed IP Addresses in eero

The security architecture restricts network access to LENNY strictly to your Main PC. Reserving IP addresses in your eero router ensures these addresses never change when DHCP leases renew.

1. Open the **eero** app on your phone.
2. Go to **Settings** -> **Network Settings** -> **Reservations & Port Forwarding**.
3. Under **IP Reservations**, tap **Add a reservation**:
   - **Main PC:** Set to `192.168.4.41` (select your Main PC from the device list).
   - **LENNY:** Set to a permanent IP (e.g., `192.168.4.50` or whatever address eero assigned to LENNY).
4. Save the reservations.

---

### What to Prepare
- **The Machine:** LENNY (Windows 11 Pro, i5-10310U, 40GB RAM, Office installed).
- **Network:** Connected to your home network (wired ethernet is preferred for smooth ~30 FPS video streaming).
- **Account:** Your regular Windows login on LENNY (Office is already licensed and signed in under your account).

---

### Step-by-Step Instructions on LENNY

#### 1. Transfer the Setup Files to LENNY
Copy the following three files from your Main PC (`D:\ARCHER_9\`) to a folder or USB drive, and place them together on LENNY:
- `D:\ARCHER_9\scripts\lenny_setup.ps1`
- `D:\ARCHER_9\scripts\lenny\hands.py`
- `D:\ARCHER_9\scripts\lenny\requirements-lenny.txt`

#### 2. Open PowerShell as Administrator on LENNY
- On LENNY, click **Start**, type **PowerShell**.
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
- Sets up `C:\archer_lenny\` for tools, artifacts, and a dedicated browser profile.
- Installs pinned Python dependencies from `requirements-lenny.txt` and Playwright Chromium.
- Pre-creates **program-specific** Windows Firewall rules for `python.exe` (port 8203) and `chrome.exe` (port 9222) restricted solely to your Main PC (`192.168.4.41`). Because these are pre-configured with the exact application paths, Windows Defender Firewall will not prompt you for network permissions.
- Binds Hands and Chromium CDP strictly to LENNY's LAN address (not `0.0.0.0`).
- Registers a scheduled task (`ArcherHands`) so ARCHER's hands start automatically in your session at boot.

> [!WARNING]
> **Windows Firewall Pop-Up — Always Click CANCEL**
> If Windows Defender Firewall ever displays an "Allow access" pop-up for `python.exe` or `chrome.exe`, always click **Cancel** (never Allow). The script already created secure rules restricted strictly to your Main PC (`192.168.4.41`). Clicking Allow would create a wide-open rule exposing Hands and Chrome DevTools (which has no internal authentication) to your entire local network.

#### 4. Enable Autologon When Prompted
- The script automatically downloads official Microsoft Sysinternals Autologon and verifies its **Microsoft Authenticode digital signature** before running.
- In the Autologon dialog, enter your Windows login password and click **Enable**.
- *Note:* This ensures that if LENNY restarts or power cycles, ARCHER's desk automatically logs back in and restores itself without physical intervention. Insecure plaintext registry fallbacks are completely eliminated.

#### 5. Pair LENNY with ARCHER
- When the script finishes, ARCHER Hands starts and displays a **6-digit single-use pairing code** (e.g., `482910`).
- **Pairing Code Security:**
  - The code expires **15 minutes** after Hands starts.
  - The code is **single-use** (it is immediately invalidated as soon as pairing succeeds).
  - If 5 incorrect codes are entered, pairing is locked for **10 minutes**.
  - **Need a new code?** If the code expires or you need a fresh one, open PowerShell on LENNY and run:
    ```powershell
    python C:\archer_lenny\hands.py --new-code
    ```
    This immediately generates and displays a new 15-minute pairing code.
- Open ARCHER on your Main PC (`http://localhost:8200` or the ARCHER desktop app).
- Switch to the **LENNY** tab.
- Enter LENNY's IP address (from your eero reservation, e.g. `192.168.4.50`) and the **6-digit pairing code**, then click **Pair**.
- Once paired, ARCHER saves the persistent 32-byte auth bearer token. You never have to pair it again.

---

### That's It!
ARCHER now has its own private desk. You can watch ARCHER work in the **LENNY tab**, click into the stream to take over control at any time, or let ARCHER complete Office documents and web research in the background while you use your Main PC undisturbed.
