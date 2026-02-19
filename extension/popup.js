/**
 * Job Tracker — Chrome Extension Popup
 *
 * Handles:
 * - Auto-fill job URL from current tab
 * - Auto-extract company/role from content script
 * - Add job via backend API (POST /jobs)
 * - Display recent tracked jobs (GET /jobs)
 * - Backend connection status indicator
 */

const DEFAULT_BACKEND = "http://localhost:8000";

// --- DOM Elements ---
const form = document.getElementById("add-form");
const companyInput = document.getElementById("company");
const roleInput = document.getElementById("role");
const sourceInput = document.getElementById("source");
const jobUrlInput = document.getElementById("job-url");
const statusSelect = document.getElementById("job-status");
const notesInput = document.getElementById("notes");
const addBtn = document.getElementById("add-btn");
const messageDiv = document.getElementById("message");
const recentDiv = document.getElementById("recent-jobs");
const refreshBtn = document.getElementById("refresh-btn");
const backendUrlInput = document.getElementById("backend-url");
const saveSettingsBtn = document.getElementById("save-settings");
const statusDot = document.getElementById("status-dot");

// --- Init ---
document.addEventListener("DOMContentLoaded", async () => {
  const settings = await getSettings();
  backendUrlInput.value = settings.backendUrl;

  // Auto-fill URL from current tab
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url) {
      jobUrlInput.value = tab.url;
      detectSource(tab.url);
    }

    // Try to get extracted data from content script
    if (tab?.id) {
      chrome.tabs.sendMessage(tab.id, { action: "extract" }, (response) => {
        if (chrome.runtime.lastError) return; // Content script not loaded
        if (response?.company && !companyInput.value) companyInput.value = response.company;
        if (response?.role && !roleInput.value) roleInput.value = response.role;
      });
    }
  } catch (e) {
    // Ignore — might not have tab permission
  }

  checkBackend(settings.backendUrl);
  loadRecentJobs(settings.backendUrl);
});

// --- Settings ---
async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND }, resolve);
  });
}

saveSettingsBtn.addEventListener("click", async () => {
  const url = backendUrlInput.value.trim().replace(/\/+$/, "");
  await chrome.storage.local.set({ backendUrl: url || DEFAULT_BACKEND });
  showMessage("Settings saved!", "success");
  checkBackend(url || DEFAULT_BACKEND);
});

// --- Backend Health Check ---
async function checkBackend(baseUrl) {
  try {
    const resp = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(3000) });
    if (resp.ok) {
      statusDot.className = "dot dot-connected";
      statusDot.title = "Backend connected";
    } else {
      throw new Error("Not OK");
    }
  } catch {
    statusDot.className = "dot dot-disconnected";
    statusDot.title = "Backend unreachable";
  }
}

// --- Detect Source from URL ---
function detectSource(url) {
  if (url.includes("linkedin.com")) sourceInput.value = "LinkedIn";
  else if (url.includes("indeed.com")) sourceInput.value = "Indeed";
  else if (url.includes("glassdoor.com")) sourceInput.value = "Glassdoor";
  else if (url.includes("lever.co")) sourceInput.value = "Lever";
  else if (url.includes("greenhouse.io")) sourceInput.value = "Greenhouse";
  else if (url.includes("myworkdayjobs.com")) sourceInput.value = "Workday";
}

// --- Add Job ---
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  addBtn.disabled = true;
  addBtn.textContent = "Adding...";
  hideMessage();

  const settings = await getSettings();
  const payload = {
    company: companyInput.value.trim(),
    role: roleInput.value.trim(),
    source: sourceInput.value.trim(),
    job_url: jobUrlInput.value.trim(),
    status: statusSelect.value,
    notes: notesInput.value.trim(),
  };

  try {
    const resp = await fetch(`${settings.backendUrl}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(5000),
    });

    if (resp.status === 201) {
      const job = await resp.json();
      showMessage(`Added: ${job.company} / ${job.role}`, "success");
      form.reset();
      jobUrlInput.value = payload.job_url; // Keep the URL
      loadRecentJobs(settings.backendUrl);
    } else {
      const err = await resp.text();
      showMessage(`Error: ${resp.status} — ${err}`, "error");
    }
  } catch (err) {
    showMessage(`Cannot reach backend: ${err.message}`, "error");
  } finally {
    addBtn.disabled = false;
    addBtn.textContent = "Track This Job";
  }
});

// --- Load Recent Jobs ---
async function loadRecentJobs(baseUrl) {
  try {
    const resp = await fetch(`${baseUrl}/jobs`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) throw new Error(`${resp.status}`);

    const data = await resp.json();
    const jobs = (data.jobs || []).slice(0, 5); // Show last 5

    if (jobs.length === 0) {
      recentDiv.innerHTML = '<div class="no-jobs">No tracked jobs yet.</div>';
      return;
    }

    recentDiv.innerHTML = jobs
      .map((job) => {
        const badgeClass = getBadgeClass(job.status);
        return `
          <div class="job-card">
            <div class="job-title">${escapeHtml(job.company)} — ${escapeHtml(job.role)}</div>
            <div class="job-meta">
              <span class="status-badge ${badgeClass}">${escapeHtml(job.status)}</span>
              ${job.source ? ` &middot; ${escapeHtml(job.source)}` : ""}
              ${job.date_applied ? ` &middot; ${escapeHtml(job.date_applied)}` : ""}
            </div>
          </div>
        `;
      })
      .join("");
  } catch {
    recentDiv.innerHTML = '<div class="no-jobs">Could not load jobs.</div>';
  }
}

refreshBtn.addEventListener("click", async () => {
  const settings = await getSettings();
  loadRecentJobs(settings.backendUrl);
});

// --- Helpers ---
function showMessage(text, type) {
  messageDiv.textContent = text;
  messageDiv.className = `message ${type}`;
}

function hideMessage() {
  messageDiv.className = "message hidden";
}

function getBadgeClass(status) {
  const s = (status || "").toLowerCase();
  if (s === "applied") return "applied";
  if (s === "interview") return "interview";
  if (s === "offer") return "offer";
  if (s.includes("reject") || s === "no reply") return "rejected";
  if (s === "assessment") return "assessment";
  return "default";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}
