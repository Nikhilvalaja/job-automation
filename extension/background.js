/**
 * Job Tracker Pro — Background Service Worker
 *
 * Handles:
 * - Context menu "Track This Job" (right-click on any page)
 * - Badge counter (today's applications on extension icon)
 * - Keyboard shortcut handler (Ctrl+Shift+J)
 * - Chrome notifications for tracked jobs
 * - Daily badge reset
 *
 * SAFETY: No persistent connections. Only event-driven.
 */

const DEFAULT_BACKEND = "http://localhost:8000";

// --- Context Menu ---
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ backendUrl: DEFAULT_BACKEND, todayCount: 0, todayDate: today() });

  chrome.contextMenus.create({
    id: "track-job",
    title: "Track This Job",
    contexts: ["page", "link"],
  });

  chrome.contextMenus.create({
    id: "track-job-separator",
    type: "separator",
    contexts: ["page"],
  });

  chrome.contextMenus.create({
    id: "open-dashboard",
    title: "Open Dashboard",
    contexts: ["page"],
  });

  updateBadge();
});

// Context menu click handler
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "track-job") {
    // Send message to content script to open preview panel
    try {
      chrome.tabs.sendMessage(tab.id, { action: "quickTrack" });
    } catch {
      // Content script not loaded on this page — open popup instead
      chrome.action.openPopup();
    }
  } else if (info.menuItemId === "open-dashboard") {
    chrome.tabs.create({ url: "http://localhost:8501" });
  }
});

// --- Keyboard Shortcut ---
chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "quick-track") {
    try {
      chrome.tabs.sendMessage(tab.id, { action: "quickTrack" });
    } catch {
      chrome.action.openPopup();
    }
  }
});

// --- Badge Counter ---
function today() {
  return new Date().toISOString().slice(0, 10);
}

async function updateBadge() {
  const data = await chrome.storage.local.get({ todayCount: 0, todayDate: today() });

  // Reset counter if it's a new day
  if (data.todayDate !== today()) {
    await chrome.storage.local.set({ todayCount: 0, todayDate: today() });
    data.todayCount = 0;
  }

  const count = data.todayCount;
  if (count > 0) {
    chrome.action.setBadgeText({ text: String(count) });
    chrome.action.setBadgeBackgroundColor({ color: "#2563eb" });
  } else {
    chrome.action.setBadgeText({ text: "" });
  }
}

async function incrementBadge() {
  const data = await chrome.storage.local.get({ todayCount: 0, todayDate: today() });

  if (data.todayDate !== today()) {
    await chrome.storage.local.set({ todayCount: 1, todayDate: today() });
  } else {
    await chrome.storage.local.set({ todayCount: data.todayCount + 1 });
  }

  updateBadge();
}

// --- Message Handler (from content scripts) ---
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "jobTracked") {
    incrementBadge();

    // Show Chrome notification
    const job = message.job || {};
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title: "Job Tracked!",
      message: `${job.company || "Unknown"} — ${job.role || "Unknown"}\nStatus: ${job.status || "Applied"}`,
    });

    sendResponse({ ok: true });
  }

  if (message.action === "getBadgeCount") {
    chrome.storage.local.get({ todayCount: 0, todayDate: today() }, (data) => {
      const count = data.todayDate === today() ? data.todayCount : 0;
      sendResponse({ count });
    });
    return true; // Keep channel open for async response
  }

  if (message.action === "getBackendUrl") {
    chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND }, (data) => {
      sendResponse({ backendUrl: data.backendUrl });
    });
    return true;
  }
});

// Update badge on startup
updateBadge();
