/**
 * ARCHER browser client — WebSocket bridge.
 *
 * Connects to the same FastAPI server that already serves this page
 * (see archer/server.py) and dispatches typed events to listeners.
 * See ../CONTRACT.md for the full message schema.
 *
 * This file is functional plumbing, not the visual layer — orb.js (or
 * whatever replaces it) is where the design work happens. Avoid rewriting
 * this file unless the WebSocket contract itself changes.
 */

const ArcherClient = (() => {
  const listeners = {
    state: [],
    amplitude: [],
    sttPartial: [],
    sttFinal: [],
    assistantLine: [],
    wakeWord: [],
    mode: [],
    halt: [],
    micMute: [],
    ttsMute: [],
    observerCamera: [],
    switchTab: [],
    logLine: [],
    memorySnapshot: [],
    tasksSnapshot: [],
    systemSnapshot: [],
    browserScreenshot: [],
    hello: [],
    cameraFrameRequest: [],
    connected: [],
    disconnected: [],
  };

  let socket = null;
  let reconnectDelayMs = 1000;
  const MAX_RECONNECT_DELAY_MS = 10000;

  function emit(eventName, payload) {
    (listeners[eventName] || []).forEach((fn) => {
      try {
        fn(payload);
      } catch (err) {
        console.error(`[ArcherClient] listener for "${eventName}" threw:`, err);
      }
    });
  }

  function handleMessage(raw) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    switch (msg.type) {
      case "state":
        emit("state", msg.state);
        break;
      case "amplitude":
        emit("amplitude", msg.value);
        break;
      case "stt_partial":
        emit("sttPartial", msg.text);
        break;
      case "stt_final":
        emit("sttFinal", msg.text);
        break;
      case "agent_response":
        emit("assistantLine", { text: msg.text, agent: msg.agent });
        break;
      case "assistant_line":
        emit("assistantLine", { text: msg.text, agent: null });
        break;
      case "agent_response_start":
        // Informational only (elapsed seconds) — no dedicated listener yet;
        // surface via the "state" == "processing" visual instead.
        break;
      case "agent_switch":
        // Informational — fold into future needs if the visual wants it.
        break;
      case "wake_word":
        emit("wakeWord");
        break;
      case "mode":
        emit("mode", msg.mode);
        break;
      case "halt":
        emit("halt");
        break;
      case "mic_mute":
        emit("micMute", msg.muted);
        break;
      case "tts_mute":
        emit("ttsMute", msg.muted);
        break;
      case "observer_camera":
        emit("observerCamera", msg.released);
        break;
      case "camera_frame_request":
        emit("cameraFrameRequest", { requestId: msg.request_id });
        break;
      case "switch_tab":
        emit("switchTab", msg.tab);
        break;
      case "log_line":
        emit("logLine", msg.text);
        break;
      case "artifact_push":
        // A tool result that included an image (currently just
        // take_screenshot) -- 2026-09-19, Col's ask: the screenshot was
        // only ever reaching the model, never shown to him. See
        // core_agent.py's _publish_tool_screenshot.
        emit("artifactPush", { imageB64: msg.image_b64 || "", kind: msg.kind || "", title: msg.title || "" });
        break;
      case "memory_snapshot":
        // Relationship/social tracking + pattern-recognition output for
        // the MEMORY tab (2026-09-16) -- see CONTRACT.md.
        emit("memorySnapshot", {
          contacts: msg.contacts || [],
          commitments: msg.commitments || [],
          entities: msg.entities || [],
          patterns: msg.patterns || [],
          interventions: msg.interventions || [],
          pendingPeople: msg.pending_people || [],
        });
        break;
      case "tasks_snapshot":
        // Tasks + habits for the TASKS tab (2026-09-16) -- see CONTRACT.md.
        // Re-broadcast after every write, from any surface (browser tab or
        // a voice/text tool call), so this always reflects live state.
        emit("tasksSnapshot", { tasks: msg.tasks || [], habits: msg.habits || [] });
        break;
      case "system_snapshot":
        // GPU/VRAM + per-instance loaded-model residency + available local
        // models + audio devices, for the SYSTEM tab (2026-09-16) -- see
        // CONTRACT.md and server.py's _build_system_snapshot.
        emit("systemSnapshot", {
          gpu: msg.gpu || null,
          cpu: msg.cpu || null,
          tokensPerSec: msg.tokens_per_sec,
          ollamaLoaded: msg.ollama_loaded || [],
          availableModels: msg.available_models || [],
          currentModel: msg.current_model || null,
          micDevices: msg.mic_devices || [],
          speakerDevices: msg.speaker_devices || [],
          currentMicIndex: msg.current_mic_index,
          currentSpeakerIndex: msg.current_speaker_index,
        });
        break;
      case "browser_screenshot":
        // Mirror of ARCHER's own Playwright-driven browser (2026-09-16) --
        // see CONTRACT.md's Browser pane section.
        emit("browserScreenshot", { imageB64: msg.image_b64 || null, active: !!msg.active });
        break;
      case "hello":
        emit("hello", {
          mode: msg.mode,
          micMuted: msg.mic_muted,
          ttsMuted: msg.tts_muted,
          cameraReleased: msg.camera_released,
          cameraAvailable: msg.camera_available,
        });
        break;
      case "system_start":
        break;
      default:
        console.warn("[ArcherClient] unknown message type:", msg.type);
    }
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
      return;
    }
    const url = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/voice`;
    socket = new WebSocket(url);

    socket.addEventListener("open", () => {
      reconnectDelayMs = 1000;
      console.log("[ArcherClient] connected");
      emit("connected");
    });

    socket.addEventListener("message", (event) => handleMessage(event.data));

    socket.addEventListener("close", () => {
      console.warn(`[ArcherClient] disconnected — retrying in ${reconnectDelayMs}ms`);
      emit("disconnected");
      setTimeout(connect, reconnectDelayMs);
      reconnectDelayMs = Math.min(reconnectDelayMs * 1.5, MAX_RECONNECT_DELAY_MS);
    });

    socket.addEventListener("error", (err) => {
      console.warn("[ArcherClient] WebSocket error:", err);
    });
  }

  function send(obj) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(obj));
    }
  }

  return {
    get readyState() {
      return socket ? socket.readyState : -1;
    },
    on(eventName, handler) {
      if (!listeners[eventName]) {
        throw new Error(`[ArcherClient] unknown event "${eventName}"`);
      }
      listeners[eventName].push(handler);
      if (eventName === "connected" && socket && socket.readyState === WebSocket.OPEN) {
        try {
          handler();
        } catch (err) {
          console.error(`[ArcherClient] listener for "${eventName}" threw:`, err);
        }
      }
    },
    sendText(text) {
      send({ type: "text_input", text });
    },
    sendHalt() {
      send({ type: "halt" });
    },
    sendModeToggle() {
      send({ type: "mode_toggle" });
    },
    sendMicMuteToggle() {
      send({ type: "mic_mute_toggle" });
    },
    sendTtsMuteToggle() {
      send({ type: "tts_mute_toggle" });
    },
    sendCameraFrameResponse(requestId, imageB64) {
      send({ type: "camera_frame_response", request_id: requestId, image_b64: imageB64 });
    },
    sendRequestCameraFrame() {
      send({ type: "request_camera_frame" });
    },
    sendMemoryGetAll() {
      send({ type: "memory_get_all" });
    },
    sendMemoryAddContact(name, relationship, typicalIntervalDays) {
      send({
        type: "memory_add_contact",
        name,
        relationship: relationship || null,
        typical_interval_days: typicalIntervalDays || null,
      });
    },
    sendMemoryLogInteraction(contactName, interactionType, notes) {
      send({
        type: "memory_log_interaction",
        contact_name: contactName,
        interaction_type: interactionType || "in-person",
        notes: notes || null,
      });
    },
    sendMemoryAddCommitment(contactName, promise, dueDate) {
      send({
        type: "memory_add_commitment",
        contact_name: contactName,
        promise,
        due_date: dueDate || null,
      });
    },
    sendMemoryResolveCommitment(commitmentId, fulfilled) {
      send({ type: "memory_resolve_commitment", commitment_id: commitmentId, fulfilled: fulfilled !== false });
    },
    sendMemoryConfirmPerson(id, name) {
      send({ type: "memory_confirm_person", id, name });
    },
    sendMemoryDismissPerson(id) {
      send({ type: "memory_dismiss_person", id });
    },
    sendTasksGetAll() {
      send({ type: "tasks_get_all" });
    },
    sendTasksAdd(title, dueDate) {
      send({ type: "tasks_add", title, due_date: dueDate || null });
    },
    sendTasksComplete(taskId) {
      send({ type: "tasks_complete", task_id: taskId });
    },
    sendTasksDelete(taskId) {
      send({ type: "tasks_delete", task_id: taskId });
    },
    sendHabitsAdd(name, frequency) {
      send({ type: "habits_add", name, frequency: frequency || "daily" });
    },
    sendHabitsComplete(name) {
      send({ type: "habits_complete", name });
    },
    sendHabitsDelete(name) {
      send({ type: "habits_delete", name });
    },
    sendSystemGetAll() {
      send({ type: "system_get_all" });
    },
    sendSystemSwitchMic(deviceIndex) {
      send({ type: "system_switch_mic", device_index: deviceIndex });
    },
    sendSystemSwitchSpeaker(deviceIndex) {
      send({ type: "system_switch_speaker", device_index: deviceIndex });
    },
    sendSystemSwitchModel(model) {
      send({ type: "system_switch_model", model });
    },
    sendBrowserGetScreenshot() {
      send({ type: "browser_get_screenshot" });
    },
    connect,
  };
})();

// Exposed on window (not just the module-local const) because every other
// file in this client -- system.js, memory.js, tasks.js, logs.js,
// browser.js, orb.js -- reaches this through `window.ArcherClient`, always
// behind an `if (window.ArcherClient)` guard for load-order safety. Without
// this assignment that guard was ALWAYS false: none of those files' event
// listeners ever registered and none of their send*() calls ever fired,
// which is why the SYSTEM dropdowns/performance charts/GPU info never
// populated, and why Logs/Memory/Tasks only ever showed their static empty
// state -- found and fixed 2026-09-16 while chasing exactly that complaint.
window.ArcherClient = ArcherClient;

document.addEventListener("DOMContentLoaded", () => ArcherClient.connect());
