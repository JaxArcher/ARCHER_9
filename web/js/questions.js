/**
 * ARCHER "I Have Questions" Tab (Spec Section 5f, Col 2026-10-22).
 *
 * All follow-up questions from ARCHER (unrecognised people, unnamed items, task clarifications)
 * live in this tab as interactive cards.
 * Tab turns amber with count badge when questions are open.
 */
(() => {
  const container = document.getElementById("archer-questions-container");
  const tabBtn = document.getElementById("tab-btn-questions");
  if (!container || !tabBtn) return;

  let currentQuestions = [];
  let openCount = 0;
  let activeMediaRecorder = null;
  let audioChunks = [];
  let recordingQid = null;

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function updateTabBadge(count) {
    openCount = Math.max(0, parseInt(count, 10) || 0);
    if (openCount > 0) {
      tabBtn.classList.add("tab-amber");
      tabBtn.textContent = `I HAVE QUESTIONS (${openCount})`;
    } else {
      tabBtn.classList.remove("tab-amber");
      tabBtn.textContent = "I HAVE QUESTIONS";
    }
  }

  function renderCard(q, isLater = false) {
    const qid = q.question_id;
    const sourceLabel = q.source === "person" ? "Person Sighting" : (q.source === "item" ? "Item" : "Follow-Up");
    const sourceClass = q.source === "person" ? "badge-person" : (q.source === "item" ? "badge-item" : "badge-general");
    
    // Images
    const imgs = q.images || [];
    const imagesHtml = imgs.length ? `
      <div class="question-images">
        ${imgs.map(uri => `<img class="question-thumb" src="${uri}" alt="Context Photo" />`).join("")}
      </div>
    ` : "";

    // Threaded messages
    const threads = q.threads || [];
    const threadsHtml = threads.length ? `
      <div class="question-thread-list">
        ${threads.map(t => `
          <div class="question-thread-item ${t.source === 'archer' ? 'from-archer' : 'from-user'}">
            <span class="thread-author">${t.source === 'archer' ? 'ARCHER:' : 'You:'}</span>
            <span class="thread-text">${escapeHtml(t.text || t.answer_text)}</span>
          </div>
        `).join("")}
      </div>
    ` : "";

    // Answered display
    const isAnswered = (q.status === "answered");
    const answeredHtml = isAnswered ? `
      <div class="question-answered-banner">
        <span class="answered-icon">&#x2714;</span> Answered: <em>${escapeHtml(q.answer_text)}</em>
      </div>
    ` : "";

    const isRecordingThis = (recordingQid === qid);

    return `
      <div class="question-card ${isLater ? 'card-later' : ''} ${isAnswered ? 'card-answered' : ''}" data-qid="${qid}">
        <div class="question-card-header">
          <div class="question-badge-wrap">
            <span class="question-badge ${sourceClass}">${escapeHtml(sourceLabel)}</span>
            ${q.subject_ref ? `<span class="question-subject-ref">${escapeHtml(q.subject_ref)}</span>` : ""}
          </div>
          <div class="question-header-actions">
            ${!isLater && !isAnswered ? `
              <button class="question-btn btn-later" data-action="later" data-qid="${qid}" title="Review later -- keeps card visible without amber glow">Review Later</button>
            ` : ""}
            <button class="question-btn btn-delete" data-action="delete" data-qid="${qid}" title="Dismiss permanently">&#x2715; Dismiss</button>
          </div>
        </div>

        <div class="question-card-body">
          ${imagesHtml}
          <div class="question-content">
            <div class="question-context-line">${escapeHtml(q.context || "")}</div>
            <div class="question-prompt-text">${escapeHtml(q.text)}</div>
            ${threadsHtml}
            ${answeredHtml}
          </div>
        </div>

        ${!isAnswered ? `
          <div class="question-card-footer">
            <form class="question-reply-form" data-qid="${qid}">
              <div class="question-input-group">
                <button type="button" class="question-mic-btn ${isRecordingThis ? 'recording' : ''}" data-qid="${qid}" title="Speak your response">
                  ${isRecordingThis ? '🔴 Recording...' : '🎤 Speak'}
                </button>
                <input type="text" class="question-text-input" placeholder="Type your response..." autocomplete="off" />
                <button type="submit" class="question-send-btn">Send</button>
              </div>
            </form>
          </div>
        ` : ""}
      </div>
    `;
  }

  function renderView() {
    const openList = currentQuestions.filter(q => q.status === "open");
    const laterList = currentQuestions.filter(q => q.status === "later");
    const answeredList = currentQuestions.filter(q => q.status === "answered");

    let html = `
      <div class="questions-header-bar">
        <div class="questions-title-wrap">
          <h3 class="questions-main-title">I HAVE QUESTIONS</h3>
          <span class="questions-subtitle">Everything ARCHER follows up on lives here — no photos or questions in the chat box.</span>
        </div>
        <div class="questions-controls">
          <button id="questions-btn-refresh" class="question-btn btn-secondary">Refresh</button>
        </div>
      </div>
    `;

    // Open Questions
    html += `<div class="questions-section">`;
    html += `<h4 class="questions-section-title">Open Questions (${openList.length})</h4>`;
    if (!openList.length) {
      html += `
        <div class="questions-empty-card">
          <span class="empty-icon">&#x2705;</span>
          <div class="empty-text">No open questions right now.</div>
          <div class="empty-subtext">ARCHER will raise cards here when visitors, items, or clarifications arise.</div>
        </div>
      `;
    } else {
      html += `<div class="questions-cards-grid">${openList.map(q => renderCard(q, false)).join("")}</div>`;
    }
    html += `</div>`;

    // Review Later
    if (laterList.length) {
      html += `
        <div class="questions-section later-section">
          <h4 class="questions-section-title">Review Later (${laterList.length})</h4>
          <div class="questions-cards-grid">${laterList.map(q => renderCard(q, true)).join("")}</div>
        </div>
      `;
    }

    // Answered Recent
    if (answeredList.length) {
      html += `
        <div class="questions-section answered-section">
          <details class="questions-collapsible">
            <summary class="questions-section-title">Recently Answered (${answeredList.length})</summary>
            <div class="questions-cards-grid">${answeredList.slice(0, 10).map(q => renderCard(q, false)).join("")}</div>
          </details>
        </div>
      `;
    }

    container.innerHTML = html;
    bindActions();
  }

  function bindActions() {
    // Refresh
    const refreshBtn = document.getElementById("questions-btn-refresh");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => loadQuestions());
    }

    // Submit text replies
    container.querySelectorAll(".question-reply-form").forEach(form => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const qid = form.dataset.qid;
        const input = form.querySelector(".question-text-input");
        const val = (input ? input.value : "").trim();
        if (!val) return;
        await submitResponse(qid, val);
      });
    });

    // Review Later buttons
    container.querySelectorAll(".question-btn[data-action='later']").forEach(btn => {
      btn.addEventListener("click", async () => {
        const qid = btn.dataset.qid;
        await markLater(qid);
      });
    });

    // Delete buttons
    container.querySelectorAll(".question-btn[data-action='delete']").forEach(btn => {
      btn.addEventListener("click", async () => {
        const qid = btn.dataset.qid;
        if (confirm("Dismiss this question card permanently?")) {
          await deleteQuestion(qid);
        }
      });
    });

    // Mic recording buttons
    container.querySelectorAll(".question-mic-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const qid = btn.dataset.qid;
        toggleMic(qid, btn);
      });
    });
  }

  async function loadQuestions() {
    try {
      const res = await fetch("/api/questions");
      if (res.ok) {
        const data = await res.json();
        currentQuestions = data.questions || [];
        updateTabBadge(data.open_count);
        renderView();
      }
    } catch (e) {
      console.warn("[archer] Failed to load questions:", e);
    }
  }

  async function submitResponse(qid, text) {
    try {
      const res = await fetch(`/api/questions/${encodeURIComponent(qid)}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response: text }),
      });
      if (res.ok) {
        await loadQuestions();
      } else {
        alert("Failed to submit response.");
      }
    } catch (e) {
      console.warn("[archer] Failed to respond to question:", e);
    }
  }

  async function markLater(qid) {
    try {
      const res = await fetch(`/api/questions/${encodeURIComponent(qid)}/later`, { method: "POST" });
      if (res.ok) {
        await loadQuestions();
      }
    } catch (e) {
      console.warn("[archer] Failed to mark question later:", e);
    }
  }

  async function deleteQuestion(qid) {
    try {
      const res = await fetch(`/api/questions/${encodeURIComponent(qid)}/delete`, { method: "POST" });
      if (res.ok) {
        await loadQuestions();
      }
    } catch (e) {
      console.warn("[archer] Failed to delete question:", e);
    }
  }

  async function toggleMic(qid, btn) {
    if (activeMediaRecorder && activeMediaRecorder.state === "recording") {
      // Stop recording
      activeMediaRecorder.stop();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      recordingQid = qid;
      btn.classList.add("recording");
      btn.textContent = "🔴 Recording...";

      activeMediaRecorder = new MediaRecorder(stream);
      activeMediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
      };
      activeMediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        btn.classList.remove("recording");
        btn.textContent = "⏳ Transcribing...";
        recordingQid = null;

        const blob = new Blob(audioChunks, { type: "audio/webm" });

        try {
          const transRes = await fetch("/api/questions/transcribe", {
            method: "POST",
            headers: { "Content-Type": "audio/webm" },
            body: blob,
          });
          if (transRes.ok) {
            const data = await transRes.json();
            const text = (data.text || "").trim();
            const form = container.querySelector(`.question-reply-form[data-qid="${qid}"]`);
            if (form) {
              const input = form.querySelector(".question-text-input");
              if (input && text) {
                input.value = text;
                input.focus();
              }
            }
          }
        } catch (err) {
          console.warn("[archer] Transcription error:", err);
        } finally {
          btn.textContent = "🎤 Speak";
        }
      };

      activeMediaRecorder.start();
    } catch (err) {
      console.warn("[archer] Could not open microphone for question response:", err);
      alert("Microphone access failed. Please type your response.");
      btn.textContent = "🎤 Speak";
      recordingQid = null;
    }
  }

  // Initial load
  loadQuestions();

  // Switch tab event
  window.addEventListener("archer-tab-changed", (evt) => {
    if (evt.detail && evt.detail.activeTab === "questions") {
      loadQuestions();
    }
  });

  // WebSocket live updates
  if (window.ArcherClient) {
    window.ArcherClient.on("questions_count", (data) => {
      if (data && typeof data.open_count !== "undefined") {
        updateTabBadge(data.open_count);
      }
    });
    window.ArcherClient.on("questions_updated", () => {
      loadQuestions();
    });
  }
})();
