/**
 * ARCHER browser client — LOGS tab: "what ARCHER is doing right now."
 *
 * Renders server.py's curated status feed (broadcast as
 * {"type": "log_line", "text": "HH:MM:SS | <emoji> <plain-English line>\n"},
 * see server.py's _register_status_line_bridge and CONTRACT.md) as one
 * discrete, colored entry per event instead of a raw monospace text dump
 * -- modeled on the step-by-step action feed Col pointed to (timestamped
 * one-liners like "Searched 10 websites" / "Applying a code patch" as
 * their own visually distinct rows, not buried in a log wall). Read-only,
 * newest at the bottom, auto-scrolls unless the user has scrolled up to
 * read back through history -- same Pause/Clear controls as before, plus
 * a "Working for Xm Ys" header while ARCHER is actively processing a
 * turn, matching that reference's running timer.
 */
(() => {
  const panel = document.getElementById("tab-logs");
  if (!panel) return;

  panel.innerHTML = `
    <div id="archer-logs-toolbar">
      <span id="archer-logs-label">Idle -- waiting for the wake word.</span>
      <button id="archer-logs-pause" type="button">Pause</button>
      <button id="archer-logs-clear" type="button">Clear</button>
    </div>
    <div id="archer-logs-view"></div>
  `;

  const view = document.getElementById("archer-logs-view");
  const pauseBtn = document.getElementById("archer-logs-pause");
  const clearBtn = document.getElementById("archer-logs-clear");
  const label = document.getElementById("archer-logs-label");

  let paused = false;
  let working = false;
  let workStartedAt = null;
  let timerHandle = null;

  // Only auto-scroll if the user hasn't deliberately scrolled up to read
  // back through history -- otherwise new entries would keep yanking them
  // back to the bottom.
  const NEAR_BOTTOM_PX = 40;
  function isNearBottom() {
    return view.scrollHeight - view.scrollTop - view.clientHeight < NEAR_BOTTOM_PX;
  }

  const MAX_ENTRIES = 1000; // cap so a long session doesn't grow the DOM forever

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // Each line arrives as "HH:MM:SS | <text>" -- split the timestamp out
  // so it can be dimmed while the message itself (emoji + plain English)
  // gets the accent treatment.
  const LINE_RE = /^(\d{2}:\d{2}:\d{2}) \| (.*)$/;

  function addEntry(line) {
    const m = LINE_RE.exec(line);
    const entry = document.createElement("div");
    entry.className = "log-entry";
    if (m) {
      entry.innerHTML =
        `<span class="log-ts">${escapeHtml(m[1])}</span>` +
        `<span class="log-msg">${escapeHtml(m[2])}</span>`;
    } else {
      entry.innerHTML = `<span class="log-msg">${escapeHtml(line)}</span>`;
    }
    view.appendChild(entry);
    while (view.childElementCount > MAX_ENTRIES) {
      view.removeChild(view.firstChild);
    }
  }

  function formatElapsed(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  function updateLabel() {
    if (paused) {
      label.textContent = "Paused.";
    } else if (working && workStartedAt) {
      label.textContent = `Working for ${formatElapsed(Date.now() - workStartedAt)}`;
    } else {
      label.textContent = "Idle -- waiting for the wake word.";
    }
  }

  pauseBtn.addEventListener("click", () => {
    paused = !paused;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
    updateLabel();
  });

  clearBtn.addEventListener("click", () => {
    view.innerHTML = "";
  });

  if (window.ArcherClient) {
    window.ArcherClient.on("logLine", (text) => {
      if (paused || !text) return;
      const stickToBottom = isNearBottom();
      for (const line of text.split("\n")) {
        if (line) addEntry(line);
      }
      if (stickToBottom) {
        view.scrollTop = view.scrollHeight;
      }
    });

    // Drive the "Working for Xm Ys" header off the same pipeline state
    // the orb uses -- listening/idle both read as "not working" so the
    // timer only runs while ARCHER is actually thinking or speaking.
    window.ArcherClient.on("state", (e) => {
      const state = typeof e === "string" ? e : e?.state;
      const isWorking = state === "processing" || state === "speaking";
      if (isWorking && !working) {
        working = true;
        workStartedAt = Date.now();
        if (!timerHandle) timerHandle = setInterval(updateLabel, 1000);
      } else if (!isWorking && working) {
        working = false;
        workStartedAt = null;
        if (timerHandle) {
          clearInterval(timerHandle);
          timerHandle = null;
        }
      }
      updateLabel();
    });
  }
})();
