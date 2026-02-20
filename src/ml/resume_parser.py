"""Resume text parser — structures resume text into analyzable units.

Parses resume text into:
- Summary/objective section
- Experience entries (company, role, bullets)
- Skills inventory (master list of all skills)
- Education section

100% deterministic — no LLM calls.

Supports common resume formats:
- Bullet-point based (most common)
- Paragraph style
- With or without explicit section headers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.ml.bullet_analyzer import AnalyzedBullet, analyze_bullet
from src.ml.skill_taxonomy import extract_skills, categorize_skills
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExperienceEntry:
    """A single work experience entry."""
    company: str = ""
    role: str = ""
    date_range: str = ""
    bullets: list[AnalyzedBullet] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "role": self.role,
            "date_range": self.date_range,
            "bullets": [b.to_dict() for b in self.bullets],
        }


@dataclass
class ParsedResume:
    """Fully parsed and structured resume."""
    raw_text: str = ""
    summary_lines: list[str] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    skills_tokens: list[str] = field(default_factory=list)
    skill_categories: dict[str, list[str]] = field(default_factory=dict)
    skill_inventory_master_list: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    total_bullets: int = 0
    total_metrics: int = 0

    def to_dict(self) -> dict:
        return {
            "summary_lines": self.summary_lines,
            "experience": [e.to_dict() for e in self.experience],
            "skills_tokens": self.skills_tokens,
            "skill_categories": self.skill_categories,
            "skill_inventory_master_list": self.skill_inventory_master_list,
            "education": self.education,
            "total_bullets": self.total_bullets,
            "total_metrics": self.total_metrics,
        }


# ---------------------------------------------------------------------------
# Section detection patterns
# ---------------------------------------------------------------------------

_SECTION_HEADERS = {
    "summary": re.compile(
        r"(?:^|\n)\s*(?:summary|objective|profile|about\s+me|professional\s+summary)\s*:?\s*\n",
        re.IGNORECASE,
    ),
    "experience": re.compile(
        r"(?:^|\n)\s*(?:experience|work\s+experience|professional\s+experience|"
        r"employment|work\s+history|career\s+history)\s*:?\s*\n",
        re.IGNORECASE,
    ),
    "skills": re.compile(
        r"(?:^|\n)\s*(?:skills|technical\s+skills|core\s+competencies|"
        r"technologies|tech\s+stack|tools\s+&\s+technologies)\s*:?\s*\n",
        re.IGNORECASE,
    ),
    "education": re.compile(
        r"(?:^|\n)\s*(?:education|academic|degrees?|certifications?|"
        r"education\s+&\s+certifications?)\s*:?\s*\n",
        re.IGNORECASE,
    ),
    "projects": re.compile(
        r"(?:^|\n)\s*(?:projects|personal\s+projects|side\s+projects|"
        r"open\s+source)\s*:?\s*\n",
        re.IGNORECASE,
    ),
}

# Experience entry header: "Company Name | Role | Date"
# or "Role at Company (Date)" etc.
_EXPERIENCE_ENTRY = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    # Pattern 1: Company — Role (or Role — Company)
    r"([A-Z][\w\s&.,'-]+?)\s*(?:[|–—-]|at)\s*(.+?)(?:\s*[|–—-]\s*(.+?))?"
    r"|"
    # Pattern 2: Just a company/role line followed by date
    r"([A-Z][\w\s&.,'-]+)"
    r")"
    r"\s*$",
    re.MULTILINE,
)

# Date range patterns
_DATE_PATTERN = re.compile(
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}"
    r"|(?:20|19)\d{2})"
    r"\s*[-–—to]+\s*"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}"
    r"|(?:20|19)\d{2}|present|current)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ResumeParser:
    """Parses resume text into structured units.

    100% deterministic. No LLM calls.
    """

    def parse(self, text: str) -> ParsedResume:
        """Parse resume text into structured format.

        Args:
            text: Raw resume text (from PDF extraction, paste, etc.)

        Returns:
            ParsedResume with all sections structured.
        """
        if not text or not text.strip():
            return ParsedResume(raw_text=text)

        # Normalize whitespace
        clean_text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Detect sections
        sections = self._detect_sections(clean_text)

        # Parse each section
        summary = self._parse_summary(sections.get("summary", ""))
        experience = self._parse_experience(sections.get("experience", ""))
        education = self._parse_education(sections.get("education", ""))

        # Extract skills from everywhere
        all_skills = extract_skills(clean_text)

        # Also extract from explicit skills section
        skills_section_skills = extract_skills(sections.get("skills", ""))
        # Merge (preserve order, deduplicate)
        seen = set()
        merged_skills = []
        for s in skills_section_skills + all_skills:
            if s not in seen:
                merged_skills.append(s)
                seen.add(s)

        # Categorize
        categories = categorize_skills(merged_skills)

        # Count metrics across all bullets
        total_bullets = sum(len(e.bullets) for e in experience)
        total_metrics = sum(
            len(b.metrics) for e in experience for b in e.bullets
        )

        result = ParsedResume(
            raw_text=text,
            summary_lines=summary,
            experience=experience,
            skills_tokens=merged_skills,
            skill_categories=categories,
            skill_inventory_master_list=merged_skills,  # this IS the master list
            education=education,
            total_bullets=total_bullets,
            total_metrics=total_metrics,
        )

        logger.debug(
            f"Parsed resume: {len(experience)} entries, {total_bullets} bullets, "
            f"{len(merged_skills)} skills, {total_metrics} metrics"
        )

        return result

    def _detect_sections(self, text: str) -> dict[str, str]:
        """Detect and split text into sections by headers."""
        # Find all section header positions
        found_sections: list[tuple[str, int, int]] = []

        for section_name, pattern in _SECTION_HEADERS.items():
            match = pattern.search(text)
            if match:
                found_sections.append((section_name, match.start(), match.end()))

        if not found_sections:
            # No headers found — treat entire text as experience
            return {"experience": text}

        # Sort by position
        found_sections.sort(key=lambda x: x[1])

        # Extract section texts
        sections: dict[str, str] = {}
        for i, (name, _, header_end) in enumerate(found_sections):
            if i + 1 < len(found_sections):
                next_start = found_sections[i + 1][1]
                sections[name] = text[header_end:next_start]
            else:
                sections[name] = text[header_end:]

        # If there's text before the first section, treat as summary
        if found_sections[0][1] > 50:
            pre_text = text[:found_sections[0][1]].strip()
            if pre_text and "summary" not in sections:
                sections["summary"] = pre_text

        return sections

    def _parse_summary(self, text: str) -> list[str]:
        """Parse summary section into individual lines."""
        if not text:
            return []
        lines = []
        for line in text.strip().split("\n"):
            cleaned = line.strip()
            cleaned = re.sub(r"^[-•*·‣]\s*", "", cleaned)
            if cleaned and len(cleaned) > 15:
                lines.append(cleaned)
        return lines[:5]  # max 5 summary lines

    def _parse_experience(self, text: str) -> list[ExperienceEntry]:
        """Parse experience section into entries with bullets."""
        if not text:
            return []

        entries: list[ExperienceEntry] = []
        lines = text.strip().split("\n")

        current_entry: ExperienceEntry | None = None
        current_bullets: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check if this is a date line
            date_match = _DATE_PATTERN.search(stripped)

            # Check if this is a company/role header
            is_header = (
                # Starts with capital, not a bullet, relatively short
                stripped[0].isupper()
                and not stripped.startswith(("-", "•", "*", "·", "‣"))
                and not re.match(r"^\d+[\.\)]", stripped)
                and len(stripped) < 120
                and (date_match or "|" in stripped or "—" in stripped or " at " in stripped.lower())
            )

            if is_header:
                # Save previous entry
                if current_entry:
                    current_entry.bullets = [
                        analyze_bullet(b, f"{current_entry.company.lower().replace(' ', '_')}_{i}")
                        for i, b in enumerate(current_bullets)
                    ]
                    entries.append(current_entry)

                # Parse new entry header
                company, role, date_range = self._parse_entry_header(stripped)
                current_entry = ExperienceEntry(
                    company=company,
                    role=role,
                    date_range=date_range,
                )
                current_bullets = []

            elif stripped.startswith(("-", "•", "*", "·", "‣")) or re.match(r"^\d+[\.\)]", stripped):
                # It's a bullet point
                bullet_text = re.sub(r"^[-•*·‣\d\.\)]+\s*", "", stripped)
                if len(bullet_text) > 10:
                    current_bullets.append(bullet_text)

            elif current_entry and not current_entry.date_range and date_match:
                # Date line on its own
                current_entry.date_range = date_match.group()

        # Save last entry
        if current_entry:
            current_entry.bullets = [
                analyze_bullet(b, f"{current_entry.company.lower().replace(' ', '_')}_{i}")
                for i, b in enumerate(current_bullets)
            ]
            entries.append(current_entry)

        return entries

    def _parse_entry_header(self, line: str) -> tuple[str, str, str]:
        """Parse a company/role header line.

        Returns (company, role, date_range).
        """
        # Extract date first
        date_match = _DATE_PATTERN.search(line)
        date_range = date_match.group() if date_match else ""
        if date_match:
            line = line[:date_match.start()] + line[date_match.end():]

        # Clean up separators
        line = line.strip().rstrip("|–—- ")

        # Try splitting by common separators
        parts = re.split(r"\s*[|–—]\s*", line)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) >= 2:
            # Check if first part looks like a role (has common title words)
            role_words = {"engineer", "developer", "manager", "lead", "senior",
                         "architect", "analyst", "scientist", "designer", "director"}
            first_lower = parts[0].lower()
            if any(w in first_lower for w in role_words):
                return parts[1], parts[0], date_range
            return parts[0], parts[1], date_range
        elif parts:
            # Single part — try "Role at Company"
            at_match = re.match(r"(.+?)\s+at\s+(.+)", parts[0], re.IGNORECASE)
            if at_match:
                return at_match.group(2).strip(), at_match.group(1).strip(), date_range
            return parts[0], "", date_range

        return "", "", date_range

    def _parse_education(self, text: str) -> list[str]:
        """Parse education section into entries."""
        if not text:
            return []
        entries = []
        for line in text.strip().split("\n"):
            cleaned = line.strip()
            cleaned = re.sub(r"^[-•*·‣]\s*", "", cleaned)
            if cleaned and len(cleaned) > 10:
                entries.append(cleaned)
        return entries[:5]  # max 5 education entries
