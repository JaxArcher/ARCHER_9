/**
 * ARCHER browser client — SYSTEM card + always-visible controls bar.
 *
 * Added 2026-09-16 after Col hand-diagnosed a ~100s local-model response
 * delay via `ollama ps` / `nvidia-smi` in a terminal, then asked for this
 * to just be a tab: live camera feed, GPU/VRAM headroom + which
 * Ollama-loaded models are actually resident on GPU vs silently offloaded
 * to CPU, a dropdown to switch the local "brain" model, and dropdowns to
 * hot-swap the mic/speaker device without restarting ARCHER.
 *
 * Restructured the same day (second pass, per Col's follow-up: "the model
 * and audio switches...instead of at the top of the screen"): the
 * model/mic/speaker dropdowns now build into #archer-controls-bar, a
 * separate always-visible strip above the scrollable dashboard grid,
 * instead of living inside the (sometimes tall, sometimes scrolled)
 * System card. Camera/GPU/performance still build into #tab-system, now a
 * sidebar in the primary row (see ui.css/index.html).
 *
 * The Performance section was Chart.js-based sparklines until this same
 * pass -- dropped in favor of small self-contained SVG ring gauges (no
 * CDN dependency, which is very likely WHY they never rendered for Col:
 * an unreachable/blocked CDN would silently degrade to empty boxes via
 * the old code's own `typeof Chart === "undefined"` guard, and there'd be
 * no error visible anywhere in ARCHER's own logs to explain it).
 *
 * Loads lazily the first time the WebSocket connects, then polls
 * system_get_all every 4s WHILE the Dashboard tab is actually visible --
 * stops polling and detaches the camera <img> the moment you switch to
 * Gesture, so this doesn't burn bandwidth/CPU in the background forever.
 */
