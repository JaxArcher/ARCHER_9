/**
 * ARCHER browser client — LOGS tab (Spec Section 5e, Col 2026-10-21).
 *
 * Implements:
 * 1. Status Board (top): 8 cards tracking live state, time in state, and failure reasons:
 *    - Voice: listening, hearing you, thinking, speaking, paused, muted. Mic & speaker devices.
 *    - Brain: idle or answering, primary model, last reply timing (first words, total).
 *    - Startup: startup steps and timing breakdown.
 *    - Observer service: running or stopped (turns red within seconds if heartbeat fails),
 *      room listening state, people in view (count only, never names), item watcher state.
 *    - Virtual phone: stopped, startup step (launching, booting, connecting), online (-gpu host), or error.
 *    - ARCHER's browser: closed or open with current page title.
 *    - Tools: currently running tool and last result.
 *    - Background jobs: Ollama residency, Redis, ChromaDB, nightly maintenance.
 *
 * 2. Controls Bar:
 *    - Category filter pills: All, Voice, Brain, Tools, Observer, Phone, Browser, System.
 *    - "Errors only" checkbox.
 *    - Search input.
 *    - Actions: Pause/Resume, Clear, "Working for" timer, and Technical Log toggle.
 *
 * 3. Activity Feed:
 *    - Plain-English discrete event feed from all subsystems (last 1,000 entries preserved).
 *    - Category badges, severity styling, and expandable "Details" toggles for errors & warnings.
 *    - Strict privacy rule (Spec 5c): Room transcripts and overheard words NEVER appear.
 *
 * 4. Technical Log Stream:
 *    - Live tail of logs/archer_*.log at INFO and above (skipping /api/ polling noise).
 */
