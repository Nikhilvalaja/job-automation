"""ML-powered job description parser.

Uses OpenAI GPT to extract structured data from raw job postings:
- Role category (backend, data_science, ml, devops, etc.)
- Experience level (entry, mid, senior, lead, staff)
- Years of experience required (min/max range)
- Job type (full_time, part_time, contract, internship)
- Remote type (remote, hybrid, onsite)
- Required skills
- Salary range (if mentioned)
- Education requirements

Falls back to keyword-based extraction when GPT is unavailable.
"""

from __future__ import annotations

import json
import re

from src.llm.client import LLMClient
from src.utils.logging import get_logger

logger = get_logger(__name__)

PARSE_SYSTEM = """You are a job description parser. Extract structured data from job postings.

Return ONLY valid JSON with these fields:
{
  "category": "one of: backend, frontend, fullstack, data_science, data_engineer, ml_engineer, devops, cloud, mobile, security, business_analyst, product_manager, qa, other",
  "experience_level": "one of: entry, mid, senior, lead, staff, principal, director",
  "experience_years_min": 0,
  "experience_years_max": 0,
  "job_type": "one of: full_time, part_time, contract, internship",
  "remote_type": "one of: remote, hybrid, onsite, unknown",
  "salary_min": 0,
  "salary_max": 0,
  "salary_currency": "USD",
  "skills": "comma-separated list of key technical skills",
  "education": "one of: none, bachelors, masters, phd"
}

Rules:
- If experience years not stated, estimate from level: entry=0-2, mid=2-5, senior=5-10, lead=8-15, staff=10+
- If salary not mentioned, set both to 0
- For skills, extract only technical skills (languages, frameworks, tools), max 15
- Return ONLY the JSON object, no other text"""

PARSE_USER = """Parse this job posting:

Title: {title}
Company: {company}
Location: {location}

Description:
{description}"""


class JobParser:
    """Parses job descriptions into structured data using LLM or keywords."""

    def __init__(self) -> None:
        self._llm = LLMClient()

    def parse(self, job: dict) -> dict:
        """Parse a job posting into structured fields.

        Uses GPT if available, falls back to keyword extraction.
        """
        if self._llm.is_configured():
            try:
                return self._parse_llm(job)
            except Exception as e:
                logger.warning(f"LLM parse failed, falling back to keywords: {e}")

        return self._parse_keywords(job)

    def parse_batch(self, jobs: list[dict], batch_size: int = 10) -> list[dict]:
        """Parse multiple jobs. Uses LLM for each (rate-limited)."""
        results = []
        for job in jobs[:batch_size]:
            result = self.parse(job)
            results.append(result)
        return results

    def _parse_llm(self, job: dict) -> dict:
        """Parse using OpenAI GPT."""
        user_prompt = PARSE_USER.format(
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            description=job.get("description", "")[:3000],
        )

        result = self._llm.chat_safe(
            system_prompt=PARSE_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=500,
        )
        if result is None:
            raise RuntimeError("LLM unavailable — quota exceeded or not configured")

        # Parse JSON from response
        text = result["text"].strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]

        parsed = json.loads(text)

        # Validate and clean fields
        return self._validate_fields(parsed)

    def _parse_keywords(self, job: dict) -> dict:
        """Keyword-based fallback parser (no API needed)."""
        title = job.get("title", "").lower()
        desc = job.get("description", "").lower()
        location = job.get("location", "").lower()
        all_text = f"{title} {desc}"

        return self._validate_fields({
            "category": _detect_category(title, desc),
            "experience_level": _detect_level(title, desc),
            "experience_years_min": _detect_years_min(all_text),
            "experience_years_max": _detect_years_max(all_text),
            "job_type": _detect_job_type(title, desc),
            "remote_type": _detect_remote(title, desc, location),
            "salary_min": 0,
            "salary_max": 0,
            "salary_currency": "USD",
            "skills": _detect_skills(all_text),
            "education": _detect_education(desc),
        })

    def _validate_fields(self, fields: dict) -> dict:
        """Ensure all fields are valid."""
        valid_categories = {
            "backend", "frontend", "fullstack", "data_science", "data_engineer",
            "ml_engineer", "devops", "cloud", "mobile", "security",
            "business_analyst", "product_manager", "qa", "other",
        }
        valid_levels = {"entry", "mid", "senior", "lead", "staff", "principal", "director"}
        valid_types = {"full_time", "part_time", "contract", "internship"}
        valid_remote = {"remote", "hybrid", "onsite", "unknown"}
        valid_edu = {"none", "bachelors", "masters", "phd"}

        cat = str(fields.get("category", "other")).lower().replace(" ", "_")
        fields["category"] = cat if cat in valid_categories else "other"

        level = str(fields.get("experience_level", "mid")).lower()
        fields["experience_level"] = level if level in valid_levels else "mid"

        jtype = str(fields.get("job_type", "full_time")).lower().replace(" ", "_").replace("-", "_")
        fields["job_type"] = jtype if jtype in valid_types else "full_time"

        remote = str(fields.get("remote_type", "unknown")).lower()
        fields["remote_type"] = remote if remote in valid_remote else "unknown"

        edu = str(fields.get("education", "none")).lower().replace("'", "").replace("bachelor", "bachelors").replace("master", "masters")
        if "bachelor" in edu:
            edu = "bachelors"
        elif "master" in edu:
            edu = "masters"
        fields["education"] = edu if edu in valid_edu else "none"

        fields["experience_years_min"] = max(0, int(fields.get("experience_years_min", 0) or 0))
        fields["experience_years_max"] = max(0, int(fields.get("experience_years_max", 0) or 0))
        fields["salary_min"] = max(0, int(fields.get("salary_min", 0) or 0))
        fields["salary_max"] = max(0, int(fields.get("salary_max", 0) or 0))

        if isinstance(fields.get("skills"), list):
            fields["skills"] = ",".join(fields["skills"])

        return fields