(() => {
  const panel = document.getElementById("tab-system");
  const controlsBar = document.getElementById("archer-controls-bar");
  if (!panel || !controlsBar) return;

  panel.innerHTML = `
    <section class="archer-memory-pane" id="archer-system-gpu-pane">
      <h3>GPU / VRAM</h3>
      <div id="archer-system-gpu-info"></div>
      <h4>Loaded on Ollama</h4>
      <p class="archer-memory-hint">The browser equivalent of running <code>ollama ps</code> yourself -- size_vram vs size shows whether a model is actually resident on GPU or has been silently offloaded to CPU (which is what a slow first response usually means).</p>
      <div id="archer-system-ollama-loaded"></div>
    </section>

    <section class="archer-memory-pane" id="archer-system-charts-pane">
      <h3>Performance</h3>
      <p class="archer-memory-hint">Updated every 4s. Tokens/sec only moves when a local-model turn actually finishes generating.</p>
      <div class="archer-gauge-row" id="archer-gauge-row"></div>
    </section>
  `;

  controlsBar.innerHTML = `
    <div class="archer-control" id="archer-control-model">
      <label for="archer-system-model-select">Brain Model</label>
      <select id="archer-system-model-select"></select>
    </div>
    <div class="archer-control" id="archer-control-mic">
      <label for="archer-system-mic-select">Microphone</label>
      <select id="archer-system-mic-select"></select>
    </div>
    <div class="archer-control" id="archer-control-speaker">
      <label for="archer-system-speaker-select">Speaker</label>
      <select id="archer-system-speaker-select"></select>
    </div>
  `;

  const gpuInfo = document.getElementById("archer-system-gpu-info");
  const ollamaLoadedList = document.getElementById("archer-system-ollama-loaded");
  const gaugeRow = document.getElementById("archer-gauge-row");
  const modelSelect = document.getElementById("archer-system-model-select");
  const micSelect = document.getElementById("archer-system-mic-select");
  const speakerSelect = document.getElementById("archer-system-speaker-select");

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderGpu(gpu) {
    if (!gpu) {
      gpuInfo.innerHTML = '<p class="archer-memory-empty">No GPU detected (or pynvml unreachable).</p>';
      return;
    }
    const pct = Math.round((gpu.used_mb / gpu.total_mb) * 100);
    gpuInfo.innerHTML = `
      <div class="archer-memory-row">
        <div class="archer-memory-row-main"><strong>${escapeHtml(gpu.name)}</strong></div>
        <div class="archer-system-vram-bar"><div class="archer-system-vram-bar-fill" style="width:${pct}%"></div></div>
        <div class="archer-memory-row-sub">${gpu.used_mb} MB / ${gpu.total_mb} MB VRAM used (${pct}%) &middot; GPU util ${gpu.gpu_util_pct}%${gpu.temp_c != null ? ` &middot; ${gpu.temp_c}&deg;C` : ""}</div>
      </div>
    `;
  }

  function renderOllamaLoaded(models) {
    if (!models.length) {
      ollamaLoadedList.innerHTML = '<p class="archer-memory-empty">Nothing loaded into Ollama right now.</p>';
      return;
    }
    ollamaLoadedList.innerHTML = models.map((m) => {
      const size = m.size || 0;
      const vram = m.size_vram || 0;
      const vramPct = size ? Math.round((vram / size) * 100) : 0;
      const onGpu = vramPct >= 99;
      return `
        <div class="archer-memory-row">
          <div class="archer-memory-row-main">
            <strong>${escapeHtml(m.name || m.model)}</strong>
            <span class="archer-memory-tag">${escapeHtml(m.instance)}</span>
            <span class="archer-memory-tag archer-memory-status-${onGpu ? "delivered" : "pending"}">${onGpu ? "100% GPU" : vramPct + "% GPU / " + (100 - vramPct) + "% CPU"}</span>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderModelSelect(available, current) {
    if (document.activeElement === modelSelect) return;
    if (!available || available.length === 0) {
      if (current) {
        modelSelect.innerHTML = `<option value="${escapeHtml(current)}" selected>${escapeHtml(current)}</option>`;
      } else {
        modelSelect.innerHTML = '<option value="" disabled selected>None found</option>';
      }
      return;
    }
    let html = available.map((m) =>
      `<option value="${escapeHtml(m)}" ${m === current ? "selected" : ""}>${escapeHtml(m)}</option>`
    ).join("");
    if (current && !available.includes(current)) {
      html = `<option value="${escapeHtml(current)}" selected>${escapeHtml(current)}</option>` + html;
    }
    modelSelect.innerHTML = html;
  }

  function renderDeviceSelect(select, devices, currentIndex) {
    if (document.activeElement === select) return;
    if (!devices || devices.length === 0) {
      select.innerHTML = '<option value="" disabled selected>None found</option>';
      return;
    }
    const hasMatch = currentIndex != null && devices.some(d => d.index === currentIndex);
    let html = "";
    if (!hasMatch) {
      html += `<option value="" disabled ${currentIndex == null ? "selected" : ""}>Select device...</option>`;
    }
    html += devices.map((d) =>
      `<option value="${d.index}" ${d.index === currentIndex ? "selected" : ""}>${escapeHtml(d.name)}</option>`
    ).join("");
    select.innerHTML = html;
  }

  // Initial state before server snapshot arrives
  modelSelect.innerHTML = '<option value="" disabled selected>Loading...</option>';
  micSelect.innerHTML = '<option value="" disabled selected>Loading...</option>';
  speakerSelect.innerHTML = '<option value="" disabled selected>Loading...</option>';

  // Self-contained SVG ring gauges (2026-09-16, replacing Chart.js -- no
  // CDN dependency, so nothing to silently fail to load). Each gauge is a
  // stroked circle whose dash-offset encodes value/max as a fraction of
  // the circumference, rotated -90deg (via CSS) so it fills clockwise
  // from the top like a normal loading ring.
  const GAUGES = [
    { key: "gpuUtil", label: "GPU", unit: "%", max: 100, color: "#86f7df" },
    { key: "vram", label: "VRAM", unit: "%", max: 100, color: "#7fd9ff" },
    { key: "gpuTemp", label: "TEMP", unit: "°C", max: 90, color: "#ffb86c" },
    { key: "cpuUtil", label: "CPU", unit: "%", max: 100, color: "#ff8fa3" },
    { key: "tokens", label: "TOK/S", unit: "", max: 80, color: "#c9f6ff" },
  ];
  const R = 32;
  const CIRC = 2 * Math.PI * R;

  function gaugeSvg(g) {
    return `
      <div class="archer-gauge" id="archer-gauge-${g.key}">
        <svg viewBox="0 0 76 76" class="archer-gauge-svg">
          <circle cx="38" cy="38" r="${R}" class="archer-gauge-track" />
          <circle cx="38" cy="38" r="${R}" class="archer-gauge-fill" stroke="${g.color}"
            stroke-dasharray="${CIRC}" stroke-dashoffset="${CIRC}" data-circ="${CIRC}" />
          <text x="38" y="35" class="archer-gauge-value" data-unit="${g.unit}">--</text>
          <text x="38" y="49" class="archer-gauge-unit">${g.unit}</text>
        </svg>
        <div class="archer-gauge-label">${g.label}</div>
      </div>
    `;
  }

  let gaugesBuilt = false;
  function ensureGauges() {
    if (gaugesBuilt) return;
    gaugesBuilt = true;
    gaugeRow.innerHTML = GAUGES.map(gaugeSvg).join("");
  }

  function setGauge(key, value, max, unit) {
    const wrap = document.getElementById(`archer-gauge-${key}`);
    if (!wrap) return;
    const fill = wrap.querySelector(".archer-gauge-fill");
    const text = wrap.querySelector(".archer-gauge-value");
    if (value === null || value === undefined) {
      fill.style.strokeDashoffset = CIRC;
      text.textContent = "--";
      return;
    }
    const pct = Math.max(0, Math.min(1, value / max));
    fill.style.strokeDashoffset = String(CIRC * (1 - pct));
    text.textContent = unit === "%" || unit === "" ? Math.round(value) : Math.round(value * 10) / 10;
  }

  function renderGauges(data) {
    ensureGauges();
    const vramPct = data.gpu ? Math.round((data.gpu.used_mb / data.gpu.total_mb) * 100) : null;
    setGauge("gpuUtil", data.gpu ? data.gpu.gpu_util_pct : null, 100, "%");
    setGauge("vram", vramPct, 100, "%");
    setGauge("gpuTemp", data.gpu ? data.gpu.temp_c : null, 90, "°C");
    setGauge("cpuUtil", data.cpu ? data.cpu.cpu_util_pct : null, 100, "%");
    setGauge("tokens", data.tokensPerSec, 80, "");
  }

  let modelSelectWired = false;
  let deviceSelectsWired = false;

  function render(data) {
    renderGpu(data.gpu);
    renderOllamaLoaded(data.ollamaLoaded);
    renderGauges(data);
    renderModelSelect(data.availableModels, data.currentModel);
    renderDeviceSelect(micSelect, data.micDevices, data.currentMicIndex);
    renderDeviceSelect(speakerSelect, data.speakerDevices, data.currentSpeakerIndex);

    if (!modelSelectWired) {
      modelSelectWired = true;
      modelSelect.addEventListener("change", () => {
        window.ArcherClient.sendSystemSwitchModel(modelSelect.value);
      });
    }
    if (!deviceSelectsWired) {
      deviceSelectsWired = true;
      micSelect.addEventListener("change", () => {
        window.ArcherClient.sendSystemSwitchMic(parseInt(micSelect.value, 10));
      });
      speakerSelect.addEventListener("change", () => {
        window.ArcherClient.sendSystemSwitchSpeaker(parseInt(speakerSelect.value, 10));
      });
    }
  }

  if (window.ArcherClient) {
    window.ArcherClient.on("systemSnapshot", render);
  }

  // Camera feed + polling only run while the Dashboard is genuinely
  // visible -- an MJPEG <img> keeps its HTTP connection open indefinitely
  // otherwise, and there's no reason to poll GPU/device state for a tab
  // nobody's looking at. The controls bar itself stays visible/populated
  // regardless (it's outside #archer-tab-content), so switching to
  // Gesture just pauses the live numbers, not the dropdowns' last-known
  // state.
  let pollTimer = null;
  function startLive() {
    if (window.ArcherClient) window.ArcherClient.sendSystemGetAll();
    if (!pollTimer) {
      pollTimer = setInterval(() => {
        if (window.ArcherClient) window.ArcherClient.sendSystemGetAll();
      }, 4000);
    }
  }
  function stopLive() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Phase 1 Redesign (2026-10-06): Poll GPU / VRAM / model stats strictly while SYSTEM tab is active.
  window.addEventListener("archer-tab-changed", (evt) => {
    const active = evt.detail && evt.detail.activeTab;
    if (active === "system") startLive();
    else stopLive();
  });

  if (window.ArcherClient) {
    window.ArcherClient.on("connected", () => {
      // Request initial snapshot on load so controls bar dropdowns (Brain Model, Mic, Speaker) populate immediately regardless of active tab
      window.ArcherClient.sendSystemGetAll();
      if (window.ArcherTabs && window.ArcherTabs.getActiveTab() === "system") {
        startLive();
      }
    });
  }
})();


