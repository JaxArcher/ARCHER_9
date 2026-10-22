/**
 * ARCHER browser client — ANDROID tab (Phase 7b).
 *
 * Implements the interactive Android virtual phone interface:
 * - Dedicated binary WebSocket (/ws/android) for raw JPEG frames with per-client backpressure.
 * - Streams frames ONLY while ANDROID tab is visible (auto-pauses on tab switch or browser minimization).
 * - Dynamic resolution sizing to the tab's real pixel height (capped at 1080x2400).
 * - Startup progress banner: launching -> Android booting -> connecting screen -> online.
 * - Details log pane showing live ~20 lines of logs/android_emulator.log during starting/error.
 * - 5-second unacknowledged start fallback ("ARCHER didn't respond").
 * - Toolbar: Back, Home, Recent Apps, Rotate, Details, Start/Stop Virtual Phone.
 * - Hardware-accelerated Canvas rendering via createImageBitmap.
 * - Bidirectional mouse/touch/keyboard event forwarding.
 */
(() => {
  let isRunning = false;
  let isStarting = false;
  let canvas = null;
  let ctx = null;
  let statusBadge = null;
  let startStopBtn = null;
  let isTouching = false;
  let currentRotation = 0; // 0, 90, 180, 270
  let isTabVisible = false;
  let streamWs = null;
  let startTimeoutTimer = null;

  function initAndroidTab() {
    canvas = document.getElementById("archer-android-canvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    statusBadge = document.getElementById("android-status-badge");
    startStopBtn = document.getElementById("android-btn-start-stop");

    // Toolbar button bindings
    const btnBack = document.getElementById("android-btn-back");
    const btnHome = document.getElementById("android-btn-home");
    const btnRecents = document.getElementById("android-btn-recents");
    const btnRotate = document.getElementById("android-btn-rotate");
    const btnDetails = document.getElementById("android-btn-details");
    const detailsPane = document.getElementById("android-details-pane");
    const detailsClose = document.getElementById("android-details-close");

    if (btnBack) btnBack.addEventListener("click", () => sendButton("back"));
    if (btnHome) btnHome.addEventListener("click", () => sendButton("home"));
    if (btnRecents) btnRecents.addEventListener("click", () => sendButton("overview"));
    if (btnRotate) btnRotate.addEventListener("click", () => rotateScreen());
    if (startStopBtn) startStopBtn.addEventListener("click", toggleEmulator);

    if (btnDetails && detailsPane) {
      btnDetails.addEventListener("click", () => {
        const isHidden = detailsPane.style.display === "none";
        detailsPane.style.display = isHidden ? "block" : "none";
        btnDetails.textContent = isHidden ? "Hide Details" : "Details";
        if (isHidden && window.ArcherClient && typeof window.ArcherClient.sendAndroidGetLogs === "function") {
          window.ArcherClient.sendAndroidGetLogs();
        }
      });
    }

    if (detailsClose && detailsPane) {
      detailsClose.addEventListener("click", () => {
        detailsPane.style.display = "none";
        if (btnDetails) btnDetails.textContent = "Details";
      });
    }

    // Canvas touch/mouse interaction
    canvas.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    // Touch support for touchscreens / tablets
    canvas.addEventListener("touchstart", handleTouchStart, { passive: false });
    window.addEventListener("touchmove", handleTouchMove, { passive: false });
    window.addEventListener("touchend", handleTouchEnd, { passive: false });

    // Keyboard interaction
    canvas.setAttribute("tabindex", "0");
    canvas.addEventListener("keydown", handleKeyDown);
    canvas.addEventListener("keyup", handleKeyUp);

    // Tab visibility listener (Phase 7b review item 1)
    window.addEventListener("archer-tab-changed", (e) => {
      const tab = e.detail && e.detail.activeTab;
      if (tab === "android") {
        isTabVisible = true;
        canvas.focus();
        openStreamWs();
        sendResize();
        sendWsMessage({ type: "android_tab_visibility", visible: true });
        if (!isRunning && !isStarting) {
          sendWsMessage({ type: "android_query_state" });
        }
      } else {
        if (isTabVisible) {
          isTabVisible = false;
          closeStreamWs();
          sendWsMessage({ type: "android_tab_visibility", visible: false });
        }
      }
    });

    // Browser tab minimization / window visibility listener (Claude 15:15 follow-up)
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        if (isTabVisible) {
          closeStreamWs();
          sendWsMessage({ type: "android_tab_visibility", visible: false });
        }
      } else {
        if (isTabVisible) {
          openStreamWs();
          sendResize();
          sendWsMessage({ type: "android_tab_visibility", visible: true });
        }
      }
    });

    // ResizeObserver on viewport wrapper for dynamic sizing (Phase 7b review item 2)
    const wrapper = document.querySelector(".android-viewport-wrapper");
    if (wrapper && window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        if (isTabVisible) {
          sendResize();
        }
      });
      ro.observe(wrapper);
    }
    window.addEventListener("resize", () => {
      if (isTabVisible) sendResize();
    });

    // Register with ArcherClient WebSocket dispatcher for state updates
    if (window.ArcherClient) {
      window.ArcherClient.on("android_state", handleStateUpdate);
      window.ArcherClient.on("android_log_tail", (lines) => {
        const detailsLog = document.getElementById("android-details-log");
        if (detailsLog && Array.isArray(lines)) {
          detailsLog.textContent = lines.join("\n");
          detailsLog.scrollTop = detailsLog.scrollHeight;
        }
      });
      // Initial state query
      sendWsMessage({ type: "android_query_state" });
    }
  }

  function getWsUrl(path) {
    const loc = window.location;
    const proto = loc.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${loc.host}${path}`;
  }

  function openStreamWs() {
    if (streamWs && (streamWs.readyState === WebSocket.OPEN || streamWs.readyState === WebSocket.CONNECTING)) {
      return;
    }
    try {
      streamWs = new WebSocket(getWsUrl("/ws/android"));
      streamWs.binaryType = "blob";

      streamWs.onopen = () => {
        console.log("[archer-android] Dedicated /ws/android binary stream connected.");
        sendResize();
      };

      streamWs.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          try {
            const bmp = await createImageBitmap(event.data);
            if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
              canvas.width = bmp.width;
              canvas.height = bmp.height;
            }
            ctx.drawImage(bmp, 0, 0);
            bmp.close();
          } catch (err) {
            console.debug("[archer-android] Bitmap render error:", err);
          }
        }
      };

      streamWs.onclose = () => {
        console.log("[archer-android] /ws/android disconnected.");
        streamWs = null;
      };

      streamWs.onerror = (e) => {
        console.debug("[archer-android] /ws/android error:", e);
      };
    } catch (err) {
      console.error("[archer-android] Failed to open /ws/android:", err);
    }
  }

  function closeStreamWs() {
    if (streamWs) {
      try {
        streamWs.close();
      } catch (e) {}
      streamWs = null;
    }
  }

  function sendResize() {
    if (!isTabVisible) return;
    const wrapper = document.querySelector(".android-viewport-wrapper") || canvas;
    if (!wrapper) return;
    const dpr = window.devicePixelRatio || 1;
    // Calculate actual pixel height of viewport, bounded [400, 2400]
    const h = Math.min(2400, Math.max(400, Math.round(wrapper.clientHeight * dpr)));
    // Pixel 7 aspect ratio: 1080 / 2400 = 0.45
    const w = Math.min(1080, Math.max(180, Math.round(h * (1080 / 2400))));

    if (streamWs && streamWs.readyState === WebSocket.OPEN) {
      streamWs.send(JSON.stringify({ type: "resize", width: w, height: h }));
    }
    sendWsMessage({ type: "android_resize", width: w, height: h });
  }

  function sendInput(data) {
    if (streamWs && streamWs.readyState === WebSocket.OPEN) {
      streamWs.send(JSON.stringify(data));
    } else {
      sendWsMessage(data);
    }
  }

  function sendWsMessage(msg) {
    if (window.ArcherClient && typeof window.ArcherClient.send === "function") {
      window.ArcherClient.send(msg);
    } else {
      console.warn("[archer-android] ArcherClient WebSocket not available to send:", msg);
    }
  }

  function toggleEmulator() {
    if (isRunning) {
      updateStatus("Stopping virtual phone...", "amber");
      if (startStopBtn) startStopBtn.disabled = true;
      sendWsMessage({ type: "android_stop" });
    } else {
      // Do not prematurely claim "Starting" without server word
      updateStatus("Connecting to ARCHER...", "amber");
      if (startStopBtn) {
        startStopBtn.disabled = true;
        startStopBtn.textContent = "Connecting...";
      }

      if (startTimeoutTimer) clearTimeout(startTimeoutTimer);
      startTimeoutTimer = setTimeout(() => {
        if (!isRunning && !isStarting) {
          updateStatus("ARCHER didn't respond", "red");
          if (startStopBtn) {
            startStopBtn.disabled = false;
            startStopBtn.textContent = "Start Virtual Phone";
          }
        }
      }, 5000);

      sendWsMessage({ type: "android_start" });
    }
  }

  function sendButton(buttonName) {
    if (!isRunning) return;
    sendInput({ type: "android_button", button: buttonName });
  }

  function rotateScreen() {
    if (!isRunning) return;
    currentRotation = (currentRotation + 90) % 360;
    sendInput({ type: "android_button", button: "rotate", rotation: currentRotation });
  }

  function getCanvasCoords(e) {
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
    const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
    const normX = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const normY = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    return { x: normX, y: normY };
  }

  function handleMouseDown(e) {
    if (!isRunning) return;
    e.preventDefault();
    canvas.focus();
    isTouching = true;
    const { x, y } = getCanvasCoords(e);
    sendInput({ type: "android_touch", action: "down", x, y });
  }

  function handleMouseMove(e) {
    if (!isTouching || !isRunning) return;
    const { x, y } = getCanvasCoords(e);
    sendInput({ type: "android_touch", action: "move", x, y });
  }

  function handleMouseUp(e) {
    if (!isTouching) return;
    isTouching = false;
    const { x, y } = getCanvasCoords(e);
    sendInput({ type: "android_touch", action: "up", x, y });
  }

  function handleTouchStart(e) {
    if (!isRunning) return;
    e.preventDefault();
    isTouching = true;
    const { x, y } = getCanvasCoords(e);
    sendInput({ type: "android_touch", action: "down", x, y });
  }

  function handleTouchMove(e) {
    if (!isTouching || !isRunning) return;
    e.preventDefault();
    const { x, y } = getCanvasCoords(e);
    sendInput({ type: "android_touch", action: "move", x, y });
  }

  function handleTouchEnd(e) {
    if (!isTouching) return;
    e.preventDefault();
    isTouching = false;
    const { x, y } = getCanvasCoords(e);
    sendInput({ type: "android_touch", action: "up", x, y });
  }

  function handleKeyDown(e) {
    if (!isRunning) return;
    // Don't intercept browser developer tools (F12) or hard refresh (Ctrl+Shift+R)
    if (e.key === "F12" || (e.ctrlKey && e.shiftKey && e.key === "R")) return;
    e.preventDefault();
    sendInput({
      type: "android_key",
      action: "down",
      key: e.key,
      code: e.code,
      keyCode: e.keyCode,
      text: e.key.length === 1 ? e.key : "",
    });
  }

  function handleKeyUp(e) {
    if (!isRunning) return;
    if (e.key === "F12" || (e.ctrlKey && e.shiftKey && e.key === "R")) return;
    e.preventDefault();
    sendInput({
      type: "android_key",
      action: "up",
      key: e.key,
      code: e.code,
      keyCode: e.keyCode,
    });
  }

  function handleStateUpdate(state) {
    if (startTimeoutTimer) {
      clearTimeout(startTimeoutTimer);
      startTimeoutTimer = null;
    }
    if (startStopBtn) startStopBtn.disabled = false;

    isRunning = !!state.running;
    isStarting = !!state.starting;

    const banner = document.getElementById("android-step-banner");
    const stepText = document.getElementById("android-step-text");
    const stepTime = document.getElementById("android-step-time");
    const btnDetails = document.getElementById("android-btn-details");
    const detailsPane = document.getElementById("android-details-pane");
    const detailsLog = document.getElementById("android-details-log");

    if (state.log_tail && Array.isArray(state.log_tail) && detailsLog) {
      detailsLog.textContent = state.log_tail.join("\n");
      detailsLog.scrollTop = detailsLog.scrollHeight;
    }

    if (isRunning) {
      updateStatus(
        state.gpu_mode ? `Online (${state.gpu_mode})` : "Online",
        "green"
      );
      if (startStopBtn) {
        startStopBtn.textContent = "Stop Virtual Phone";
        startStopBtn.classList.remove("btn-primary");
        startStopBtn.classList.add("btn-danger");
      }
      if (banner) banner.style.display = "none";
      if (btnDetails) btnDetails.style.display = "none";
      if (detailsPane) detailsPane.style.display = "none";

      const placeholder = document.getElementById("android-placeholder-message");
      if (placeholder) placeholder.style.display = "none";
      if (canvas) canvas.style.display = "block";
      if (isTabVisible) {
        openStreamWs();
      }
    } else if (isStarting) {
      updateStatus("Starting virtual phone...", "amber");
      if (startStopBtn) startStopBtn.textContent = "Starting...";

      if (banner) {
        banner.style.display = "flex";
        if (stepText) stepText.textContent = state.step_description || "Starting...";
        if (stepTime) stepTime.textContent = state.elapsed_sec ? `${state.elapsed_sec}s` : "";
      }
      if (btnDetails) btnDetails.style.display = "inline-flex";
    } else {
      const isErr = state.step === "error" || (state.message && state.message.includes("Error"));
      updateStatus(state.message || "Offline", isErr ? "red" : "gray");
      if (startStopBtn) {
        startStopBtn.textContent = "Start Virtual Phone";
        startStopBtn.classList.remove("btn-danger");
        startStopBtn.classList.add("btn-primary");
      }

      if (banner) {
        if (isErr && state.step_description) {
          banner.style.display = "flex";
          if (stepText) stepText.textContent = state.step_description;
          if (stepTime) stepTime.textContent = "";
        } else {
          banner.style.display = "none";
        }
      }

      if (btnDetails) {
        btnDetails.style.display = isErr ? "inline-flex" : "none";
      }

      const placeholder = document.getElementById("android-placeholder-message");
      if (placeholder) {
        placeholder.style.display = "flex";
        if (state.detail) {
          const detailEl = document.getElementById("android-placeholder-detail");
          if (detailEl) detailEl.textContent = state.detail;
        }
      }
      if (canvas && !state.has_last_frame) {
        canvas.style.display = "none";
      }
      closeStreamWs();
    }
  }

  function updateStatus(text, color) {
    if (!statusBadge) return;
    statusBadge.textContent = text;
    statusBadge.className = `status-pill pill-${color}`;
  }

  // Self-initialize once DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAndroidTab);
  } else {
    initAndroidTab();
  }
})();
