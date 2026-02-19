/**
 * Job Tracker — Content Script
 *
 * Runs on job posting pages (LinkedIn, Indeed, Glassdoor, Lever, Greenhouse, Workday).
 * Extracts company name and role title from the page DOM.
 *
 * SAFETY: Read-only. Never modifies the page DOM or submits forms.
 */

(() => {
  "use strict";

  /**
   * Extract job details from the current page based on the hostname.
   * Returns { company, role } or empty strings if not found.
   */
  function extractJobDetails() {
    const host = window.location.hostname;
    let company = "";
    let role = "";

    try {
      if (host.includes("linkedin.com")) {
        // LinkedIn job posting page
        role =
          getText(".job-details-jobs-unified-top-card__job-title h1") ||
          getText(".top-card-layout__title") ||
          getText("h1.t-24") ||
          getText("h1");
        company =
          getText(".job-details-jobs-unified-top-card__company-name a") ||
          getText(".topcard__org-name-link") ||
          getText("a.topcard__org-name-link") ||
          getText(".job-details-jobs-unified-top-card__company-name");
      } else if (host.includes("indeed.com")) {
        // Indeed job posting
        role =
          getText('[data-testid="jobsearch-JobInfoHeader-title"]') ||
          getText(".jobsearch-JobInfoHeader-title") ||
          getText("h1.icl-u-xs-mb--xs");
        company =
          getText('[data-testid="inlineHeader-companyName"]') ||
          getText('[data-company-name="true"]') ||
          getText(".icl-u-lg-mr--sm");
      } else if (host.includes("glassdoor.com")) {
        // Glassdoor job listing
        role = getText('[data-test="job-title"]') || getText("h1");
        company =
          getText('[data-test="employer-name"]') ||
          getText(".employerName");
      } else if (host.includes("lever.co")) {
        // Lever job posting
        role = getText("h2.posting-headline") || getText("h2");
        company = getText(".posting-categories .sort-by-team") || getText(".main-header-logo img")?.alt || "";
      } else if (host.includes("greenhouse.io")) {
        // Greenhouse job board
        role = getText("h1.app-title") || getText("h1");
        company = getText(".company-name") || "";
      } else if (host.includes("myworkdayjobs.com")) {
        // Workday job posting
        role = getText('[data-automation-id="jobPostingHeader"]') || getText("h2");
        company = getText('[data-automation-id="headerText"]') || "";
      } else {
        // Generic fallback: try common patterns
        role = getText("h1");
        // Try to find company in meta tags
        const metaCompany = document.querySelector('meta[property="og:site_name"]');
        if (metaCompany) company = metaCompany.content;
      }
    } catch (e) {
      // Silently fail — don't break the page
    }

    return {
      company: clean(company),
      role: clean(role),
    };
  }

  /**
   * Get text content of the first matching element.
   */
  function getText(selector) {
    const el = document.querySelector(selector);
    return el ? el.textContent : "";
  }

  /**
   * Clean extracted text: trim whitespace, collapse spaces, limit length.
   */
  function clean(str) {
    if (!str) return "";
    return str.replace(/\s+/g, " ").trim().slice(0, 200);
  }

  // Listen for messages from the popup
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "extract") {
      sendResponse(extractJobDetails());
    }
  });
})();