# ---------------------------------------------------------------------------
# Keyword-based detection functions (fallback when GPT not available)
# ---------------------------------------------------------------------------

def _detect_category(title: str, desc: str) -> str:
    """Detect job category from title and description."""
    rules = [
        ("data_science", ["data scientist", "data science", "data analyst"]),
        ("data_engineer", ["data engineer", "data pipeline", "etl"]),
        ("ml_engineer", ["machine learning", "ml engineer", "deep learning", "ai engineer"]),
        ("backend", ["backend", "back-end", "server-side", "api developer"]),
        ("frontend", ["frontend", "front-end", "react developer", "ui developer"]),
        ("fullstack", ["full stack", "fullstack", "full-stack"]),
        ("devops", ["devops", "sre", "site reliability", "platform engineer", "infrastructure"]),
        ("cloud", ["cloud engineer", "cloud architect", "aws engineer", "azure engineer"]),
        ("mobile", ["ios developer", "android developer", "mobile developer", "react native"]),
        ("security", ["security engineer", "cybersecurity", "infosec", "penetration"]),
        ("business_analyst", ["business analyst", "business intelligence", "bi analyst"]),
        ("product_manager", ["product manager", "product owner", "program manager"]),
        ("qa", ["qa engineer", "quality assurance", "test engineer", "sdet"]),
    ]
    for category, keywords in rules:
        for kw in keywords:
            if kw in title or kw in desc[:500]:
                return category
    return "other"


def _detect_level(title: str, desc: str) -> str:
    """Detect experience level from title."""
    if any(w in title for w in ["principal", "distinguished"]):
        return "principal"
    if any(w in title for w in ["staff"]):
        return "staff"
    if any(w in title for w in ["director"]):
        return "director"
    if any(w in title for w in ["lead", "team lead"]):
        return "lead"
    if any(w in title for w in ["senior", "sr.", "sr "]):
        return "senior"
    if any(w in title for w in ["junior", "jr.", "jr ", "entry", "associate", "graduate", "new grad"]):
        return "entry"
    if any(w in title for w in ["intern"]):
        return "entry"
    return "mid"


def _detect_years_min(text: str) -> int:
    """Extract minimum years of experience."""
    patterns = [
        r"(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)",
        r"(?:minimum|min|at least)\s*(\d+)\s*(?:years?|yrs?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return 0


def _detect_years_max(text: str) -> int:
    """Extract maximum years of experience."""
    pattern = r"(\d+)\s*[-–to]+\s*(\d+)\s*(?:years?|yrs?)"
    match = re.search(pattern, text)
    if match:
        return int(match.group(2))

    # If only min found, estimate max
    min_years = _detect_years_min(text)
    if min_years > 0:
        return min_years + 3
    return 0


def _detect_job_type(title: str, desc: str) -> str:
    """Detect job type."""
    text = f"{title} {desc[:500]}"
    if "intern" in text:
        return "internship"
    if "contract" in text or "freelance" in text:
        return "contract"
    if "part-time" in text or "part time" in text:
        return "part_time"
    return "full_time"


def _detect_remote(title: str, desc: str, location: str) -> str:
    """Detect remote work type."""
    text = f"{title} {desc[:500]} {location}"
    if "remote" in text:
        if "hybrid" in text:
            return "hybrid"
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if "on-site" in text or "onsite" in text or "in-office" in text:
        return "onsite"
    return "unknown"


def _detect_skills(text: str) -> str:
    """Detect technical skills from job text."""
    skill_keywords = [
        "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++",
        "react", "angular", "vue", "node.js", "django", "flask", "fastapi", "spring",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
        "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
        "pytorch", "tensorflow", "scikit-learn", "pandas", "spark", "airflow",
        "git", "ci/cd", "jenkins", "github actions",
        "rest api", "graphql", "grpc", "microservices",
        "linux", "kafka", "rabbitmq", "celery",
    ]
    found = [skill for skill in skill_keywords if skill in text]
    return ",".join(found[:15])


def _detect_education(desc: str) -> str:
    """Detect education requirements."""
    if "phd" in desc or "ph.d" in desc or "doctorate" in desc:
        return "phd"
    if "master" in desc or "m.s." in desc or "ms " in desc:
        return "masters"
    if "bachelor" in desc or "b.s." in desc or "bs " in desc or "degree" in desc:
        return "bachelors"
    return "none"
