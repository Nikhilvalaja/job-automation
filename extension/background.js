/**
 * Job Tracker — Background Service Worker
 *
 * Handles:
 * - Extension install/update events
 * - Default settings initialization
 *
 * SAFETY: No persistent connections. Only runs on-demand events.
 */

const DEFAULT_BACKEND = "http://localhost:8000";

// Set defaults on install
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({ backendUrl: DEFAULT_BACKEND });
    console.log("Job Tracker extension installed. Backend URL:", DEFAULT_BACKEND);
  }
});
