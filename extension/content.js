/**
 * Job Tracker Pro — Content Script
 *
 * Features:
 * 1. Floating "Track" button on all job pages — one click saves everything
 * 2. Auto-detect "Apply" button clicks — auto-tracks when you apply
 * 3. Preview panel — shows all extracted details before saving
 * 4. Toast notifications — visual feedback on all actions
 * 5. Duplicate detection — warns if job URL already tracked
 *
 * SAFETY: Never modifies existing page content. Only injects overlay UI.
 * Never submits forms, clicks buttons, or navigates on behalf of the user.
 */

(() => {
  "use strict";

  const DEFAULT_BACKEND = "http://localhost:8000";
  let backendUrl = DEFAULT_BACKEND;
  let lastExtractedData = null;
  let isTracked = false;

  // --- Init ---
  async function init() {
    // Load settings
    try {
      const settings = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND });
      backendUrl = settings.backendUrl;
    } catch (e) {
      // Extension context might not be available
    }

    injectFloatingButton();
    setupApplyDetection();
    checkIfAlreadyTracked();
  }

  // --- Floating Track Button ---
  function injectFloatingButton() {
    if (document.getElementById("jt-floating-btn")) return;

    const btn = document.createElement("button");
    btn.id = "jt-floating-btn";
    btn.innerHTML = "+";
    btn.setAttribute("data-tooltip", "Track this job (Ctrl+Shift+J)");
    btn.addEventListener("click", onFloatingButtonClick);
    document.body.appendChild(btn);
  }

  async function onFloatingButtonClick() {
    const btn = document.getElementById("jt-floating-btn");
    if (!btn || isTracked) return;

    // Extract data
    lastExtractedData = JobTrackerExtractors.extract();

    // Show preview panel
    showPreviewPanel(lastExtractedData);
  }

  // --- Preview Panel ---
  function showPreviewPanel(data) {
    // Remove existing panel
    const existing = document.getElementById("jt-preview-panel");
    if (existing) existing.remove();

    const panel = document.createElement("div");
    panel.id = "jt-preview-panel";

    const skillsHtml = (data.skills || []).length > 0
      ? data.skills.map((s) => `<span class="jt-skill-tag">${escapeHtml(s)}</span>`).join("")
      : '<span class="jt-value jt-empty">None detected</span>';

    panel.innerHTML = `
      <div class="jt-panel-header">
        <h3>Track This Job</h3>
        <button class="jt-panel-close" id="jt-panel-close">&times;</button>
      </div>
      <div class="jt-panel-body">
        <div class="jt-panel-field">
          <label>Company</label>
          <input type="text" id="jt-company" value="${escapeAttr(data.company)}" placeholder="Company name">
        </div>
        <div class="jt-panel-field">
          <label>Role</label>
          <input type="text" id="jt-role" value="${escapeAttr(data.role)}" placeholder="Job title">
        </div>
        <div class="jt-panel-field">
          <label>Source</label>
          <input type="text" id="jt-source" value="${escapeAttr(data.source || "")}" readonly>
        </div>
        <div class="jt-panel-field">
          <label>Location</label>
          <div class="jt-value ${data.location ? "" : "jt-empty"}">${escapeHtml(data.location || "Not found")}</div>
        </div>
        <div class="jt-panel-field">
          <label>Salary</label>
          <div class="jt-value ${data.salary ? "" : "jt-empty"}">${escapeHtml(data.salary || "Not listed")}</div>
        </div>
        <div class="jt-panel-field">
          <label>Job Type</label>
          <div class="jt-value ${data.jobType ? "" : "jt-empty"}">${escapeHtml(data.jobType || "Not specified")}</div>
        </div>
        <div class="jt-panel-field">
          <label>Skills Found</label>
          <div class="jt-skills-list">${skillsHtml}</div>
        </div>
        <div class="jt-panel-field">
          <label>Status</label>
          <select id="jt-status">
            <option value="To Apply">To Apply</option>
            <option value="Applied" selected>Applied</option>
            <option value="Assessment">Assessment</option>
            <option value="Interview">Interview</option>
          </select>
        </div>
        <div class="jt-panel-field">
          <label>Notes</label>
          <input type="text" id="jt-notes" placeholder="Optional notes..."
            value="${escapeAttr(buildAutoNotes(data))}">
        </div>
      </div>
      <div class="jt-panel-actions">
        <button class="jt-btn-primary" id="jt-save-btn">Save Job</button>
        <button class="jt-btn-secondary" id="jt-cancel-btn">Cancel</button>
      </div>
    `;

    document.body.appendChild(panel);

    // Trigger open animation
    requestAnimationFrame(() => panel.classList.add("jt-open"));

    // Event listeners
    document.getElementById("jt-panel-close").addEventListener("click", closePreviewPanel);
    document.getElementById("jt-cancel-btn").addEventListener("click", closePreviewPanel);
    document.getElementById("jt-save-btn").addEventListener("click", () => saveFromPanel(data));
  }

  function closePreviewPanel() {
    const panel = document.getElementById("jt-preview-panel");
    if (panel) {
      panel.classList.remove("jt-open");
      setTimeout(() => panel.remove(), 300);
    }
  }

  function buildAutoNotes(data) {
    const parts = [];
    if (data.salary) parts.push(`Salary: ${data.salary}`);
    if (data.location) parts.push(`Location: ${data.location}`);
    if (data.jobType) parts.push(data.jobType);
    if (data.applicants) parts.push(data.applicants);
    return parts.join(" | ");
  }

  async function saveFromPanel(data) {
    const company = document.getElementById("jt-company")?.value.trim();
    const role = document.getElementById("jt-role")?.value.trim();
    const source = document.getElementById("jt-source")?.value.trim();
    const status = document.getElementById("jt-status")?.value;
    const notes = document.getElementById("jt-notes")?.value.trim();

    if (!company || !role) {
      showToast("Company and Role are required", "error");
      return;
    }

    const saveBtn = document.getElementById("jt-save-btn");
    if (saveBtn) {
      saveBtn.textContent = "Saving...";
      saveBtn.disabled = true;
    }

    const payload = {
      company,
      role,
      source,
      job_url: data.url || window.location.href,
      status,
      notes,
    };

    const success = await trackJob(payload);

    if (success) {
      closePreviewPanel();
      markAsTracked();
      showToast(`Tracked: ${company} / ${role}`, "success");

      // Notify background to update badge
      chrome.runtime.sendMessage({ action: "jobTracked", job: payload });
    } else {
      if (saveBtn) {
        saveBtn.textContent = "Save Job";
        saveBtn.disabled = false;
      }
    }
  }

  // --- Apply Button Detection ---
  function setupApplyDetection() {
    const selectors = JobTrackerExtractors.getApplyButtonSelectors();

    // Use MutationObserver to catch dynamically loaded apply buttons
    const observer = new MutationObserver(() => {
      for (const selector of selectors) {
        const buttons = document.querySelectorAll(selector);
        buttons.forEach((btn) => {
          if (btn.dataset.jtWatched) return;
          btn.dataset.jtWatched = "true";

          btn.addEventListener("click", () => {
            // Delay to let the application process start
            setTimeout(() => onApplyDetected(), 2000);
          });
        });
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });

    // Also check existing buttons
    for (const selector of selectors) {
      const buttons = document.querySelectorAll(selector);
      buttons.forEach((btn) => {
        if (btn.dataset.jtWatched) return;
        btn.dataset.jtWatched = "true";

        btn.addEventListener("click", () => {
          setTimeout(() => onApplyDetected(), 2000);
        });
      });
    }
  }

  async function onApplyDetected() {
    if (isTracked) return;

    const data = JobTrackerExtractors.extract();
    if (!data.company && !data.role) return;

    // Show auto-track notification
    showToast(`Detected application to ${data.company || "unknown"}. Tracking...`, "info");

    const payload = {
      company: data.company,
      role: data.role,
      source: data.source || "",
      job_url: data.url || window.location.href,
      status: "Applied",
      notes: buildAutoNotes(data),
    };

    const success = await trackJob(payload);
    if (success) {
      markAsTracked();
      showToast(`Auto-tracked: ${data.company} / ${data.role}`, "success");
      chrome.runtime.sendMessage({ action: "jobTracked", job: payload });
    }
  }

  // --- Duplicate Check ---
  async function checkIfAlreadyTracked() {
    const url = window.location.href;
    try {
      const resp = await fetch(`${backendUrl}/jobs`, { signal: AbortSignal.timeout(3000) });
      if (!resp.ok) return;
      const data = await resp.json();
      const jobs = data.jobs || [];
      const match = jobs.find((j) => j.job_url === url);
      if (match) {
        markAsTracked();
        showApplyBadge(`Already tracked: ${match.status}`);
      }
    } catch {
      // Backend not reachable — ignore
    }
  }

  // --- API Call ---
  async function trackJob(payload) {
    try {
      // Check for duplicate first
      const checkResp = await fetch(`${backendUrl}/jobs`, { signal: AbortSignal.timeout(5000) });
      if (checkResp.ok) {
        const existing = await checkResp.json();
        const dup = (existing.jobs || []).find((j) => j.job_url === payload.job_url);
        if (dup) {
          showToast(`Already tracked as "${dup.status}"`, "warning");
          markAsTracked();
          return false;
        }
      }

      const resp = await fetch(`${backendUrl}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(5000),
      });

      if (resp.status === 201) return true;

      const err = await resp.text();
      showToast(`Error: ${resp.status} — ${err}`, "error");
      return false;
    } catch (e) {
      showToast(`Cannot reach backend: ${e.message}`, "error");
      return false;
    }
  }

  // --- UI Helpers ---
  function markAsTracked() {
    isTracked = true;
    const btn = document.getElementById("jt-floating-btn");
    if (btn) {
      btn.innerHTML = "&#10003;";
      btn.classList.add("jt-tracked");
      btn.setAttribute("data-tooltip", "Job tracked!");
    }
  }

  function showApplyBadge(text) {
    if (document.getElementById("jt-apply-badge")) return;
    const badge = document.createElement("div");
    badge.id = "jt-apply-badge";
    badge.textContent = text;
    document.body.appendChild(badge);
  }

  function showToast(message, type = "info") {
    // Remove existing toast
    const existing = document.getElementById("jt-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "jt-toast";
    toast.className = `jt-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("jt-show"));

    setTimeout(() => {
      toast.classList.remove("jt-show");
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return (str || "").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // --- Message Listener (for popup requests) ---
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "extract") {
      const data = JobTrackerExtractors.extract();
      sendResponse(data);
    } else if (request.action === "quickTrack") {
      onFloatingButtonClick();
      sendResponse({ ok: true });
    }
  });

  // --- Start ---
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
