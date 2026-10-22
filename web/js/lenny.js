/**
 * ARCHER browser client — LENNY Tab (Spec Section 11, revised 2026-10-22).
 *
 * Implements:
 * 1. Live video feed of LENNY's desktop (~30 FPS, low latency, sharp text).
 * 2. Real-time frame rate & round-trip latency measurement.
 * 3. Bidirectional interactive takeover (mouse clicks, drags, wheel, and keyboard input).
 * 4. Task tracking ("Working on: ...") with Pause and Stop controls.
 * 5. Pairing interface for one-time 6-digit code pairing.
 * 6. Stream activation gating (streams only while tab is visible).
 * 7. Synced artifacts viewer for files generated on LENNY.
 */
(() => {
  const panel = document.getElementById("tab-lenny");
  if (!panel) return;

  panel.innerHTML = `
    <div class="archer-dashboard-card lenny-container-card">
      <!-- Toolbar -->
      <div class="lenny-toolbar">
        <div class="lenny-toolbar-group">
          <span id="lenny-status-badge" class="status-pill pill-gray">Unpaired</span>
          <div class="lenny-task-wrap">
            <span class="lenny-task-label">Working on:</span>
            <span id="lenny-task-text" class="lenny-task-text">No active task</span>
          </div>
        </div>

        <div class="lenny-toolbar-group">
          <span id="lenny-fps-badge" class="stream-metric" title="Measured Frame Rate">0 FPS</span>
          <span id="lenny-latency-badge" class="stream-metric" title="Measured Network Delay">-- ms</span>
          <button id="lenny-btn-pause" type="button" class="lenny-btn" title="Pause ARCHER on LENNY">Pause</button>
          <button id="lenny-btn-resume" type="button" class="lenny-btn btn-primary" style="display:none;" title="Resume ARCHER on LENNY">Resume</button>
          <button id="lenny-btn-stop" type="button" class="lenny-btn btn-danger" title="Stop Task">Stop</button>
          <button id="lenny-btn-reconnect" type="button" class="lenny-btn btn-secondary" title="Reconnect Stream">Reconnect</button>
        </div>
      </div>

      <!-- Takeover Alert Banner -->
      <div id="lenny-takeover-banner" class="lenny-takeover-banner" style="display:none;">
        <span class="takeover-icon">&#x270B;</span>
        <span class="takeover-text">Physical user takeover active on LENNY &mdash; ARCHER paused</span>
      </div>

      <!-- UIPI Block Alert Banner -->
      <div id="lenny-uipi-banner" class="lenny-uipi-banner" style="display:none;">
        <span class="uipi-icon">&#x26A0;</span>
        <span id="lenny-uipi-text" class="uipi-text">LENNY is showing an administrator window that ARCHER can't control</span>
      </div>

      <!-- Main Screen Viewport -->
      <div class="lenny-viewport-wrapper">
        <canvas id="lenny-screen-canvas" class="lenny-canvas" tabindex="0" title="Click and type to interact with LENNY"></canvas>

        <!-- Unpaired / Offline Placeholder & Setup Overlay -->
        <div id="lenny-placeholder" class="lenny-placeholder">
          <div class="lenny-placeholder-content">
            <div class="lenny-desk-icon">&#x1F5A5;</div>
            <h3 id="lenny-placeholder-title">LENNY (ARCHER's Desk)</h3>
            <p id="lenny-placeholder-detail">Connect ARCHER to its dedicated desk PC to automate Windows apps, Office documents, and web browsing undisturbed.</p>

            <div id="lenny-pairing-box" class="lenny-pairing-box">
              <div class="pairing-field">
                <label for="lenny-input-host">LENNY IP Address:</label>
                <input type="text" id="lenny-input-host" class="lenny-input" placeholder="e.g. 192.168.4.50" value="" />
              </div>
              <div class="pairing-field">
                <label for="lenny-input-code">6-Digit Pairing Code:</label>
                <input type="text" id="lenny-input-code" class="lenny-input" placeholder="e.g. 482910" maxlength="6" />
              </div>
              <button id="lenny-btn-pair" type="button" class="lenny-btn btn-primary">Pair with LENNY</button>
              <div id="lenny-pair-error" class="lenny-error-text" style="display:none;"></div>
            </div>

            <p class="lenny-setup-hint">
              First time? Run <code>scripts/lenny_setup.ps1</code> on LENNY as Administrator. See <code>docs/LENNY_Setup_Checklist.md</code>.
            </p>
          </div>
        </div>
      </div>

      <!-- Footer Bar -->
      <div class="lenny-footer-bar">
        <div class="lenny-footer-left">
          <span>Browser running on: <strong id="lenny-browser-host-label">LENNY</strong></span>
          <span class="lenny-footer-sep">&bull;</span>
          <span id="lenny-mouse-coords" style="opacity:0.6;">Focus feed to control with mouse &amp; keyboard</span>
        </div>
        <div class="lenny-footer-right" id="lenny-synced-artifacts">
          <!-- Recent files synced from LENNY -->
        </div>
      </div>
    </div>
  `;

  // UI Element References
  const canvas = document.getElementById("lenny-screen-canvas");
  const ctx = canvas.getContext("2d");
  const placeholder = document.getElementById("lenny-placeholder");
  const statusBadge = document.getElementById("lenny-status-badge");
  const taskText = document.getElementById("lenny-task-text");
  const fpsBadge = document.getElementById("lenny-fps-badge");
  const latencyBadge = document.getElementById("lenny-latency-badge");
  const takeoverBanner = document.getElementById("lenny-takeover-banner");
  const uipiBanner = document.getElementById("lenny-uipi-banner");
  const uipiText = document.getElementById("lenny-uipi-text");
  const browserHostLabel = document.getElementById("lenny-browser-host-label");
  const mouseCoords = document.getElementById("lenny-mouse-coords");
  const artifactsContainer = document.getElementById("lenny-synced-artifacts");

  const btnPause = document.getElementById("lenny-btn-pause");
  const btnResume = document.getElementById("lenny-btn-resume");
  const btnStop = document.getElementById("lenny-btn-stop");
  const btnReconnect = document.getElementById("lenny-btn-reconnect");
  const btnPair = document.getElementById("lenny-btn-pair");
  const inputHost = document.getElementById("lenny-input-host");
  const inputCode = document.getElementById("lenny-input-code");
  const pairError = document.getElementById("lenny-pair-error");

  let ws = null;
  let isTabVisible = false;
  let frameCount = 0;
  let lastFpsCalcTime = performance.now();
  let pingIntervalHandle = null;
  let lastPingSent = 0;
  let measuredLatencyMs = 0;
  let reconnectTimer = null;

  // --- 1. Tab Visibility Gating ---
  window.addEventListener("archer-tab-changed", (e) => {
    const isNowVisible = e.detail && e.detail.activeTab === "lenny";
    if (isNowVisible && !isTabVisible) {
      isTabVisible = true;
      startStream();
      refreshStatus();
      loadSyncedFiles();
    } else if (!isNowVisible && isTabVisible) {
      isTabVisible = false;
      stopStream();
    }
  });

  // --- 2. Live Stream Management ---
  const viewportWrapper = document.querySelector(".lenny-viewport-wrapper");

  function sendViewportSize() {
    if (ws && ws.readyState === WebSocket.OPEN && viewportWrapper) {
      const rect = viewportWrapper.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.round(rect.width * dpr);
      const h = Math.round(rect.height * dpr);
      if (w > 0 && h > 0) {
        ws.send(JSON.stringify({ type: "resize", width: w, height: h }));
      }
    }
  }

  const resizeObserver = new ResizeObserver(() => {
    if (isTabVisible) {
      sendViewportSize();
    }
  });
  if (viewportWrapper) {
    resizeObserver.observe(viewportWrapper);
  }

  function getWsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws/lenny_stream`;
  }

  function startStream() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    clearTimeout(reconnectTimer);

    try {
      ws = new WebSocket(getWsUrl());
    } catch (err) {
      console.warn("[LENNY] WebSocket connect failed:", err);
      return;
    }

    ws.onopen = () => {
      console.log("[LENNY] Live screen stream connected");
      startPingLoop();
      sendViewportSize();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleStreamMessage(msg);
      } catch (err) {
        console.debug("[LENNY] WS parse error:", err);
      }
    };

    ws.onclose = (event) => {
      console.log("[LENNY] Stream closed:", event.code, event.reason);
      stopPingLoop();
      fpsBadge.textContent = "0 FPS";
      latencyBadge.textContent = "-- ms";

      if (isTabVisible && event.code !== 4000) {
        reconnectTimer = setTimeout(startStream, 2500);
      }
    };

    ws.onerror = (err) => {
      console.warn("[LENNY] Stream error:", err);
    };
  }

  function stopStream() {
    clearTimeout(reconnectTimer);
    stopPingLoop();
    if (ws) {
      try {
        ws.close();
      } catch (e) {}
      ws = null;
    }
    fpsBadge.textContent = "0 FPS";
    latencyBadge.textContent = "-- ms";
  }

  function startPingLoop() {
    stopPingLoop();
    pingIntervalHandle = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        lastPingSent = performance.now();
        ws.send(JSON.stringify({ type: "ping", time: lastPingSent }));
      }
    }, 2000);
  }

  function stopPingLoop() {
    if (pingIntervalHandle) {
      clearInterval(pingIntervalHandle);
      pingIntervalHandle = null;
    }
  }

  // --- 3. Stream Message & Frame Rendering ---
  const frameImg = new Image();
  let isImageLoading = false;

  frameImg.onload = () => {
    isImageLoading = false;
    if (canvas.width !== frameImg.naturalWidth || canvas.height !== frameImg.naturalHeight) {
      canvas.width = frameImg.naturalWidth;
      canvas.height = frameImg.naturalHeight;
    }
    ctx.drawImage(frameImg, 0, 0);

    // Frame Rate Calculation
    frameCount++;
    const now = performance.now();
    const elapsed = now - lastFpsCalcTime;
    if (elapsed >= 1000) {
      const fps = Math.round((frameCount * 1000) / elapsed);
      fpsBadge.textContent = `${fps} FPS`;
      frameCount = 0;
      lastFpsCalcTime = now;
    }

    // Hide placeholder once video frames arrive
    placeholder.style.display = "none";
    canvas.style.display = "block";
  };

  function handleStreamMessage(msg) {
    if (msg.type === "frame") {
      if (!isImageLoading && msg.image) {
        isImageLoading = true;
        frameImg.src = "data:image/jpeg;base64," + msg.image;
      }

      // Update UI state from frame headers
      if (msg.task !== undefined) {
        taskText.textContent = msg.task || "No active task";
      }
      if (msg.takeover !== undefined) {
        setTakeoverActive(Boolean(msg.takeover));
      }
      if (msg.status) {
        updateStatusPill(msg.status);
      }
    } else if (msg.type === "pong") {
      if (lastPingSent > 0) {
        measuredLatencyMs = Math.round(performance.now() - lastPingSent);
        latencyBadge.textContent = `${measuredLatencyMs} ms`;
        if (measuredLatencyMs > 250) {
          latencyBadge.style.color = "#ffb84d";
        } else {
          latencyBadge.style.color = "#4dffb8";
        }
      }
    } else if (msg.type === "uipi_blocked") {
      setUipiBlocked(Boolean(msg.blocked), msg.message, msg.window);
    } else if (msg.type === "status") {
      if (msg.status === "unpaired" || msg.status === "offline") {
        placeholder.style.display = "flex";
        canvas.style.display = "none";
        updateStatusPill(msg.status);
        if (msg.message) {
          document.getElementById("lenny-placeholder-detail").textContent = msg.message;
        }
      }
    }
  }

  // --- 4. Interactive Takeover (Bidirectional Input Forwarding) ---
  function getNormalizedCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const cw = canvas.width || 1280;
    const ch = canvas.height || 720;
    const canvasAspect = cw / ch;
    const elementAspect = rect.width / rect.height;

    let renderW, renderH, offsetX, offsetY;
    if (elementAspect > canvasAspect) {
      // Pillarboxed (letterbox on left/right)
      renderH = rect.height;
      renderW = renderH * canvasAspect;
      offsetX = (rect.width - renderW) / 2;
      offsetY = 0;
    } else {
      // Letterboxed (bars on top/bottom)
      renderW = rect.width;
      renderH = renderW / canvasAspect;
      offsetX = 0;
      offsetY = (rect.height - renderH) / 2;
    }

    const clickX = e.clientX - rect.left - offsetX;
    const clickY = e.clientY - rect.top - offsetY;

    return {
      norm_x: Math.max(0.0, Math.min(1.0, clickX / renderW)),
      norm_y: Math.max(0.0, Math.min(1.0, clickY / renderH)),
    };
  }

  canvas.addEventListener("mousemove", (e) => {
    const { norm_x, norm_y } = getNormalizedCoords(e);
    mouseCoords.textContent = `Cursor: (${Math.round(norm_x * 100)}%, ${Math.round(norm_y * 100)}%)`;

    // Forward mousemove only when dragging (mouse button pressed)
    if (e.buttons > 0 && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "mouse",
        event: "mousemove",
        norm_x,
        norm_y,
        button: e.buttons === 2 ? "right" : "left",
      }));
    }
  });

  canvas.addEventListener("mousedown", (e) => {
    canvas.focus();
    const { norm_x, norm_y } = getNormalizedCoords(e);
    const btn = e.button === 2 ? "right" : "left";
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "mouse",
        event: "mousedown",
        norm_x,
        norm_y,
        button: btn,
      }));
    }
  });

  canvas.addEventListener("mouseup", (e) => {
    const { norm_x, norm_y } = getNormalizedCoords(e);
    const btn = e.button === 2 ? "right" : "left";
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "mouse",
        event: "mouseup",
        norm_x,
        norm_y,
        button: btn,
      }));
    }
  });

  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "mouse",
        event: "wheel",
        norm_x: 0,
        norm_y: e.deltaY < 0 ? 120 : -120, // Win32 WHEEL_DELTA
      }));
    }
  }, { passive: false });

  canvas.addEventListener("keydown", (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      const isEditingNav = ["Tab", "Backspace", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space", "Enter", "Escape", "Delete"].includes(e.key);
      if (isEditingNav || e.ctrlKey || e.altKey) {
        e.preventDefault();
      }
      ws.send(JSON.stringify({
        type: "key",
        event: "keydown",
        key: e.key,
        code: e.code,
        char_code: e.key.length === 1 ? e.key.charCodeAt(0) : null,
        ctrl: e.ctrlKey,
        alt: e.altKey,
        shift: e.shiftKey,
        meta: e.metaKey,
      }));
    }
  });

  canvas.addEventListener("keyup", (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (["Tab", "Backspace", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space", "Enter", "Escape", "Delete"].includes(e.key) || e.ctrlKey || e.altKey) {
        e.preventDefault();
      }
      ws.send(JSON.stringify({
        type: "key",
        event: "keyup",
        key: e.key,
        code: e.code,
        ctrl: e.ctrlKey,
        alt: e.altKey,
        shift: e.shiftKey,
        meta: e.metaKey,
      }));
    }
  });

  // --- 5. Status & Task Controls ---
  function updateStatusPill(status) {
    statusBadge.className = "status-pill";
    const st = (status || "").toLowerCase();
    if (st === "working") {
      statusBadge.classList.add("pill-amber");
      statusBadge.textContent = "Working";
      btnPause.style.display = "inline-block";
      btnResume.style.display = "none";
    } else if (st === "paused") {
      statusBadge.classList.add("pill-amber");
      statusBadge.textContent = "Paused";
      btnPause.style.display = "none";
      btnResume.style.display = "inline-block";
    } else if (st === "idle" || st === "paired" || st === "connected") {
      statusBadge.classList.add("pill-green");
      statusBadge.textContent = "Connected";
      btnPause.style.display = "inline-block";
      btnResume.style.display = "none";
    } else if (st === "offline") {
      statusBadge.classList.add("pill-red");
      statusBadge.textContent = "Offline";
    } else {
      statusBadge.classList.add("pill-gray");
      statusBadge.textContent = "Unpaired";
    }
  }

  function setTakeoverActive(active) {
    if (active) {
      takeoverBanner.style.display = "flex";
      updateStatusPill("paused");
    } else {
      takeoverBanner.style.display = "none";
    }
  }

  function setUipiBlocked(blocked, message, windowTitle) {
    if (blocked) {
      uipiBanner.style.display = "flex";
      if (message) {
        uipiText.textContent = message;
      } else if (windowTitle) {
        uipiText.textContent = `LENNY is showing an administrator window (${windowTitle}) that ARCHER can't control. Switch windows or close Administrator PowerShell on LENNY.`;
      } else {
        uipiText.textContent = "LENNY is showing an administrator window that ARCHER can't control. Switch windows or close Administrator PowerShell on LENNY.";
      }
    } else {
      uipiBanner.style.display = "none";
    }
  }

  async function refreshStatus() {
    try {
      const resp = await fetch("/api/lenny/status");
      if (resp.ok) {
        const data = await resp.json();
        updateStatusPill(data.status);
        taskText.textContent = data.current_task || "No active task";
        setTakeoverActive(Boolean(data.takeover_active));

        if (data.browser_host) {
          browserHostLabel.textContent = data.browser_host;
          browserHostLabel.style.color = data.browser_host === "LENNY" ? "#4dffb8" : "#ffb84d";
        }

        if (data.host && !inputHost.value) {
          inputHost.value = data.host;
        }

        if (!data.configured) {
          placeholder.style.display = "flex";
          canvas.style.display = "none";
        }
      }
    } catch (err) {
      console.debug("[LENNY] Status check error:", err);
    }
  }

  btnPause.addEventListener("click", async () => {
    try {
      await fetch("/api/lenny/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "pause" }),
      });
      refreshStatus();
    } catch (err) {
      console.warn("Pause error:", err);
    }
  });

  btnResume.addEventListener("click", async () => {
    try {
      await fetch("/api/lenny/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "resume" }),
      });
      refreshStatus();
    } catch (err) {
      console.warn("Resume error:", err);
    }
  });

  btnStop.addEventListener("click", async () => {
    try {
      await fetch("/api/lenny/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "stop" }),
      });
      refreshStatus();
    } catch (err) {
      console.warn("Stop error:", err);
    }
  });

  btnReconnect.addEventListener("click", () => {
    stopStream();
    startStream();
    refreshStatus();
  });

  btnPair.addEventListener("click", async () => {
    pairError.style.display = "none";
    const host = (inputHost.value || "").trim();
    const code = (inputCode.value || "").trim();

    if (!host) {
      pairError.textContent = "Please enter LENNY's IP address.";
      pairError.style.display = "block";
      return;
    }
    if (!code) {
      pairError.textContent = "Please enter the 6-digit pairing code.";
      pairError.style.display = "block";
      return;
    }

    btnPair.disabled = true;
    btnPair.textContent = "Pairing...";

    try {
      const resp = await fetch("/api/lenny/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host, pairing_code: code }),
      });

      if (resp.ok) {
        btnPair.textContent = "Paired!";
        setTimeout(() => {
          btnPair.textContent = "Pair with LENNY";
          btnPair.disabled = false;
          refreshStatus();
          startStream();
        }, 1000);
      } else {
        const errData = await resp.json();
        throw new Error(errData.detail || "Pairing failed");
      }
    } catch (err) {
      btnPair.disabled = false;
      btnPair.textContent = "Pair with LENNY";
      pairError.textContent = `Pairing failed: ${err.message}`;
      pairError.style.display = "block";
    }
  });

  // --- 6. Synced Artifacts Display ---
  async function loadSyncedFiles() {
    try {
      const resp = await fetch("/api/lenny/files");
      if (resp.ok) {
        const data = await resp.json();
        const files = data.files || [];
        if (files.length > 0) {
          const recent = files.slice(0, 3);
          const links = recent.map((f) => `<a href="/data/artifacts/${encodeURIComponent(f.name)}" target="_blank" class="lenny-artifact-link" title="Open synced document">&#x1F4C4; ${f.name}</a>`).join(" ");
          artifactsContainer.innerHTML = `<span>Synced from LENNY: ${links}</span>`;
        } else {
          artifactsContainer.innerHTML = `<span style="opacity:0.6;">No synced documents yet</span>`;
        }
      }
    } catch (err) {
      console.debug("[LENNY] loadSyncedFiles error:", err);
    }
  }

  // --- 7. App Event Subscriptions ---
  if (window.ArcherClient) {
    window.ArcherClient.on("lenny_status", (data) => {
      if (data.status) updateStatusPill(data.status);
      if (data.task !== undefined) taskText.textContent = data.task || "No active task";
    });

    window.ArcherClient.on("lenny_takeover", (data) => {
      setTakeoverActive(Boolean(data.active));
    });
  }

  // Initial status probe
  refreshStatus();
})();