(() => {
  const panel = document.getElementById("tab-logs");
  if (!panel) return;

  panel.innerHTML = `
    <!-- 1. Status Board -->
    <div id="archer-status-board">
      <div class="status-board-title">
        <span>ARCHER Status Board &bull; Live System Health</span>
        <span id="status-board-refresh-time" style="opacity:0.6; font-size:10px; font-weight:normal;">Live</span>
      </div>
      <div class="status-board-grid" id="status-board-grid">
        <!-- 8 Cards injected by renderStatusBoard() -->
      </div>
    </div>

    <!-- 2. Controls Bar -->
    <div id="archer-logs-controls">
      <div class="logs-filter-group">
        <button type="button" class="logs-pill-btn active" data-part="all">All</button>
        <button type="button" class="logs-pill-btn" data-part="voice">Voice</button>
        <button type="button" class="logs-pill-btn" data-part="brain">Brain</button>
        <button type="button" class="logs-pill-btn" data-part="tools">Tools</button>
        <button type="button" class="logs-pill-btn" data-part="observer">Observer</button>
        <button type="button" class="logs-pill-btn" data-part="phone">Phone</button>
        <button type="button" class="logs-pill-btn" data-part="browser">Browser</button>
        <button type="button" class="logs-pill-btn" data-part="system">System</button>
        <label class="logs-error-label">
          <input type="checkbox" id="logs-filter-errors"> Errors only
        </label>
      </div>

      <input type="text" id="logs-search-input" class="logs-search-input" placeholder="Search logs...">

      <div class="logs-actions-group">
        <span id="archer-logs-label" class="logs-label" style="font-size:11px; color:rgba(201,246,255,0.7); margin-right:4px;">Idle -- waiting for the wake word.</span>
        <button id="archer-logs-pause" class="logs-btn" type="button">Pause</button>
        <button id="archer-logs-clear" class="logs-btn" type="button">Clear</button>
        <button id="archer-logs-tech" class="logs-btn" type="button">Technical Log</button>
        <button id="archer-logs-changelog" class="logs-btn" type="button">Change Log</button>
      </div>
    </div>

    <!-- 3. Activity Feed -->
    <div id="archer-logs-view"></div>

    <!-- 4. Technical Log View -->
    <div id="archer-technical-log-view" style="display:none;"></div>

    <!-- 5. Change Log View (Spec Section 6) -->
    <div id="archer-change-log-view" style="display:none;">
      <div class="change-log-header">
        <div class="change-log-title">Change Log &bull; History of all system modifications</div>
        <div class="change-log-filter">
          <label for="change-log-date-filter">Filter date:</label>
          <input type="date" id="change-log-date-filter" class="change-log-date-input" />
          <button type="button" id="change-log-refresh-btn" class="logs-btn">Filter</button>
          <button type="button" id="change-log-clear-filter-btn" class="logs-btn">All</button>
        </div>
      </div>
      <div class="change-log-table-wrap">
        <table class="change-log-table">
          <thead>
            <tr>
              <th style="width:140px;">Timestamp</th>
              <th style="width:280px;">What Changed</th>
              <th style="width:140px;">Prompted By</th>
              <th style="width:130px;">Status</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody id="change-log-tbody">
            <tr><td colspan="5" style="text-align:center; opacity:0.6; padding:20px;">No change log records yet.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  const statusGrid = document.getElementById("status-board-grid");
  const activityView = document.getElementById("archer-logs-view");
  const techLogView = document.getElementById("archer-technical-log-view");
  const changeLogView = document.getElementById("archer-change-log-view");
  const changeLogTbody = document.getElementById("change-log-tbody");
  const changeLogDateInput = document.getElementById("change-log-date-filter");
  const changeLogRefreshBtn = document.getElementById("change-log-refresh-btn");
  const changeLogClearBtn = document.getElementById("change-log-clear-filter-btn");
  const pauseBtn = document.getElementById("archer-logs-pause");
  const clearBtn = document.getElementById("archer-logs-clear");
  const techBtn = document.getElementById("archer-logs-tech");
  const changelogBtn = document.getElementById("archer-logs-changelog");
  const searchInput = document.getElementById("logs-search-input");
  const errorsOnlyCheckbox = document.getElementById("logs-filter-errors");
  const statusLabel = document.getElementById("archer-logs-label");
  const pillBtns = panel.querySelectorAll(".logs-pill-btn");

  let paused = false;
  let isWorking = false;
  let workStartedAt = null;
  let workTimerHandle = null;
  let isTechLogActive = false;
  let isChangeLogActive = false;
  let activePartFilter = "all";
  let activeSearchTerm = "";
  let activeErrorsOnly = false;

  const MAX_ENTRIES = 1000;
  const allEntries = []; // ring buffer of structured entries

  // 8 canonical parts
  const BOARD_PARTS = [
    { key: "voice", name: "Voice" },
    { key: "brain", name: "Brain" },
    { key: "startup", name: "Startup" },
    { key: "observer", name: "Observer service" },
    { key: "phone", name: "Virtual phone" },
    { key: "browser", name: "ARCHER's browser" },
    { key: "tools", name: "Tools" },
    { key: "jobs", name: "Background jobs" },
  ];

  let boardData = {};

  function escapeHtml(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function formatDuration(sec) {
    if (sec == null || isNaN(sec) || sec < 0) return "0s";
    const total = Math.floor(sec);
    if (total < 60) return `${total}s`;
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    if (mins < 60) return `${mins}m ${secs}s`;
    const hrs = Math.floor(mins / 60);
    const remMins = mins % 60;
    return `${hrs}h ${remMins}m`;
  }

  function formatElapsedMs(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  // --- 1. Status Board Rendering ---
  function renderStatusBoard() {
    if (!statusGrid) return;
    const now = Date.now() / 1000;
    let html = "";

    for (const part of BOARD_PARTS) {
      const card = boardData[part.key] || {
        name: part.name,
        state: "Idle",
        dot: "gray",
        desc: "Waiting for status...",
        since: now,
        is_error: false,
      };

      const dotClass = `dot-${card.dot || "gray"}`;
      const isError = !!card.is_error || card.dot === "red";
      const cardClass = `board-card ${isError ? "card-error" : ""}`;
      const elapsedSec = card.since ? Math.max(0, now - card.since) : 0;
      const timeStr = formatDuration(elapsedSec);

      html += `
        <div class="${cardClass}" id="card-part-${part.key}">
          <div class="board-card-dot ${dotClass}"></div>
          <div class="board-card-info">
            <div class="board-card-header">
              <span class="board-card-name">${escapeHtml(card.name || part.name)}</span>
              <span class="board-card-time" title="Time in current state">${escapeHtml(timeStr)}</span>
            </div>
            <div class="board-card-desc" title="${escapeHtml(card.desc || card.state)}">${escapeHtml(card.desc || card.state)}</div>
          </div>
        </div>
      `;
    }

    statusGrid.innerHTML = html;
  }

  // Update card timers every second
  setInterval(() => {
    if (!statusGrid || document.hidden) return;
    const now = Date.now() / 1000;
    for (const part of BOARD_PARTS) {
      const cardEl = document.getElementById(`card-part-${part.key}`);
      const data = boardData[part.key];
      if (cardEl && data && data.since) {
        const timeEl = cardEl.querySelector(".board-card-time");
        if (timeEl) {
          timeEl.textContent = formatDuration(Math.max(0, now - data.since));
        }
      }
    }
  }, 1000);

  // --- 2. Activity Feed Rendering ---
  const NEAR_BOTTOM_PX = 50;
  function isNearBottom() {
    return activityView.scrollHeight - activityView.scrollTop - activityView.clientHeight < NEAR_BOTTOM_PX;
  }

  function matchesFilter(entry) {
    if (activeErrorsOnly && entry.level !== "error") {
      return false;
    }
    if (activePartFilter !== "all") {
      const entryPart = (entry.part || "").toLowerCase();
      if (entryPart !== activePartFilter) {
        return false;
      }
    }
    if (activeSearchTerm) {
      const q = activeSearchTerm.toLowerCase();
      const textMatch = (entry.text || "").toLowerCase().includes(q);
      const partMatch = (entry.part || "").toLowerCase().includes(q);
      const detailsMatch = (entry.details || "").toLowerCase().includes(q);
      const tsMatch = (entry.timestamp || "").toLowerCase().includes(q);
      if (!textMatch && !partMatch && !detailsMatch && !tsMatch) {
        return false;
      }
    }
    return true;
  }

  function createEntryNode(entry) {
    const row = document.createElement("div");
    const levelClass = entry.level === "error" ? "level-error" : (entry.level === "warning" ? "level-warning" : "");
    row.className = `log-entry-row ${levelClass}`;
    row.dataset.id = entry.id;

    const partClass = `part-${(entry.part || "system").toLowerCase()}`;
    const hasDetails = !!entry.details;

    let mainHtml = `
      <div class="log-entry-main">
        <span class="log-ts">${escapeHtml(entry.timestamp)}</span>
        <span class="log-part-badge ${partClass}">${escapeHtml(entry.part || "SYSTEM")}</span>
        <span class="log-msg">${escapeHtml(entry.text)}</span>
    `;

    if (hasDetails) {
      mainHtml += `<button type="button" class="log-details-btn">Details</button>`;
    }
    mainHtml += `</div>`;

    let detailsHtml = "";
    if (hasDetails) {
      detailsHtml = `<div class="log-details-block" style="display:none;">${escapeHtml(entry.details)}</div>`;
    }

    row.innerHTML = mainHtml + detailsHtml;

    if (hasDetails) {
      const btn = row.querySelector(".log-details-btn");
      const block = row.querySelector(".log-details-block");
      if (btn && block) {
        btn.addEventListener("click", () => {
          const isShown = block.style.display !== "none";
          block.style.display = isShown ? "none" : "block";
          btn.textContent = isShown ? "Details" : "Hide Details";
        });
      }
    }

    return row;
  }

  function renderFeed() {
    if (!activityView) return;
    const stick = isNearBottom();
    activityView.innerHTML = "";
    const frag = document.createDocumentFragment();

    for (const entry of allEntries) {
      if (matchesFilter(entry)) {
        frag.appendChild(createEntryNode(entry));
      }
    }
    activityView.appendChild(frag);

    if (stick) {
      activityView.scrollTop = activityView.scrollHeight;
    }
  }

  function appendEntry(entry) {
    allEntries.push(entry);
    while (allEntries.length > MAX_ENTRIES) {
      allEntries.shift();
    }

    if (paused) return;

    if (matchesFilter(entry)) {
      const stick = isNearBottom();
      activityView.appendChild(createEntryNode(entry));
      if (stick) {
        activityView.scrollTop = activityView.scrollHeight;
      }
    }
  }

  function updateWorkingLabel() {
    if (paused) {
      statusLabel.textContent = "Paused.";
    } else if (isWorking && workStartedAt) {
      statusLabel.textContent = `Working for ${formatElapsedMs(Date.now() - workStartedAt)}`;
    } else {
      statusLabel.textContent = "Idle -- waiting for the wake word.";
    }
  }

  // --- 3. Controls Wiring ---
  pillBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      pillBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activePartFilter = btn.dataset.part || "all";
      renderFeed();
    });
  });

  if (errorsOnlyCheckbox) {
    errorsOnlyCheckbox.addEventListener("change", (e) => {
      activeErrorsOnly = !!e.target.checked;
      renderFeed();
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      activeSearchTerm = (e.target.value || "").trim();
      renderFeed();
    });
  }

  if (pauseBtn) {
    pauseBtn.addEventListener("click", () => {
      paused = !paused;
      pauseBtn.textContent = paused ? "Resume" : "Pause";
      updateWorkingLabel();
      if (!paused) {
        renderFeed();
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (isTechLogActive) {
        techLogView.textContent = "";
      } else {
        allEntries.length = 0;
        activityView.innerHTML = "";
      }
    });
  }

  if (techBtn) {
    techBtn.addEventListener("click", () => {
      isTechLogActive = !isTechLogActive;
      techBtn.classList.toggle("btn-active", isTechLogActive);
      techBtn.textContent = isTechLogActive ? "Back to Activity" : "Technical Log";

      if (isTechLogActive) {
        if (isChangeLogActive) {
          isChangeLogActive = false;
          if (changelogBtn) changelogBtn.classList.remove("btn-active");
          if (changeLogView) changeLogView.style.display = "none";
        }
        activityView.style.display = "none";
        techLogView.style.display = "block";
        if (window.ArcherClient && typeof window.ArcherClient.sendTechnicalLogSubscribe === "function") {
          window.ArcherClient.sendTechnicalLogSubscribe(true);
        }
      } else {
        techLogView.style.display = "none";
        activityView.style.display = "block";
        if (window.ArcherClient && typeof window.ArcherClient.sendTechnicalLogSubscribe === "function") {
          window.ArcherClient.sendTechnicalLogSubscribe(false);
        }
        renderFeed();
      }
    });
  }

  function renderChangeLogs(entries) {
    if (!changeLogTbody) return;
    if (!Array.isArray(entries) || entries.length === 0) {
      changeLogTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.6; padding:20px;">No change records found.</td></tr>`;
      return;
    }

    let html = "";
    for (const r of entries) {
      const statusClass = `status-${r.approval_status || "individual"}`;
      const statusLabel = {
        individual: "Approved",
        session: "Session",
        no_approval_needed: "Auto (record)",
        denied: "Denied",
        denied_timeout: "Timed Out",
      }[r.approval_status] || r.approval_status;

      html += `
        <tr>
          <td style="font-family:Consolas, monospace; color:rgba(201,246,255,0.7);">${escapeHtml(r.timestamp || "")}</td>
          <td style="font-weight:600; color:#fff;">${escapeHtml(r.what_changed || "")}</td>
          <td>${escapeHtml(r.prompted_by || "")}</td>
          <td><span class="status-badge ${statusClass}">${escapeHtml(statusLabel)}</span></td>
          <td style="font-family:Consolas, monospace; font-size:11px; color:rgba(201,246,255,0.6);">${escapeHtml(r.details || "")}</td>
        </tr>
      `;
    }
    changeLogTbody.innerHTML = html;
  }

  function fetchChangeLogs() {
    const dateVal = changeLogDateInput ? changeLogDateInput.value : "";
    if (window.ArcherClient && typeof window.ArcherClient.sendGetChangeLogs === "function") {
      window.ArcherClient.sendGetChangeLogs(dateVal || null);
    } else {
      fetch(`/api/change_log${dateVal ? `?date=${encodeURIComponent(dateVal)}` : ""}`)
        .then((res) => res.json())
        .then((data) => renderChangeLogs(data.entries))
        .catch((err) => console.error("Error fetching changelog:", err));
    }
  }

  if (changelogBtn) {
    changelogBtn.addEventListener("click", () => {
      isChangeLogActive = !isChangeLogActive;
      changelogBtn.classList.toggle("btn-active", isChangeLogActive);
      changelogBtn.textContent = isChangeLogActive ? "Back to Activity" : "Change Log";

      if (isChangeLogActive) {
        if (isTechLogActive) {
          isTechLogActive = false;
          if (techBtn) {
            techBtn.classList.remove("btn-active");
            techBtn.textContent = "Technical Log";
          }
          if (techLogView) techLogView.style.display = "none";
          if (window.ArcherClient && typeof window.ArcherClient.sendTechnicalLogSubscribe === "function") {
            window.ArcherClient.sendTechnicalLogSubscribe(false);
          }
        }
        activityView.style.display = "none";
        changeLogView.style.display = "flex";
        fetchChangeLogs();
      } else {
        changeLogView.style.display = "none";
        activityView.style.display = "block";
        renderFeed();
      }
    });
  }

  if (changeLogRefreshBtn) {
    changeLogRefreshBtn.addEventListener("click", fetchChangeLogs);
  }
  if (changeLogClearBtn) {
    changeLogClearBtn.addEventListener("click", () => {
      if (changeLogDateInput) changeLogDateInput.value = "";
      fetchChangeLogs();
    });
  }

  // --- 4. Event Subscriptions via ArcherClient ---
  if (window.ArcherClient) {
    // Status board snapshot
    window.ArcherClient.on("logsStatusBoard", (msg) => {
      if (msg && msg.board) {
        boardData = msg.board;
        renderStatusBoard();
      }
    });

    // Bulk feed rehydration (sent upon connect / reload)
    window.ArcherClient.on("logsFeedBulk", (entries) => {
      if (Array.isArray(entries)) {
        allEntries.length = 0;
        for (const item of entries) {
          allEntries.push(item);
        }
        renderFeed();
      }
    });

    // Single activity feed entry
    window.ArcherClient.on("logsFeedEntry", (item) => {
      if (item) {
        appendEntry(item);
      }
    });

    // Legacy log_line fallback for backwards compatibility
    window.ArcherClient.on("logLine", (text) => {
      if (!text || allEntries.length > 0) return;
      for (const line of text.split("\n")) {
        const trimmed = line.trim();
        if (trimmed) {
          const m = /^(\d{2}:\d{2}:\d{2})\s*\|\s*(.*)$/.exec(trimmed);
          appendEntry({
            id: String(Date.now() + Math.random()),
            timestamp: m ? m[1] : "",
            part: "System",
            level: "info",
            text: m ? m[2] : trimmed,
            details: null,
          });
        }
      }
    });

    // Technical log live lines
    window.ArcherClient.on("technicalLogBulk", (lines) => {
      if (techLogView && Array.isArray(lines)) {
        techLogView.textContent = lines.join("\n") + "\n";
        techLogView.scrollTop = techLogView.scrollHeight;
      }
    });

    window.ArcherClient.on("technicalLogLine", (line) => {
      if (techLogView && isTechLogActive && line) {
        techLogView.textContent += line + "\n";
        techLogView.scrollTop = techLogView.scrollHeight;
      }
    });

    // Pipeline state driving the "Working for" timer
    window.ArcherClient.on("state", (e) => {
      const state = typeof e === "string" ? e : e?.state;
      const isWorkingState = state === "processing" || state === "speaking";
      if (isWorkingState && !isWorking) {
        isWorking = true;
        workStartedAt = Date.now();
        if (!workTimerHandle) workTimerHandle = setInterval(updateWorkingLabel, 1000);
      } else if (!isWorkingState && isWorking) {
        isWorking = false;
        workStartedAt = null;
        if (workTimerHandle) {
          clearInterval(workTimerHandle);
          workTimerHandle = null;
        }
      }
      updateWorkingLabel();
    });

    // Change log list update
    window.ArcherClient.on("changeLogList", (entries) => {
      renderChangeLogs(entries);
    });

    // Re-request status board on connect
    window.ArcherClient.on("connected", () => {
      if (typeof window.ArcherClient.sendLogsGetStatus === "function") {
        window.ArcherClient.sendLogsGetStatus();
      }
    });
  }

  // Self-render initial status board cards
  renderStatusBoard();
})();
