/**
 * Job Tracker Pro — Site-Specific Extractors
 *
 * Modular extraction engine. Each extractor knows how to pull
 * job details from a specific job board's DOM structure.
 *
 * To add a new site: add a new entry to EXTRACTORS with a `match` regex
 * and an `extract()` function that returns a JobDetails object.
 *
 * SAFETY: Read-only. Never modifies the page DOM.
 */

/* global JobTrackerExtractors */
// eslint-disable-next-line no-unused-vars
const JobTrackerExtractors = (() => {
  "use strict";

  // --- Helpers ---
  function getText(selector) {
    const el = document.querySelector(selector);
    return el ? el.textContent.trim() : "";
  }

  function getTexts(selector) {
    return Array.from(document.querySelectorAll(selector))
      .map((el) => el.textContent.trim())
      .filter(Boolean);
  }

  function getMeta(name) {
    const el =
      document.querySelector(`meta[property="${name}"]`) ||
      document.querySelector(`meta[name="${name}"]`);
    return el ? el.content.trim() : "";
  }

  function clean(str) {
    if (!str) return "";
    return str.replace(/\s+/g, " ").trim().slice(0, 500);
  }

  function getDescriptionText() {
    // Try common job description containers
    const selectors = [
      ".job-description",
      '[data-testid="job-description"]',
      ".description__text",
      ".jobsearch-jobDescriptionText",
      "#job-details",
      ".posting-page .content",
      '[class*="description"]',
      '[class*="job-details"]',
      "article",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim().length > 100) {
        return el.textContent.trim().slice(0, 5000);
      }
    }
    return "";
  }

  // --- Extractors ---

  const EXTRACTORS = [
    {
      name: "LinkedIn",
      match: /linkedin\.com/,
      extract() {
        return {
          company:
            clean(getText(".job-details-jobs-unified-top-card__company-name a")) ||
            clean(getText(".topcard__org-name-link")) ||
            clean(getText(".job-details-jobs-unified-top-card__company-name")),
          role:
            clean(getText(".job-details-jobs-unified-top-card__job-title h1")) ||
            clean(getText(".top-card-layout__title")) ||
            clean(getText("h1")),
          location:
            clean(getText(".job-details-jobs-unified-top-card__bullet")) ||
            clean(getText(".topcard__flavor--bullet")),
          salary:
            clean(getText(".salary-main-rail__current-range")) ||
            clean(getText('[class*="compensation"]')) ||
            extractSalaryFromText(),
          jobType:
            clean(getText(".job-details-jobs-unified-top-card__workplace-type")) ||
            detectJobType(),
          description: getDescriptionText(),
          skills: extractLinkedInSkills(),
          postedDate: clean(getText(".posted-time-ago__text")) || clean(getText('[class*="posted"]')),
          applicants: clean(getText('[class*="num-applicants"]')) || clean(getText('[class*="applicant"]')),
        };
      },
    },
    {
      name: "Indeed",
      match: /indeed\.com/,
      extract() {
        return {
          company:
            clean(getText('[data-testid="inlineHeader-companyName"]')) ||
            clean(getText('[data-company-name="true"]')) ||
            clean(getText(".jobsearch-InlineCompanyRating-companyHeader")),
          role:
            clean(getText('[data-testid="jobsearch-JobInfoHeader-title"]')) ||
            clean(getText(".jobsearch-JobInfoHeader-title")),
          location:
            clean(getText('[data-testid="inlineHeader-companyLocation"]')) ||
            clean(getText('[data-testid="job-location"]')),
          salary:
            clean(getText("#salaryInfoAndJobType .attribute_snippet")) ||
            clean(getText('[class*="salary"]')) ||
            extractSalaryFromText(),
          jobType: clean(getText('[class*="jobtype"]')) || detectJobType(),
          description: clean(getText("#jobDescriptionText")) || getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: clean(getText('[class*="date"]')),
          applicants: "",
        };
      },
    },
    {
      name: "Glassdoor",
      match: /glassdoor\.com/,
      extract() {
        return {
          company: clean(getText('[data-test="employer-name"]')) || clean(getText(".employerName")),
          role: clean(getText('[data-test="job-title"]')) || clean(getText("h1")),
          location: clean(getText('[data-test="employee-location"]')) || clean(getText(".location")),
          salary: clean(getText('[data-test="detailSalary"]')) || extractSalaryFromText(),
          jobType: detectJobType(),
          description: clean(getText(".jobDescriptionContent")) || getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: "",
          applicants: "",
        };
      },
    },
    {
      name: "Lever",
      match: /lever\.co/,
      extract() {
        const categories = getTexts(".posting-categories .sort-by-commitment, .posting-categories .sort-by-location, .posting-categories .sort-by-team");
        return {
          company: clean(getText(".main-header-logo img")?.alt || getText(".posting-header .company-name") || ""),
          role: clean(getText("h2.posting-headline") || getText("h2")),
          location: categories[1] || clean(getText('[class*="location"]')),
          salary: extractSalaryFromText(),
          jobType: categories[0] || detectJobType(),
          description: clean(getText('[class*="posting-page"] .content')) || getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: "",
          applicants: "",
        };
      },
    },
    {
      name: "Greenhouse",
      match: /greenhouse\.io/,
      extract() {
        return {
          company: clean(getText(".company-name") || getMeta("og:site_name")),
          role: clean(getText("h1.app-title") || getText("h1")),
          location: clean(getText(".location")),
          salary: extractSalaryFromText(),
          jobType: detectJobType(),
          description: clean(getText("#content")) || getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: "",
          applicants: "",
        };
      },
    },
    {
      name: "Workday",
      match: /myworkdayjobs\.com/,
      extract() {
        return {
          company: clean(getText('[data-automation-id="headerText"]')),
          role: clean(getText('[data-automation-id="jobPostingHeader"]') || getText("h2")),
          location: clean(getText('[data-automation-id="locations"]')),
          salary: extractSalaryFromText(),
          jobType: clean(getText('[data-automation-id="time"]')) || detectJobType(),
          description: clean(getText('[data-automation-id="jobPostingDescription"]')) || getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: clean(getText('[data-automation-id="postedOn"]')),
          applicants: "",
        };
      },
    },
    {
      name: "ZipRecruiter",
      match: /ziprecruiter\.com/,
      extract() {
        return {
          company: clean(getText('[class*="hiring_company"]') || getText(".company_name")),
          role: clean(getText("h1.job_title") || getText("h1")),
          location: clean(getText('[class*="location"]')),
          salary: clean(getText('[class*="salary"]')) || extractSalaryFromText(),
          jobType: detectJobType(),
          description: getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: "",
          applicants: "",
        };
      },
    },
    {
      name: "Wellfound",
      match: /wellfound\.com|angel\.co/,
      extract() {
        return {
          company: clean(getText('[class*="company-name"]') || getText("h2")),
          role: clean(getText("h1")),
          location: clean(getText('[class*="location"]')),
          salary: clean(getText('[class*="compensation"]')) || extractSalaryFromText(),
          jobType: detectJobType(),
          description: getDescriptionText(),
          skills: extractSkillsFromDescription(),
          postedDate: "",
          applicants: "",
        };
      },
    },
  ];

  // --- Shared Extraction Utilities ---

  function extractSalaryFromText() {
    const body = document.body.innerText;
    // Match patterns like $80,000 - $120,000, $80k-$120k, etc.
    const patterns = [
      /\$[\d,]+(?:\.\d{2})?\s*[-–—to]+\s*\$[\d,]+(?:\.\d{2})?(?:\s*(?:per\s+)?(?:year|yr|annually|annual|pa))?/gi,
      /\$[\d]+k\s*[-–—to]+\s*\$[\d]+k/gi,
      /(?:salary|compensation|pay)[\s:]*\$[\d,k]+\s*[-–—to]*\s*\$?[\d,k]*/gi,
    ];
    for (const pat of patterns) {
      const match = body.match(pat);
      if (match) return clean(match[0]);
    }
    return "";
  }

  function detectJobType() {
    const body = document.body.innerText.toLowerCase();
    if (body.includes("remote") && !body.includes("not remote")) return "Remote";
    if (body.includes("hybrid")) return "Hybrid";
    if (body.includes("on-site") || body.includes("onsite") || body.includes("in-office")) return "On-site";
    return "";
  }

  function extractLinkedInSkills() {
    const skills = getTexts(".job-details-skill-match-status-list li .skill-match-text");
    if (skills.length > 0) return skills;
    return extractSkillsFromDescription();
  }

  function extractSkillsFromDescription() {
    const desc = getDescriptionText().toLowerCase();
    const knownSkills = [
      "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "ruby",
      "react", "angular", "vue", "node.js", "express", "django", "flask", "fastapi",
      "spring", "docker", "kubernetes", "aws", "azure", "gcp", "terraform",
      "sql", "postgresql", "mongodb", "redis", "elasticsearch",
      "machine learning", "deep learning", "nlp", "computer vision",
      "git", "ci/cd", "agile", "scrum", "rest api", "graphql",
      "html", "css", "tailwind", "next.js", "svelte",
      "linux", "bash", "powershell",
      "figma", "jira", "confluence",
    ];
    return knownSkills.filter((s) => desc.includes(s.toLowerCase()));
  }

  // --- Generic Fallback ---
  function genericExtract() {
    return {
      company: clean(getMeta("og:site_name") || getText('[class*="company"]') || ""),
      role: clean(getText("h1")),
      location: clean(getText('[class*="location"]') || getMeta("geo.placename")),
      salary: extractSalaryFromText(),
      jobType: detectJobType(),
      description: getDescriptionText(),
      skills: extractSkillsFromDescription(),
      postedDate: "",
      applicants: "",
    };
  }

  // --- Public API ---
  function extract() {
    const host = window.location.hostname;
    for (const extractor of EXTRACTORS) {
      if (extractor.match.test(host)) {
        try {
          const data = extractor.extract();
          data.source = extractor.name;
          data.url = window.location.href;
          return data;
        } catch (e) {
          console.warn(`[JobTracker] ${extractor.name} extractor failed:`, e);
        }
      }
    }
    // Fallback
    const data = genericExtract();
    data.source = "Other";
    data.url = window.location.href;
    return data;
  }

  function getApplyButtonSelectors() {
    return [
      // LinkedIn
      ".jobs-apply-button",
      ".jobs-s-apply button",
      '[data-control-name="jobdetails_topcard_inapply"]',
      ".artdeco-button--primary",
      // Indeed
      "#indeedApplyButton",
      '[id*="applyButton"]',
      ".jobsearch-IndeedApplyButton",
      // Glassdoor
      '[data-test="applyButton"]',
      // Generic
      'button[class*="apply" i]',
      'a[class*="apply" i]',
      'button[id*="apply" i]',
      'a[id*="apply" i]',
      '[class*="apply-btn"]',
      '[class*="apply-button"]',
      '[data-action="apply"]',
    ];
  }

  return { extract, getApplyButtonSelectors };
})();
