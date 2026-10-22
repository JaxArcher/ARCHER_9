/**
 * ARCHER browser client — Chromium inside the pane (Phase 7, Spec Section 10).
 *
 * Replaces the old 2-second screenshot mirror with a live interactive Chromium
 * browser inside the ARTIFACTS tab.
 *
 * Features:
 * - Real-time Chrome DevTools Protocol (CDP) screencast streaming on HTML5 canvas.
 * - Bidirectional mouse (click, drag, wheel) and keyboard input forwarding.
 * - Browser chrome: tabs strip (with pinned Google Messages), back, forward, reload,
 *   home, and address bar.
 * - Auto-pauses frame pumping when tab is inactive to save CPU/GPU.
 */
(() => {
  const panel = document.getElementById("tab-browser");
  if (!panel) return;

  panel.innerHTML = `
    <div class="browser-card-header">
      <div class="browser-header-title">
        <span class="browser-title-icon">&#x1F310;</span>
        <span class="browser-title-text">CHROMIUM BROWSER</span>
      </div>
      <div class="browser-header-actions">
        <span id="browser-status-badge" class="status-pill pill-gray">Offline</span>
        <button id="browser-btn-restart" type="button" class="browser-hdr-btn" title="Restart Browser Session">Restart</button>
      </div>
    </div>

    <!-- Tab Strip -->
    <div class="browser-tab-strip">
      <div id="browser-tabs-list" class="browser-tabs-list"></div>
      <button id="browser-tab-new-btn" type="button" class="browser-tab-add" title="Open New Tab">+</button>
    </div>

    <!-- Navigation Bar -->
    <div class="browser-nav-bar">
      <div class="browser-nav-buttons">
        <button id="browser-btn-back" type="button" class="browser-nav-btn" title="Back" disabled>&#x25C0;</button>
        <button id="browser-btn-forward" type="button" class="browser-nav-btn" title="Forward" disabled>&#x25B6;</button>
        <button id="browser-btn-reload" type="button" class="browser-nav-btn" title="Reload">&#x21BB;</button>
        <button id="browser-btn-home" type="button" class="browser-nav-btn" title="Home (Google Messages)">&#x2302;</button>
      </div>
      <form id="browser-address-form" class="browser-address-form">
        <input id="browser-address-input" type="text" class="browser-address-input" placeholder="Enter URL (e.g. https://google.com)..." autocomplete="off" />
        <button id="browser-address-go" type="submit" class="browser-address-go-btn" title="Navigate">Go</button>
      </form>
    </div>

    <!-- Viewport -->
    <div id="browser-viewport-container" class="browser-viewport-container">
      <canvas id="archer-browser-canvas" class="archer-browser-canvas" width="1280" height="800" tabindex="0"></canvas>
      <div id="browser-empty-placeholder" class="browser-empty-placeholder">
        <div class="browser-placeholder-content">
          <div class="browser-placeholder-icon">&#x1F30E;</div>
          <h3>Chromium in Workspace</h3>
          <p>Persistent profile &bull; Pinned Messages &bull; Interactive CDP Screencast</p>
          <button id="browser-btn-start-session" type="button" class="browser-start-btn">Start Browser</button>
        </div>
      </div>
    </div>
  `;

  const canvas = document.getElementById("archer-browser-canvas");
  const ctx = canvas.getContext("2d");
  const placeholder = document.getElementById("browser-empty-placeholder");
  const statusBadge = document.getElementById("browser-status-badge");
  const tabsList = document.getElementById("browser-tabs-list");
  const btnNewTab = document.getElementById("browser-tab-new-btn");
  const btnBack = document.getElementById("browser-btn-back");
  const btnForward = document.getElementById("browser-btn-forward");
  const btnReload = document.getElementById("browser-btn-reload");
  const btnHome = document.getElementById("browser-btn-home");
  const btnRestart = document.getElementById("browser-btn-restart");
  const btnStartSession = document.getElementById("browser-btn-start-session");
  const addressForm = document.getElementById("browser-address-form");
  const addressInput = document.getElementById("browser-address-input");

  let isBrowserActive = false;
  let currentTabs = [];
  let activeTabIdx = 0;
  let lastMoveTime = 0;

  // Render screencast frame onto canvas
  const frameImg = new Image();
  let framePending = false;
  let nextFrameData = null;

  frameImg.onload = () => {
    ctx.drawImage(frameImg, 0, 0, canvas.width, canvas.height);
    framePending = false;
    if (nextFrameData) {
      const d = nextFrameData;
      nextFrameData = null;
      framePending = true;
      frameImg.src = "data:image/jpeg;base64," + d;
    }
  };

  function onScreencastFrame(msg) {
    if (!msg || !msg.data) return;
    setBrowserOnline(true);
    if (!framePending) {
      framePending = true;
      frameImg.src = "data:image/jpeg;base64," + msg.data;
    } else {
      nextFrameData = msg.data;
    }
  }

  function setBrowserOnline(online) {
    isBrowserActive = online;
    if (online) {
      statusBadge.textContent = "Online";
      statusBadge.className = "status-pill pill-green";
      placeholder.style.display = "none";
      canvas.style.display = "block";
    } else {
      statusBadge.textContent = "Offline";
      statusBadge.className = "status-pill pill-gray";
      placeholder.style.display = "flex";
      canvas.style.display = "none";
    }
  }

  function renderTabs(tabs) {
    currentTabs = tabs || [];
    tabsList.innerHTML = "";
    currentTabs.forEach((tab) => {
      const tabEl = document.createElement("div");
      tabEl.className = "browser-tab-item" + (tab.active ? " active" : "") + (tab.pinned ? " pinned" : "");
      
      const icon = document.createElement("span");
      icon.className = "browser-tab-icon";
      icon.textContent = tab.pinned ? "💬" : "📄";
      tabEl.appendChild(icon);

      const title = document.createElement("span");
      title.className = "browser-tab-title";
      title.textContent = tab.pinned ? "Messages" : (tab.title || "Tab");
      tabEl.appendChild(title);

      if (!tab.pinned) {
        const closeBtn = document.createElement("button");
        closeBtn.className = "browser-tab-close";
        closeBtn.textContent = "×";
        closeBtn.title = "Close tab";
        closeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (window.ArcherClient) {
            window.ArcherClient.sendBrowserCloseTab(tab.index);
          }
        });
        tabEl.appendChild(closeBtn);
      }

      tabEl.addEventListener("click", () => {
        if (window.ArcherClient) {
          window.ArcherClient.sendBrowserSwitchTab(tab.index);
        }
      });

      tabsList.appendChild(tabEl);
    });
  }

  function onBrowserState(state) {
    if (!state) return;
    setBrowserOnline(Boolean(state.open));
    if (state.tabs) {
      renderTabs(state.tabs);
    }
    if (state.url && document.activeElement !== addressInput) {
      addressInput.value = state.url === "about:blank" ? "" : state.url;
    }
    btnBack.disabled = !state.canGoBack;
    btnForward.disabled = !state.canGoForward;
  }

  // Mouse Coordinate Translation
  function getCanvasCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: Math.round((e.clientX - rect.left) * scaleX),
      y: Math.round((e.clientY - rect.top) * scaleY),
    };
  }

  function getButtonName(btnCode) {
    if (btnCode === 2) return "right";
    if (btnCode === 1) return "middle";
    return "left";
  }

  // Mouse Event Listeners on Canvas
  canvas.addEventListener("mousedown", (e) => {
    e.preventDefault();
    canvas.focus();
    const coords = getCanvasCoords(e);
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserMouseEvent({
        eventType: "mousePressed",
        x: coords.x,
        y: coords.y,
        button: getButtonName(e.button),
        clickCount: e.detail || 1,
      });
    }
  });

  canvas.addEventListener("mouseup", (e) => {
    e.preventDefault();
    const coords = getCanvasCoords(e);
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserMouseEvent({
        eventType: "mouseReleased",
        x: coords.x,
        y: coords.y,
        button: getButtonName(e.button),
        clickCount: e.detail || 1,
      });
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    const now = Date.now();
    if (now - lastMoveTime < 35) return; // Throttle to ~28 FPS
    lastMoveTime = now;
    const coords = getCanvasCoords(e);
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserMouseEvent({
        eventType: "mouseMoved",
        x: coords.x,
        y: coords.y,
        button: e.buttons ? getButtonName(e.button) : "none",
      });
    }
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const coords = getCanvasCoords(e);
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserMouseEvent({
        eventType: "wheel",
        x: coords.x,
        y: coords.y,
        deltaX: e.deltaX,
        deltaY: e.deltaY,
      });
    }
  }, { passive: false });

  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
  });

  // Keyboard Event Listeners
  canvas.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
    }
    if (window.ArcherClient) {
      const isChar = e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey;
      window.ArcherClient.sendBrowserKeyEvent({
        eventType: "rawKeyDown",
        key: e.key,
        code: e.code,
        text: isChar ? e.key : "",
        windowsVirtualKeyCode: e.keyCode,
      });
      if (isChar) {
        window.ArcherClient.sendBrowserInsertText(e.key);
      }
    }
  });

  canvas.addEventListener("keyup", (e) => {
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserKeyEvent({
        eventType: "keyUp",
        key: e.key,
        code: e.code,
        windowsVirtualKeyCode: e.keyCode,
      });
    }
  });

  // Touch Event Support (for mobile/tablets)
  canvas.addEventListener("touchstart", (e) => {
    if (e.touches.length === 1) {
      e.preventDefault();
      canvas.focus();
      const t = e.touches[0];
      const coords = getCanvasCoords(t);
      if (window.ArcherClient) {
        window.ArcherClient.sendBrowserMouseEvent({
          eventType: "mousePressed",
          x: coords.x,
          y: coords.y,
          button: "left",
          clickCount: 1,
        });
      }
    }
  }, { passive: false });

  canvas.addEventListener("touchmove", (e) => {
    if (e.touches.length === 1) {
      e.preventDefault();
      const t = e.touches[0];
      const coords = getCanvasCoords(t);
      if (window.ArcherClient) {
        window.ArcherClient.sendBrowserMouseEvent({
          eventType: "mouseMoved",
          x: coords.x,
          y: coords.y,
          button: "left",
        });
      }
    }
  }, { passive: false });

  canvas.addEventListener("touchend", (e) => {
    if (e.changedTouches.length === 1) {
      e.preventDefault();
      const t = e.changedTouches[0];
      const coords = getCanvasCoords(t);
      if (window.ArcherClient) {
        window.ArcherClient.sendBrowserMouseEvent({
          eventType: "mouseReleased",
          x: coords.x,
          y: coords.y,
          button: "left",
          clickCount: 1,
        });
      }
    }
  }, { passive: false });

  // Chrome Navigation Actions
  btnBack.addEventListener("click", () => {
    if (window.ArcherClient) window.ArcherClient.sendBrowserBack();
  });

  btnForward.addEventListener("click", () => {
    if (window.ArcherClient) window.ArcherClient.sendBrowserForward();
  });

  btnReload.addEventListener("click", () => {
    if (window.ArcherClient) window.ArcherClient.sendBrowserReload();
  });

  btnHome.addEventListener("click", () => {
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserNavigate("https://messages.google.com/web");
    }
  });

  btnNewTab.addEventListener("click", () => {
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserNewTab("about:blank");
    }
  });

  btnRestart.addEventListener("click", () => {
    if (window.ArcherClient) {
      setBrowserOnline(false);
      window.ArcherClient.sendBrowserRestart();
    }
  });

  btnStartSession.addEventListener("click", () => {
    if (window.ArcherClient) {
      window.ArcherClient.sendBrowserStart();
    }
  });

  addressForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const url = (addressInput.value || "").trim();
    if (url && window.ArcherClient) {
      window.ArcherClient.sendBrowserNavigate(url);
    }
  });

  // Client Event Subscriptions
  if (window.ArcherClient) {
    window.ArcherClient.on("browserScreencastFrame", onScreencastFrame);
    window.ArcherClient.on("browserState", onBrowserState);
    window.ArcherClient.on("connected", () => {
      if (window.ArcherTabs && window.ArcherTabs.getActiveTab() === "artifacts") {
        window.ArcherClient.sendBrowserScreencastVisibility(true);
        window.ArcherClient.sendBrowserGetState();
      }
    });
  }

  // Tab Visibility & Lifecycle
  function handleVisibility(active) {
    if (!window.ArcherClient) return;
    if (active) {
      window.ArcherClient.sendBrowserScreencastVisibility(true);
      window.ArcherClient.sendBrowserGetState();
    } else {
      window.ArcherClient.sendBrowserScreencastVisibility(false);
    }
  }

  window.addEventListener("archer-tab-changed", (evt) => {
    const active = evt.detail && evt.detail.activeTab === "artifacts";
    handleVisibility(active);
  });

  document.addEventListener("visibilitychange", () => {
    const isVisible = document.visibilityState === "visible";
    const isArtifacts = window.ArcherTabs && window.ArcherTabs.getActiveTab() === "artifacts";
    handleVisibility(isVisible && isArtifacts);
  });
})();
