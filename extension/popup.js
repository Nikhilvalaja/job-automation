/**
 * Job Tracker Pro — Popup Script v2
 *
 * Features:
 * - Tab navigation (Add Job / Recent / Settings)
 * - Quick stats dashboard
 * - Auto-extract from content script
 * - Duplicate detection warning
 * - Today's application count badge
 * - Backend health check
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
const duplicateWarning = document.getElementById("duplicate-warning");
const recentDiv = document.getElementById("recent-jobs");
const recentCount = document.getElementById("recent-count");
const refreshBtn = document.getElementById("refresh-btn");
const backendUrlInput = document.getElementById("backend-url");
const saveSettingsBtn = document.getElementById("save-settings");
const statusDot = document.getElementById("status-dot");
const todayCountEl = document.getElementById("today-count");

// Stat elements
const statTotal = document.getElementById("stat-total");
const statApplied = document.getElementById("stat-applied");
const statInterview = document.getElementById("stat-interview");
const statOffer = document.getElementById("stat-offer");

// --- Tab Navigation ---
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

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
        if (chrome.runtime.lastError) return;
        if (response?.company && !companyInput.value) companyInput.value = response.company;
        if (response?.role && !roleInput.value) roleInput.value = response.role;
        if (response?.source && !sourceInput.value) sourceInput.value = response.source;

        // Auto-fill notes with extracted details
        if (response && !notesInput.value) {
          const parts = [];
          if (response.salary) parts.push(`Salary: ${response.salary}`);
          if (response.location) parts.push(`Location: ${response.location}`);
          if (response.jobType) parts.push(response.jobType);
          if (response.skills?.length) parts.push(`Skills: ${response.skills.slice(0, 5).join(", ")}`);
          notesInput.value = parts.join(" | ");
        }
      });
    }
  } catch (e) {
    // Ignore
  }

  checkBackend(settings.backendUrl);
  loadStats(settings.backendUrl);
  loadRecentJobs(settings.backendUrl);
  loadTodayCount();
  checkDuplicate(settings.backendUrl);
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
    statusDot.title = "Backend unreachable — start with: uvicorn backend.main:app --reload";
  }
}

// --- Today Count ---
async function loadTodayCount() {
  try {
    chrome.runtime.sendMessage({ action: "getBadgeCount" }, (response) => {
      if (response?.count !== undefined) {
        todayCountEl.textContent = `${response.count} today`;
      }
    });
  } catch {
    // Ignore
  }
}

// --- Quick Stats ---
async function loadStats(baseUrl) {
  try {
    const resp = await fetch(`${baseUrl}/jobs`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return;
    const data = await resp.json();
    const jobs = data.jobs || [];

    statTotal.textContent = jobs.length;
    statApplied.textContent = jobs.filter((j) => j.status === "Applied").length;
    statInterview.textContent = jobs.filter((j) => j.status === "Interview").length;
    statOffer.textContent = jobs.filter((j) => j.status === "Offer").length;
  } catch {
    // Stats stay as —
  }
}

// --- Detect Source from URL ---
function detectSource(url) {
  const sources = {
    "linkedin.com": "LinkedIn", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor",
    "lever.co": "Lever", "greenhouse.io": "Greenhouse", "myworkdayjobs.com": "Workday",
    "ziprecruiter.com": "ZipRecruiter", "wellfound.com": "Wellfound", "angel.co": "Wellfound",
    "dice.com": "Dice", "monster.com": "Monster", "builtin.com": "BuiltIn",
    "simplyhired.com": "SimplyHired", "careerbuilder.com": "CareerBuilder",
  };
  for (const [domain, name] of Object.entries(sources)) {
    if (url.includes(domain)) { sourceInput.value = name; return; }
  }
}

// --- Duplicate Check ---
async function checkDuplicate(baseUrl) {
  const url = jobUrlInput.value;
  if (!url) return;
  try {
    const resp = await fetch(`${baseUrl}/jobs`, { signal: AbortSignal.timeout(3000) });
    if (!resp.ok) return;
    const data = await resp.json();
    const dup = (data.jobs || []).find((j) => j.job_url === url);
    if (dup) {
      duplicateWarning.classList.remove("hidden");
      duplicateWarning.textContent = `Already tracked: "${dup.company} / ${dup.role}" (${dup.status})`;
    }
  } catch {
    // Ignore
  }
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
      showMessage(`Tracked: ${job.company} / ${job.role}`, "success");
      form.reset();
      jobUrlInput.value = payload.job_url;
      loadRecentJobs(settings.backendUrl);
      loadStats(settings.backendUrl);

      // Update badge
      chrome.runtime.sendMessage({ action: "jobTracked", job: payload });
      loadTodayCount();
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
    const jobs = (data.jobs || []).slice(0, 8);

    recentCount.textContent = `${data.jobs?.length || 0} total jobs`;

    if (jobs.length === 0) {
      recentDiv.innerHTML = '<div class="no-jobs">No tracked jobs yet. Add your first one!</div>';
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
    recentDiv.innerHTML = '<div class="no-jobs">Could not load jobs. Is the backend running?</div>';
    recentCount.textContent = "—";
  }
}

refreshBtn.addEventListener("click", async () => {
  const settings = await getSettings();
  loadRecentJobs(settings.backendUrl);
  loadStats(settings.backendUrl);
  loadTodayCount();
});

// --- Open Dashboard ---
document.getElementById("open-dashboard")?.addEventListener("click", () => {
  chrome.tabs.create({ url: "http://localhost:8501" });
});

// --- Helpers ---
function showMessage(text, type) {
  messageDiv.textContent = text;
  messageDiv.className = `message ${type}`;
}

function hideMessage() { messageDiv.className = "message hidden"; }

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
