/**
 * ARCHER browser client — R&D / Self-Development tab renderer (Phase 9, Spec Section 11b).
 *
 * Displays R&D proposals, automated dual-model coding runs, checker verdicts,
 * diff views, pre-apply backups, and one-click rollback.
 */
(() => {
  const panel = document.getElementById("tab-rnd");
  if (!panel) return;

  panel.innerHTML = `
    <div id="archer-rnd-root" class="archer-rnd-pane">
      <div class="rnd-header">
        <div class="rnd-title-group">
          <h3>ARCHER Self-Development &amp; R&amp;D</h3>
          <p class="archer-memory-hint">
            Autonomous R&amp;D coding via Antigravity in isolated worktrees.
            Dual-model review (Writer + Checker from different families), tested diffs, and instant rollback.
          </p>
        </div>
        <div class="rnd-controls">
          <button id="rnd-btn-new" type="button" class="artifact-btn btn-primary" title="Propose a new improvement or skill">+ Propose Idea</button>
          <button id="rnd-btn-undo" type="button" class="artifact-btn btn-danger" title="Restore previous repository state from backup">Undo Last Update</button>
          <button id="rnd-btn-refresh" type="button" class="artifact-btn" title="Refresh proposals list">&#x21BB; Refresh</button>
        </div>
      </div>

      <!-- New Proposal Modal / Collapsible Form -->
      <div id="rnd-form-container" class="rnd-form-wrap" style="display:none;">
        <div class="rnd-form-box">
          <h4>Propose New Code Improvement or Skill</h4>
          <div class="rnd-form-field">
            <label for="rnd-input-title">Title / Improvement</label>
            <input id="rnd-input-title" type="text" placeholder="e.g. Add weather skill with voice reporting" autocomplete="off" />
          </div>
          <div class="rnd-form-field">
            <label for="rnd-input-desc">Requirements &amp; Details</label>
            <textarea id="rnd-input-desc" rows="3" placeholder="Explain what the feature or improvement should do, what tests to add, etc."></textarea>
          </div>
          <div class="rnd-form-actions">
            <button id="rnd-btn-submit-proposal" type="button" class="artifact-btn btn-primary">Submit Proposal</button>
            <button id="rnd-btn-cancel-proposal" type="button" class="artifact-btn">Cancel</button>
          </div>
        </div>
      </div>

      <div id="rnd-feedback-banner" class="rnd-feedback" style="display:none;"></div>

      <!-- Proposals List -->
      <div class="rnd-proposals-wrap">
        <div id="rnd-proposals-list" class="rnd-proposals-grid">
          <div class="archer-memory-empty">Loading R&amp;D proposals...</div>
        </div>
      </div>
    </div>
  `;

  const proposalsList = document.getElementById("rnd-proposals-list");
  const formContainer = document.getElementById("rnd-form-container");
  const btnNew = document.getElementById("rnd-btn-new");
  const btnUndo = document.getElementById("rnd-btn-undo");
  const btnRefresh = document.getElementById("rnd-btn-refresh");
  const btnSubmit = document.getElementById("rnd-btn-submit-proposal");
  const btnCancel = document.getElementById("rnd-btn-cancel-proposal");
  const inputTitle = document.getElementById("rnd-input-title");
  const inputDesc = document.getElementById("rnd-input-desc");
  const feedbackBanner = document.getElementById("rnd-feedback-banner");

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function showFeedback(msg, isError = false) {
    if (!feedbackBanner) return;
    feedbackBanner.className = `rnd-feedback ${isError ? "error" : "success"}`;
    feedbackBanner.textContent = msg;
    feedbackBanner.style.display = "block";
    setTimeout(() => {
      if (feedbackBanner) feedbackBanner.style.display = "none";
    }, 6000);
  }

  function getStatusClass(status) {
    switch (status) {
      case "proposed": return "pill-gray";
      case "running": return "pill-blue pulse";
      case "ready_for_review": return "pill-green";
      case "applied": return "pill-purple";
      case "rejected":
      case "failed": return "pill-red";
      case "undone": return "pill-gray";
      default: return "pill-gray";
    }
  }

  function getVerdictClass(verdict) {
    switch ((verdict || "").toLowerCase()) {
      case "clear": return "verdict-clear";
      case "concerns": return "verdict-concerns";
      case "reject": return "verdict-reject";
      default: return "verdict-pending";
    }
  }

  async function fetchProposals() {
    try {
      const res = await fetch("/api/rnd/proposals");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderProposals(data.proposals || []);
    } catch (e) {
      console.warn("[RND] fetchProposals failed:", e);
      if (window.ArcherClient) {
        window.ArcherClient.send({ type: "rnd_get_proposals" });
      }
    }
  }

  function renderProposals(proposals) {
    if (!proposalsList) return;
    if (!proposals || !proposals.length) {
      proposalsList.innerHTML = '<div class="archer-memory-empty">No R&amp;D proposals yet. Click &ldquo;+ Propose Idea&rdquo; or ask ARCHER by voice.</div>';
      return;
    }

    proposalsList.innerHTML = proposals.map((p) => {
      const isRunning = p.status === "running";
      const isReady = p.status === "ready_for_review";
      const isApplied = p.status === "applied";
      const isFailed = p.status === "failed";
      const isProposed = p.status === "proposed";

      const verdict = (p.checker_verdict || "pending").toUpperCase();
      const verdictClass = getVerdictClass(p.checker_verdict);

      return `
        <div class="rnd-card" data-job-id="${escapeHtml(p.job_id)}">
          <div class="rnd-card-header">
            <div class="rnd-card-title-line">
              <span class="status-pill ${getStatusClass(p.status)}">${escapeHtml(p.status.replace(/_/g, " ").toUpperCase())}</span>
              <strong class="rnd-item-title">${escapeHtml(p.title)}</strong>
              <span class="rnd-source-badge">source: ${escapeHtml(p.source || "user")}</span>
            </div>
            <div class="rnd-card-meta">
              <code>${escapeHtml(p.job_id)}</code>
              <span>${p.created_at ? new Date(p.created_at).toLocaleString() : ""}</span>
            </div>
          </div>

          <div class="rnd-card-desc">
            ${escapeHtml(p.description || "No description provided.")}
          </div>

          <!-- Dual-Model Details (Writer + Checker) -->
          ${(p.writer_model || p.checker_model || p.checker_verdict !== "pending") ? `
            <div class="rnd-models-box">
              <div class="rnd-model-row">
                <span class="rnd-model-label">Writer AI:</span>
                <span class="rnd-model-val">${escapeHtml(p.writer_model || "gemini-4-argon-medium")} (Gemini)</span>
                <span class="rnd-model-sep">&bull;</span>
                <span class="rnd-model-label">Checker AI:</span>
                <span class="rnd-model-val">${escapeHtml(p.checker_model || "claude-sonnet-5-5-medium")} (Claude)</span>
              </div>
              <div class="rnd-verdict-row">
                <span class="rnd-verdict-label">Verdict:</span>
                <span class="rnd-verdict-badge ${verdictClass}">${escapeHtml(verdict)}</span>
                ${p.summary ? `<span class="rnd-summary-text">&mdash; ${escapeHtml(p.summary)}</span>` : ""}
              </div>
              ${p.checker_reason ? `<div class="rnd-reasons-text">${escapeHtml(p.checker_reason)}</div>` : ""}
            </div>
          ` : ""}

          <!-- Action Buttons -->
          <div class="rnd-card-actions">
            ${(isProposed || isFailed) ? `
              <button type="button" class="artifact-btn btn-primary" data-action="run" data-job-id="${escapeHtml(p.job_id)}">
                &#x25B6; Run R&amp;D (Dual-Model)
              </button>
            ` : ""}

            ${isRunning ? `
              <div class="rnd-running-indicator">
                <span class="android-step-spinner">&#x25F7;</span>
                <span>Coding in isolated worktree and running tests...</span>
              </div>
            ` : ""}

            ${(isReady || isApplied) ? `
              <button type="button" class="artifact-btn" data-action="view_diff" data-job-id="${escapeHtml(p.job_id)}" title="View tested unified diff in Artifacts tab">
                &#x1F4C4; View Diff &amp; Summary
              </button>
            ` : ""}

            ${isReady ? `
              <button type="button" class="artifact-btn btn-success" data-action="apply" data-job-id="${escapeHtml(p.job_id)}" title="Apply this update through Phase 3 approval gate">
                &#x2714; Apply Update
              </button>
            ` : ""}

            ${isApplied ? `
              <span class="rnd-applied-tag">&#x2713; Applied to live repo</span>
              <button type="button" class="artifact-btn btn-danger" data-action="undo" data-job-id="${escapeHtml(p.job_id)}" title="Rollback this update to pre-apply backup">
                Undo
              </button>
            ` : ""}
          </div>
        </div>
      `;
    }).join("");

    // Bind action buttons
    proposalsList.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        const jobId = btn.dataset.jobId;
        handleCardAction(action, jobId);
      });
    });
  }

  async function handleCardAction(action, jobId) {
    if (action === "run") {
      showFeedback(`Starting R&D run for ${jobId} in isolated worktree...`);
      try {
        const res = await fetch("/api/rnd/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: jobId }),
        });
        const data = await res.json();
        if (data.status === "failed") {
          showFeedback(`Run failed: ${data.error}`, true);
        } else {
          showFeedback(`R&D job ${jobId} is executing. You will see live updates.`);
        }
        fetchProposals();
      } catch (e) {
        showFeedback(`Failed to start job: ${e}`, true);
      }
    } else if (action === "view_diff") {
      // Switch to ARTIFACTS tab and refresh
      const artifactsTabBtn = document.querySelector('.tab-btn[data-tab="artifacts"]');
      if (artifactsTabBtn) artifactsTabBtn.click();
      setTimeout(() => {
        const refreshBtn = document.getElementById("artifacts-refresh-btn");
        if (refreshBtn) refreshBtn.click();
      }, 300);
    } else if (action === "apply") {
      showFeedback(`Applying update ${jobId} (subject to Phase 3 approval)...`);
      try {
        const res = await fetch("/api/rnd/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: jobId }),
        });
        const data = await res.json();
        if (data.status === "denied") {
          showFeedback(`Apply denied: ${data.message}`, true);
        } else if (data.status === "applied") {
          showFeedback(`Update ${jobId} applied successfully! Backed up to ${data.backup_path}. Takes effect on restart.`);
        }
        fetchProposals();
      } catch (e) {
        showFeedback(`Failed to apply update: ${e}`, true);
      }
    } else if (action === "undo") {
      if (!confirm(`Are you sure you want to undo update ${jobId} and restore files from pre-apply backup?`)) {
        return;
      }
      showFeedback(`Undoing update ${jobId}...`);
      try {
        const res = await fetch("/api/rnd/undo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: jobId }),
        });
        const data = await res.json();
        if (data.status === "undone") {
          showFeedback(`Restored previous repository state! (${(data.restored_files || []).length} files restored)`);
        } else {
          showFeedback(`Undo failed: ${data.message}`, true);
        }
        fetchProposals();
      } catch (e) {
        showFeedback(`Undo error: ${e}`, true);
      }
    }
  }

  // Toggle new proposal form
  if (btnNew) {
    btnNew.addEventListener("click", () => {
      formContainer.style.display = formContainer.style.display === "none" ? "block" : "none";
      if (formContainer.style.display === "block" && inputTitle) inputTitle.focus();
    });
  }

  if (btnCancel) {
    btnCancel.addEventListener("click", () => {
      formContainer.style.display = "none";
      if (inputTitle) inputTitle.value = "";
      if (inputDesc) inputDesc.value = "";
    });
  }

  // Submit new proposal
  if (btnSubmit) {
    btnSubmit.addEventListener("click", async () => {
      const title = (inputTitle.value || "").trim();
      const desc = (inputDesc.value || "").trim();
      if (!title) {
        alert("Please enter a title for the proposal.");
        return;
      }
      try {
        const res = await fetch("/api/rnd/propose", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, description: desc, source: "user" }),
        });
        const data = await res.json();
        showFeedback(`Proposal '${title}' recorded successfully!`);
        inputTitle.value = "";
        inputDesc.value = "";
        formContainer.style.display = "none";
        fetchProposals();
      } catch (e) {
        showFeedback(`Failed to submit proposal: ${e}`, true);
      }
    });
  }

  // Undo button in toolbar
  if (btnUndo) {
    btnUndo.addEventListener("click", async () => {
      if (!confirm("Restore previous repository state from the latest R&D pre-apply backup?")) {
        return;
      }
      showFeedback("Restoring previous state from latest backup...");
      try {
        const res = await fetch("/api/rnd/undo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const data = await res.json();
        if (data.status === "undone") {
          showFeedback(`Restored previous state! (${(data.restored_files || []).length} files restored from backup)`);
        } else {
          showFeedback(`Could not undo: ${data.message}`, true);
        }
        fetchProposals();
      } catch (e) {
        showFeedback(`Undo error: ${e}`, true);
      }
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => fetchProposals());
  }

  // WebSocket event listeners
  if (window.ArcherClient) {
    window.ArcherClient.on("rndProposalsList", (data) => renderProposals(data.proposals));
    window.ArcherClient.on("rndProposalCreated", () => fetchProposals());
    window.ArcherClient.on("rndJobStarted", () => fetchProposals());
    window.ArcherClient.on("rndJobCompleted", (data) => {
      showFeedback(`R&D Job ${data.job_id} finished: Verdict is ${data.checker_verdict.toUpperCase()}`);
      fetchProposals();
    });
    window.ArcherClient.on("rndUpdateApplied", () => fetchProposals());
    window.ArcherClient.on("rndUpdateUndone", () => fetchProposals());
    window.ArcherClient.on("connected", () => fetchProposals());
  }

  // Initial load
  fetchProposals();
})();
