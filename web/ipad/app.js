/**
 * ARCHER iPad Air Gateway — Safari 12 Compatible Application.
 *
 * Strictly adheres to iOS 12 / Safari 12 JavaScript constraints:
 * - NO optional chaining (?.)
 * - NO nullish coalescing (??)
 * - NO BigInt, WebCodecs, or modern ES2020+ operators.
 */
(function () {
  "use strict";

  // State
  var token = localStorage.getItem("archer_ipad_token") || null;
  var ws = null;
  var reconnectTimer = null;
  var audioEnabled = false;
  var activeTab = "tab-chat";
  var chatMessages = [];
  var pendingApprovals = {};
  var tasksList = [];
  var habitsList = [];
  var awayList = [];
  var itemsList = [];

  // DOM Elements
  var viewPairing = document.getElementById("view-pairing");
  var viewApp = document.getElementById("view-app");
  var pairingForm = document.getElementById("pairing-form");
  var pairingInput = document.getElementById("pairing-code-input");
  var pairingError = document.getElementById("pairing-error");
  var pairingSubmitBtn = document.getElementById("pairing-submit-btn");

  var connectionStatus = document.getElementById("connection-status");
  var audioToggleBtn = document.getElementById("audio-toggle-btn");
  var unpairBtn = document.getElementById("unpair-btn");

  var chatContainer = document.getElementById("chat-messages");
  var chatForm = document.getElementById("chat-form");
  var chatInput = document.getElementById("chat-input");
  var approvalBar = document.getElementById("approval-bar");
  var navApprovalDot = document.getElementById("nav-approval-dot");

  var awayListEl = document.getElementById("away-list");
  var awayCountBadge = document.getElementById("away-count-badge");
  var tasksListEl = document.getElementById("tasks-list");
  var tasksCountBadge = document.getElementById("tasks-count-badge");
  var habitsListEl = document.getElementById("habits-list");

  var itemsGridEl = document.getElementById("items-grid");
  var itemsCountBadge = document.getElementById("items-count-badge");
  var itemSearchInput = document.getElementById("item-search-input");

  var photoModal = document.getElementById("photo-modal");
  var modalImg = document.getElementById("modal-img");
  var modalCaption = document.getElementById("modal-caption");
  var modalClose = document.getElementById("modal-close");
  var modalBackdrop = document.getElementById("modal-backdrop");

  var navTabs = document.querySelectorAll(".nav-tab");
  var contentTabs = document.querySelectorAll(".content-tab");

  // Utilities
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTime(timestamp) {
    if (!timestamp) return "";
    var d = new Date(typeof timestamp === "number" && timestamp < 1e11 ? timestamp * 1000 : timestamp);
    if (isNaN(d.getTime())) return String(timestamp);
    var hours = d.getHours();
    var mins = d.getMinutes();
    var ampm = hours >= 12 ? "PM" : "AM";
    hours = hours % 12;
    hours = hours ? hours : 12;
    var strMins = mins < 10 ? "0" + mins : String(mins);
    return hours + ":" + strMins + " " + ampm;
  }

  // ---------------------------------------------------------------------------
  // 1. View Switching & Pairing Flow
  // ---------------------------------------------------------------------------

  function showView(viewName) {
    if (viewName === "pairing") {
      viewPairing.className = "ipad-view active";
      viewApp.className = "ipad-view";
      if (pairingInput) {
        pairingInput.value = "";
        pairingInput.focus();
      }
    } else {
      viewPairing.className = "ipad-view";
      viewApp.className = "ipad-view active";
    }
  }

  function handlePairingSubmit() {
    var code = (pairingInput.value || "").replace(/\s+/g, "");
    if (!code || code.length !== 6) {
      showPairingError("Please enter the 6-digit numeric pairing code.");
      return;
    }
    showPairingError("");
    pairingSubmitBtn.disabled = true;
    pairingSubmitBtn.textContent = "Pairing...";

    fetch("/api/ipad/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code, device_name: "Col's iPad Air" }),
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (err) {
            throw new Error((err && err.detail) || "Invalid pairing code.");
          });
        }
        return res.json();
      })
      .then(function (data) {
        pairingSubmitBtn.disabled = false;
        pairingSubmitBtn.textContent = "Pair with ARCHER";
        if (data && data.token) {
          token = data.token;
          localStorage.setItem("archer_ipad_token", token);
          showView("app");
          initApp();
        } else {
          showPairingError("Unexpected server response.");
        }
      })
      .catch(function (err) {
        pairingSubmitBtn.disabled = false;
        pairingSubmitBtn.textContent = "Pair with ARCHER";
        showPairingError(err.message || "Failed to pair with ARCHER.");
      });
  }

  function showPairingError(msg) {
    if (!pairingError) return;
    if (msg) {
      pairingError.textContent = msg;
      pairingError.style.display = "block";
    } else {
      pairingError.textContent = "";
      pairingError.style.display = "none";
    }
  }

  function handleUnpair() {
    if (confirm("Disconnect this iPad from ARCHER? You will need to pair again with a 6-digit code.")) {
      if (ws) {
        try {
          ws.close();
        } catch (e) {}
      }
      token = null;
      localStorage.removeItem("archer_ipad_token");
      showView("pairing");
    }
  }

  // ---------------------------------------------------------------------------
  // 2. Navigation Tabs
  // ---------------------------------------------------------------------------

  function switchTab(tabId) {
    activeTab = tabId;
    for (var i = 0; i < navTabs.length; i++) {
      var btn = navTabs[i];
      if (btn.getAttribute("data-tab") === tabId) {
        btn.className = "nav-tab active";
      } else {
        btn.className = "nav-tab";
      }
    }
    for (var j = 0; j < contentTabs.length; j++) {
      var pane = contentTabs[j];
      if (pane.id === tabId) {
        pane.className = "content-tab active";
      } else {
        pane.className = "content-tab";
      }
    }

    if (tabId === "tab-away-tasks") {
      fetchTasks();
      fetchAway();
    } else if (tabId === "tab-items") {
      fetchItems();
    } else if (tabId === "tab-chat") {
      scrollChatToBottom();
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Audio Spoken Replies
  // ---------------------------------------------------------------------------

  function initAudioUnlock() {
    audioToggleBtn.addEventListener("click", function () {
      audioEnabled = !audioEnabled;
      if (audioEnabled) {
        audioToggleBtn.className = "header-btn audio-on";
        audioToggleBtn.querySelector(".btn-text").textContent = "Audio On";
        // Unlock HTML5 Audio on iOS Safari user tap
        try {
          var silent = new Audio("data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA");
          silent.play().catch(function () {});
        } catch (e) {}
      } else {
        audioToggleBtn.className = "header-btn audio-muted";
        audioToggleBtn.querySelector(".btn-text").textContent = "Audio Off";
      }
    });
  }

  function playSpokenReply(text) {
    if (!audioEnabled || !token || !text) return;
    try {
      var clean = text.substring(0, 300);
      var url = "/api/ipad/tts?token=" + encodeURIComponent(token) + "&text=" + encodeURIComponent(clean);
      var sound = new Audio(url);
      sound.play().catch(function (e) {
        console.log("[iPadAudio] Playback prevented", e);
      });
    } catch (e) {
      console.log("[iPadAudio] Audio error", e);
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Chat & Approvals
  // ---------------------------------------------------------------------------

  function renderChat() {
    if (!chatContainer) return;
    var html = "";
    for (var i = 0; i < chatMessages.length; i++) {
      var msg = chatMessages[i];
      var isUser = msg.role === "user";
      var cls = isUser ? "chat-bubble user" : "chat-bubble assistant";
      var author = isUser ? "You" : (msg.agent || "ARCHER");
      html += '<div class="' + cls + '">';
      html += '<div class="chat-bubble-author">' + escapeHtml(author) + ' &middot; ' + formatTime(msg.timestamp) + '</div>';
      html += '<div class="chat-bubble-text">' + escapeHtml(msg.text) + '</div>';
      html += '</div>';
    }
    chatContainer.innerHTML = html;
    scrollChatToBottom();
  }

  function addChatMessage(role, text, agent) {
    chatMessages.push({
      role: role,
      text: text,
      agent: agent || "assistant",
      timestamp: Date.now() / 1000,
    });
    renderChat();
  }

  function scrollChatToBottom() {
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  function handleChatSubmit() {
    var text = (chatInput.value || "").trim();
    if (!text) return;
    chatInput.value = "";

    // Send via WebSocket if connected, else fallback to REST
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "chat_input", text: text }));
    } else {
      addChatMessage("user", text);
      fetch("/api/ipad/chat/send", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        body: JSON.stringify({ text: text }),
      }).catch(function (e) {
        console.log("[iPadChat] REST send failed", e);
      });
    }
  }

  function renderApprovals() {
    if (!approvalBar) return;
    var reqIds = Object.keys(pendingApprovals);
    if (!reqIds.length) {
      approvalBar.style.display = "none";
      approvalBar.innerHTML = "";
      if (navApprovalDot) navApprovalDot.style.display = "none";
      return;
    }

    approvalBar.style.display = "block";
    if (navApprovalDot) navApprovalDot.style.display = "block";

    var html = "";
    for (var i = 0; i < reqIds.length; i++) {
      var reqId = reqIds[i];
      var req = pendingApprovals[reqId];
      html += '<div class="approval-card" data-req-id="' + escapeHtml(reqId) + '">';
      html += '<div class="approval-header">';
      html += '<span class="approval-tag">&#x26A0; Approval Required (' + escapeHtml(req.tool_name || "Action") + ')</span>';
      html += '<span class="approval-timer" id="timer-' + escapeHtml(reqId) + '">' + (req.remaining_seconds || 30) + 's</span>';
      html += '</div>';
      html += '<div class="approval-desc">' + escapeHtml(req.description || "Action requires approval") + '</div>';
      if (req.details) {
        html += '<div class="approval-details">' + escapeHtml(req.details) + '</div>';
      }
      html += '<div class="approval-actions">';
      html += '<button class="approval-btn approve" onclick="window.__archerRespondApproval(\'' + escapeHtml(reqId) + '\', \'approve\')">&#x2714; Approve</button>';
      html += '<button class="approval-btn deny" onclick="window.__archerRespondApproval(\'' + escapeHtml(reqId) + '\', \'deny\')">&#x2716; Deny</button>';
      html += '</div>';
      html += '</div>';
    }
    approvalBar.innerHTML = html;
  }

  window.__archerRespondApproval = function (reqId, decision) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "approval_response", request_id: reqId, decision: decision }));
    }
    fetch("/api/ipad/approvals/respond", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + token,
      },
      body: JSON.stringify({ request_id: reqId, decision: decision }),
    }).then(function () {
      delete pendingApprovals[reqId];
      renderApprovals();
    }).catch(function (e) {
      console.log("[iPadApproval] Response failed", e);
    });
  };

  // ---------------------------------------------------------------------------
  // 5. Tasks & Away Views
  // ---------------------------------------------------------------------------

  function fetchTasks() {
    if (!token) return;
    fetch("/api/ipad/tasks", {
      headers: { Authorization: "Bearer " + token },
    })
      .then(function (res) {
        if (res.status === 401) {
          handleAuthFailure();
          return null;
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        tasksList = data.tasks || [];
        habitsList = data.habits || [];
        renderTasks();
      })
      .catch(function (e) {
        console.log("[iPadTasks] Fetch failed", e);
      });
  }

  function renderTasks() {
    if (tasksCountBadge) {
      var pendingCount = 0;
      for (var i = 0; i < tasksList.length; i++) {
        if (tasksList[i].status !== "completed") pendingCount++;
      }
      tasksCountBadge.textContent = String(pendingCount);
    }

    if (tasksListEl) {
      if (!tasksList.length) {
        tasksListEl.innerHTML = '<p class="section-hint">No tasks registered.</p>';
      } else {
        var html = "";
        for (var j = 0; j < tasksList.length; j++) {
          var t = tasksList[j];
          var isCompleted = t.status === "completed";
          var cls = isCompleted ? "task-item completed" : "task-item";
          var checkMark = isCompleted ? "&#x2714;" : "";
          html += '<div class="' + cls + '" onclick="window.__archerToggleTask(' + t.id + ', ' + (!isCompleted) + ')">';
          html += '<div class="task-checkbox">' + checkMark + '</div>';
          html += '<div class="task-info">';
          html += '<div class="task-text">' + escapeHtml(t.title || t.name) + '</div>';
          if (t.due_date) {
            html += '<div class="task-due">Due: ' + escapeHtml(t.due_date) + '</div>';
          }
          html += '</div>';
          html += '</div>';
        }
        tasksListEl.innerHTML = html;
      }
    }

    if (habitsListEl) {
      if (!habitsList.length) {
        habitsListEl.innerHTML = '<p class="section-hint">No active habits.</p>';
      } else {
        var hHtml = "";
        for (var k = 0; k < habitsList.length; k++) {
          var h = habitsList[k];
          hHtml += '<div class="habit-item">';
          hHtml += '<span class="habit-name">' + escapeHtml(h.name) + '</span>';
          hHtml += '<span class="habit-streak">&#x1F525; ' + (h.streak_count || 0) + ' streak (' + escapeHtml(h.frequency || "daily") + ')</span>';
          hHtml += '</div>';
        }
        habitsListEl.innerHTML = hHtml;
      }
    }
  }

  window.__archerToggleTask = function (taskId, completed) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "task_toggle", task_id: taskId, completed: completed }));
    }
    fetch("/api/ipad/tasks/toggle", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + token,
      },
      body: JSON.stringify({ task_id: taskId, completed: completed }),
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (data && data.tasks) {
          tasksList = data.tasks;
          renderTasks();
        }
      })
      .catch(function (e) {
        console.log("[iPadTasks] Toggle failed", e);
      });
  };

  function fetchAway() {
    if (!token) return;
    fetch("/api/ipad/away", {
      headers: { Authorization: "Bearer " + token },
    })
      .then(function (res) {
        if (res.status === 401) {
          handleAuthFailure();
          return null;
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        awayList = data.interventions || [];
        renderAway();
      })
      .catch(function (e) {
        console.log("[iPadAway] Fetch failed", e);
      });
  }

  function renderAway() {
    if (awayCountBadge) awayCountBadge.textContent = String(awayList.length);
    if (!awayListEl) return;
    if (!awayList.length) {
      awayListEl.innerHTML = '<p class="section-hint">No recent interventions while you were away.</p>';
      return;
    }
    var html = "";
    for (var i = 0; i < awayList.length; i++) {
      var item = awayList[i];
      html += '<div class="away-item">';
      html += '<div class="away-item-top">';
      html += '<span class="away-category">' + escapeHtml(item.category || item.agent || "Observation") + '</span>';
      html += '<span class="away-time">' + formatTime(item.timestamp || item.created_at) + '</span>';
      html += '</div>';
      html += '<div class="away-text">' + escapeHtml(item.message || item.text || item.summary || "") + '</div>';
      html += '</div>';
    }
    awayListEl.innerHTML = html;
  }

  // ---------------------------------------------------------------------------
  // 6. Where's My... (Items)
  // ---------------------------------------------------------------------------

  function fetchItems(searchQuery) {
    if (!token) return;
    var url = "/api/ipad/items";
    if (searchQuery) url += "?query=" + encodeURIComponent(searchQuery);

    fetch(url, {
      headers: { Authorization: "Bearer " + token },
    })
      .then(function (res) {
        if (res.status === 401) {
          handleAuthFailure();
          return null;
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        itemsList = data.items || [];
        renderItems();
      })
      .catch(function (e) {
        console.log("[iPadItems] Fetch failed", e);
      });
  }

  function renderItems() {
    if (itemsCountBadge) itemsCountBadge.textContent = String(itemsList.length);
    if (!itemsGridEl) return;
    if (!itemsList.length) {
      itemsGridEl.innerHTML = '<p class="section-hint">No items found.</p>';
      return;
    }

    var html = "";
    for (var i = 0; i < itemsList.length; i++) {
      var item = itemsList[i];
      var loc = item.room ? item.room + (item.location_name ? " &middot; " + item.location_name : "") : (item.location_name || "Unknown");
      var thumbUrl = item.has_photo ? "/api/ipad/items/photo/" + item.id + "?token=" + encodeURIComponent(token) : "";

      html += '<div class="item-card">';
      html += '<div class="item-thumb-wrap">';
      if (thumbUrl) {
        html += '<img src="' + escapeHtml(thumbUrl) + '" alt="" class="item-thumb" onclick="window.__archerShowPhoto(\'' + escapeHtml(thumbUrl) + '\', \'' + escapeHtml(item.item_name) + '\')">';
      } else {
        html += '<div class="item-thumb-placeholder">&#x1F4E6;</div>';
      }
      html += '</div>';

      html += '<div class="item-details">';
      html += '<div class="item-name">' + escapeHtml(item.item_name) + '</div>';
      html += '<div class="item-location">&#x1F4CD; ' + escapeHtml(loc) + '</div>';
      if (item.last_seen_at) {
        html += '<div class="item-time">Seen: ' + formatTime(item.last_seen_at) + '</div>';
      }
      html += '</div>';
      html += '</div>';
    }
    itemsGridEl.innerHTML = html;
  }

  window.__archerShowPhoto = function (url, caption) {
    if (modalImg && photoModal) {
      modalImg.src = url;
      modalCaption.textContent = caption || "";
      photoModal.style.display = "flex";
    }
  };

  function hidePhotoModal() {
    if (photoModal) photoModal.style.display = "none";
  }

  // ---------------------------------------------------------------------------
  // 7. WebSocket Live Pipeline
  // ---------------------------------------------------------------------------

  function connectWebSocket() {
    if (!token) return;
    if (ws) {
      try {
        ws.close();
      } catch (e) {}
    }

    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = protocol + "//" + location.host + "/ws/ipad?token=" + encodeURIComponent(token);

    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      scheduleReconnect();
      return;
    }

    if (connectionStatus) {
      connectionStatus.textContent = "Connecting";
      connectionStatus.className = "status-badge connecting";
    }

    ws.onopen = function () {
      if (connectionStatus) {
        connectionStatus.textContent = "Online";
        connectionStatus.className = "status-badge online";
      }
      clearTimeout(reconnectTimer);
    };

    ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        handleWsMessage(msg);
      } catch (err) {
        console.log("[iPadWS] Parse error", err);
      }
    };

    ws.onclose = function (evt) {
      if (connectionStatus) {
        connectionStatus.textContent = "Offline";
        connectionStatus.className = "status-badge connecting";
      }
      if (evt && evt.code === 4401) {
        handleAuthFailure();
        return;
      }
      scheduleReconnect();
    };

    ws.onerror = function () {
      if (connectionStatus) {
        connectionStatus.textContent = "Offline";
        connectionStatus.className = "status-badge connecting";
      }
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(function () {
      if (token) connectWebSocket();
    }, 4000);
  }

  function handleWsMessage(msg) {
    var type = msg.type;
    if (type === "init") {
      chatMessages = msg.chat_history || [];
      renderChat();
      tasksList = msg.tasks || [];
      habitsList = msg.habits || [];
      renderTasks();
      awayList = msg.interventions || [];
      renderAway();

      var reqs = msg.pending_approvals || [];
      pendingApprovals = {};
      for (var i = 0; i < reqs.length; i++) {
        pendingApprovals[reqs[i].request_id] = reqs[i];
      }
      renderApprovals();
    } else if (type === "chat_message") {
      addChatMessage(msg.role, msg.text, msg.agent);
      if (msg.role === "assistant") {
        playSpokenReply(msg.text);
      }
    } else if (type === "approval_request") {
      pendingApprovals[msg.request_id] = msg;
      renderApprovals();
    } else if (type === "approval_resolved" || type === "approval_timeout") {
      delete pendingApprovals[msg.request_id];
      renderApprovals();
    } else if (type === "tasks_updated") {
      tasksList = msg.tasks || [];
      habitsList = msg.habits || [];
      renderTasks();
    }
  }

  function handleAuthFailure() {
    token = null;
    localStorage.removeItem("archer_ipad_token");
    if (ws) {
      try {
        ws.close();
      } catch (e) {}
    }
    showView("pairing");
    showPairingError("Pairing has been revoked or expired. Please re-pair with code on PC.");
  }

  // ---------------------------------------------------------------------------
  // 8. Initialization
  // ---------------------------------------------------------------------------

  function initApp() {
    initAudioUnlock();
    connectWebSocket();
    fetchTasks();
    fetchAway();
    fetchItems();

    // Fetch initial chat history
    fetch("/api/ipad/chat/history", {
      headers: { Authorization: "Bearer " + token },
    })
      .then(function (res) {
        if (res.status === 401) {
          handleAuthFailure();
          return null;
        }
        return res.json();
      })
      .then(function (data) {
        if (data && data.messages) {
          chatMessages = data.messages;
          renderChat();
        }
      })
      .catch(function () {});

    // Fetch pending approvals
    fetch("/api/ipad/approvals", {
      headers: { Authorization: "Bearer " + token },
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (data && data.requests) {
          pendingApprovals = {};
          for (var i = 0; i < data.requests.length; i++) {
            pendingApprovals[data.requests[i].request_id] = data.requests[i];
          }
          renderApprovals();
        }
      })
      .catch(function () {});
  }

  // Wire event listeners
  if (pairingForm) {
    pairingForm.addEventListener("submit", handlePairingSubmit);
  }
  if (unpairBtn) {
    unpairBtn.addEventListener("click", handleUnpair);
  }
  if (chatForm) {
    chatForm.addEventListener("submit", handleChatSubmit);
  }

  if (itemSearchInput) {
    itemSearchInput.addEventListener("input", function () {
      var q = itemSearchInput.value || "";
      fetchItems(q);
    });
  }

  if (modalClose) modalClose.addEventListener("click", hidePhotoModal);
  if (modalBackdrop) modalBackdrop.addEventListener("click", hidePhotoModal);

  // Wire tab clicks
  for (var i = 0; i < navTabs.length; i++) {
    (function (btn) {
      btn.addEventListener("click", function () {
        var tabId = btn.getAttribute("data-tab");
        switchTab(tabId);
      });
    })(navTabs[i]);
  }

  // Countdown timer ticker for active approval prompts
  setInterval(function () {
    var reqIds = Object.keys(pendingApprovals);
    for (var i = 0; i < reqIds.length; i++) {
      var req = pendingApprovals[reqIds[i]];
      if (req.remaining_seconds && req.remaining_seconds > 0) {
        req.remaining_seconds--;
        var timerEl = document.getElementById("timer-" + req.request_id);
        if (timerEl) timerEl.textContent = req.remaining_seconds + "s";
      }
    }
  }, 1000);

  // Start app
  if (token) {
    showView("app");
    initApp();
  } else {
    showView("pairing");
  }
})();
