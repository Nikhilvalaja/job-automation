"""Job description normalization engine.

Transforms raw JD text into structured data:
- Removes EEO/legal/benefits boilerplate
- Extracts must-have vs nice-to-have skills
- Normalizes title and seniority
- Detects location/remote type
- Computes parse confidence score

100% deterministic — no LLM calls. Uses regex patterns, skill taxonomy,
and heuristic rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.ml.skill_taxonomy import extract_skills, get_skill_category
from src.ml.title_normalizer import normalize_title, NormalizedTitle
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class NormalizedJD:
    """Structured output from JD normalization."""
    title_raw: str = ""
    title_norm: str = ""           # canonical role: "data_engineer"
    seniority_level: str = ""      # "entry", "mid", "senior", etc.
    location_type: str = ""        # "remote", "hybrid", "onsite", "unknown"
    must_have_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    all_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    cleaned_text: str = ""
    confidence: float = 0.0
    skill_categories: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "title_raw": self.title_raw,
            "title_norm": self.title_norm,
            "seniority_level": self.seniority_level,
            "location_type": self.location_type,
            "must_have_skills": self.must_have_skills,
            "nice_to_have_skills": self.nice_to_have_skills,
            "all_skills": self.all_skills,
            "responsibilities": self.responsibilities,
            "cleaned_text": self.cleaned_text,
            "confidence": self.confidence,
            "skill_categories": self.skill_categories,
        }


# ---------------------------------------------------------------------------
# Boilerplate removal patterns
# ---------------------------------------------------------------------------

_BOILERPLATE_PATTERNS: list[re.Pattern] = [
    # EEO statements
    re.compile(
        r"(?:equal\s+opportunity|eeo|affirmative\s+action|"
        r"we\s+(?:are|do)\s+not\s+discriminate|"
        r"regardless\s+of\s+race|"
        r"all\s+qualified\s+applicants|"
        r"protected\s+(?:class|characteristic|veteran)|"
        r"disability\s+status|"
        r"gender\s+identity|sexual\s+orientation).*?(?:\n\n|\n(?=[A-Z])|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
    # Benefits boilerplate
    re.compile(
        r"(?:(?:our|we\s+offer|benefits\s+include|what\s+we\s+offer|perks)\s*:?\s*\n)"
        r"(?:[-•*]\s*(?:(?:health|dental|vision|401k|pto|vacation|stock|equity|"
        r"insurance|gym|wellness|remote|flexible|parental|disability|life).*?\n))+",
        re.IGNORECASE,
    ),
    # Legal disclaimers
    re.compile(
        r"(?:this\s+(?:position|role)\s+(?:is\s+)?(?:subject\s+to|requires)\s+"
        r"(?:background\s+check|drug\s+(?:test|screen)|security\s+clearance)).*?"
        r"(?:\n\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
    # Salary disclaimers
    re.compile(
        r"(?:compensation|salary|pay)\s+(?:range|band)?\s*(?:is\s+)?(?:based\s+on|"
        r"depends\s+on|varies\s+(?:by|based)).*?(?:\n\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "About Us" sections at the end
    re.compile(
        r"(?:^|\n)(?:about\s+(?:us|the\s+company|our\s+company))\s*\n.*$",
        re.IGNORECASE | re.DOTALL,
    ),
]

# ---------------------------------------------------------------------------
# Section detection for must-have vs nice-to-have
# ---------------------------------------------------------------------------

# Patterns that indicate a "required" section
_REQUIRED_HEADERS = re.compile(
    r"(?:^|\n)\s*(?:required|requirements|must[- ]have|minimum\s+qualifications|"
    r"what\s+you(?:'ll)?\s+(?:need|bring)|essential|mandatory|"
    r"qualifications|basic\s+qualifications|key\s+skills)\s*:?\s*\n",
    re.IGNORECASE,
)

# Patterns that indicate a "nice-to-have" section
_PREFERRED_HEADERS = re.compile(
    r"(?:^|\n)\s*(?:preferred|nice[- ]to[- ]have|bonus|plus|preferred\s+qualifications|"
    r"desired|additional\s+qualifications|it(?:'s| is)\s+a\s+(?:bonus|plus)|"
    r"ideal(?:ly)?|advantageous|not\s+required\s+but)\s*:?\s*\n",
    re.IGNORECASE,
)

# Inline markers for must-have within bullets
_MUST_HAVE_INLINE = re.compile(
    r"(?:required|must\s+have|mandatory|essential|minimum\s+of)",
    re.IGNORECASE,
)

# Inline markers for nice-to-have within bullets
_NICE_HAVE_INLINE = re.compile(
    r"(?:preferred|nice\s+to\s+have|bonus|plus|ideally|a\s+plus|desirable|optional)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Location / Remote detection
# ---------------------------------------------------------------------------

_REMOTE_PATTERNS = {
    "remote": re.compile(
        r"\b(?:fully\s+remote|100%\s+remote|remote[- ]first|remote[- ]only|"
        r"work\s+from\s+(?:home|anywhere)|distributed\s+team)\b",
        re.IGNORECASE,
    ),
    "hybrid": re.compile(
        r"\b(?:hybrid|(?:\d+)\s*days?\s*(?:in[- ]office|on[- ]site)|"
        r"flexible\s+(?:work|location)|partially\s+remote)\b",
        re.IGNORECASE,
    ),
    "onsite": re.compile(
        r"\b(?:on[- ]?site|in[- ]office|in[- ]person|office[- ]based|"
        r"must\s+be\s+(?:located|based)\s+in)\b",
        re.IGNORECASE,
    ),
}

# ---------------------------------------------------------------------------
# Responsibility extraction
# ---------------------------------------------------------------------------

_RESPONSIBILITY_HEADER = re.compile(
    r"(?:^|\n)\s*(?:responsibilities|what\s+you(?:'ll)?\s+(?:do|work\s+on)|"
    r"the\s+role|your\s+(?:role|impact)|key\s+responsibilities|"
    r"in\s+this\s+role|day\s+to\s+day)\s*:?\s*\n",
    re.IGNORECASE,
)


def _extract_bullets(text: str, start: int, max_bullets: int = 15) -> list[str]:
    """Extract bullet points starting from a position in text."""
    section = text[start:]
    # Find end of section (next header or double newline without bullet)
    lines = section.split("\n")
    bullets = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if bullets:  # empty line after bullets = end of section
                break
            continue
        # Check if it's a bullet
        if stripped.startswith(("- ", "* ", "• ", "· ", "‣ ")) or re.match(r"^\d+[\.\)]\s", stripped):
            bullet_text = re.sub(r"^[-*•·‣\d\.\)]+\s*", "", stripped)
            if len(bullet_text) > 10:  # skip very short bullets
                bullets.append(bullet_text)
        elif bullets:
            # Non-bullet line after bullets = end of section
            # Unless it's a continuation (starts with lowercase)
            if stripped[0].isupper() and len(stripped) > 50:
                break
        if len(bullets) >= max_bullets:
            break
    return bullets


# ---------------------------------------------------------------------------
# Main Normalizer
# ---------------------------------------------------------------------------

class JDNormalizer:
    """Normalizes raw job descriptions into structured data.

    100% deterministic. No LLM calls.
    """

    def normalize(self, title: str, description: str, location: str = "") -> NormalizedJD:
        """Normalize a job description into structured fields.

        Args:
            title: Raw job title
            description: Raw JD text
            location: Location string if available

        Returns:
            NormalizedJD with all extracted fields + confidence score
        """
        if not description:
            title_info = normalize_title(title)
            return NormalizedJD(
                title_raw=title,
                title_norm=title_info.canonical,
                seniority_level=title_info.seniority,
                confidence=0.2,  # very low — title only
            )

        # Step 1: Clean text (remove boilerplate)
        cleaned = self._remove_boilerplate(description)

        # Step 2: Normalize title
        title_info = normalize_title(title)

        # Step 3: Detect location type
        location_type = self._detect_location(cleaned, location)

        # Step 4: Extract skills with must-have / nice-to-have classification
        must_have, nice_to_have, all_skills = self._extract_classified_skills(cleaned)

        # Step 5: Extract responsibilities
        responsibilities = self._extract_responsibilities(cleaned)

        # Step 6: Categorize skills
        skill_categories: dict[str, list[str]] = {}
        for skill in all_skills:
            cat = get_skill_category(skill)
            skill_categories.setdefault(cat, []).append(skill)

        # Step 7: Compute confidence
        confidence = self._compute_confidence(
            title_info=title_info,
            must_have=must_have,
            all_skills=all_skills,
            responsibilities=responsibilities,
            cleaned_text=cleaned,
        )

        result = NormalizedJD(
            title_raw=title,
            title_norm=title_info.canonical,
            seniority_level=title_info.seniority,
            location_type=location_type,
            must_have_skills=must_have,
            nice_to_have_skills=nice_to_have,
            all_skills=all_skills,
            responsibilities=responsibilities,
            cleaned_text=cleaned,
            confidence=round(confidence, 3),
            skill_categories=skill_categories,
        )

        logger.debug(
            f"Normalized JD: {title} -> {title_info.canonical}/{title_info.seniority} "
            f"({len(must_have)} must-have, {len(nice_to_have)} nice-to-have, "
            f"confidence={confidence:.2f})"
        )

        return result

    def _remove_boilerplate(self, text: str) -> str:
        """Remove EEO, benefits, legal boilerplate from JD text."""
        cleaned = text
        for pattern in _BOILERPLATE_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        # Collapse excessive whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _detect_location(self, text: str, location: str = "") -> str:
        """Detect remote/hybrid/onsite from text and location field."""
        combined = f"{text}\n{location}"
        # Check remote first (higher priority)
        if _REMOTE_PATTERNS["remote"].search(combined):
            return "remote"
        if _REMOTE_PATTERNS["hybrid"].search(combined):
            return "hybrid"
        if _REMOTE_PATTERNS["onsite"].search(combined):
            return "onsite"
        # Check for "remote" as a simple keyword in location field
        if "remote" in location.lower():
            return "remote"
        return "unknown"

    def _extract_classified_skills(
        self, text: str
    ) -> tuple[list[str], list[str], list[str]]:
        """Extract skills classified as must-have or nice-to-have.

        Returns (must_have, nice_to_have, all_skills).
        """
        all_skills = extract_skills(text)

        # Try section-based classification first
        must_have, nice_to_have = self._classify_by_sections(text, all_skills)

        # If section-based didn't work well, use inline markers
        if not must_have and not nice_to_have:
            must_have, nice_to_have = self._classify_by_inline(text, all_skills)

        # If still nothing classified, all skills are must-have
        if not must_have and not nice_to_have:
            must_have = all_skills
            nice_to_have = []

        return must_have, nice_to_have, all_skills

    def _classify_by_sections(
        self, text: str, all_skills: list[str]
    ) -> tuple[list[str], list[str]]:
        """Classify skills based on section headers (Required vs Preferred)."""
        required_match = _REQUIRED_HEADERS.search(text)
        preferred_match = _PREFERRED_HEADERS.search(text)

        if not required_match and not preferred_match:
            return [], []

        must_have = set()
        nice_to_have = set()

        # Extract text from required section
        if required_match:
            req_start = required_match.end()
            # End of required section: either preferred section or next major header
            req_end = preferred_match.start() if preferred_match and preferred_match.start() > req_start else len(text)
            req_text = text[req_start:req_end]
            must_have = set(extract_skills(req_text))

        # Extract text from preferred section
        if preferred_match:
            pref_start = preferred_match.end()
            pref_text = text[pref_start:]
            # Limit to reasonable length (next section or 2000 chars)
            next_header = re.search(r"\n\s*(?:[A-Z][a-z]+\s+){1,3}:?\s*\n", pref_text)
            if next_header:
                pref_text = pref_text[:next_header.start()]
            nice_to_have = set(extract_skills(pref_text[:2000]))

        # Remove overlaps: must-have takes priority
        nice_to_have -= must_have

        # Ensure all classified skills are in all_skills
        all_set = set(all_skills)
        must_list = [s for s in all_skills if s in must_have]
        nice_list = [s for s in all_skills if s in nice_to_have]

        return must_list, nice_list

    def _classify_by_inline(
        self, text: str, all_skills: list[str]
    ) -> tuple[list[str], list[str]]:
        """Classify skills based on inline markers (required/preferred keywords near skills)."""
        must_have = []
        nice_to_have = []

        lines = text.split("\n")
        for line in lines:
            line_skills = extract_skills(line)
            if not line_skills:
                continue

            if _MUST_HAVE_INLINE.search(line):
                must_have.extend(s for s in line_skills if s not in must_have)
            elif _NICE_HAVE_INLINE.search(line):
                nice_to_have.extend(s for s in line_skills if s not in nice_to_have)

        # Remove overlaps
        nice_set = set(nice_to_have) - set(must_have)
        nice_to_have = [s for s in nice_to_have if s in nice_set]

        return must_have, nice_to_have

    def _extract_responsibilities(self, text: str) -> list[str]:
        """Extract responsibility bullet points from JD."""
        match = _RESPONSIBILITY_HEADER.search(text)
        if match:
            return _extract_bullets(text, match.end(), max_bullets=10)
        return []

    def _compute_confidence(
        self,
        title_info: NormalizedTitle,
        must_have: list[str],
        all_skills: list[str],
        responsibilities: list[str],
        cleaned_text: str,
    ) -> float:
        """Compute confidence score for the normalization (0.0 - 1.0).

        Higher when:
        - Role was clearly identified (not "other")
        - Skills were found
        - Must-have / nice-to-have were classified
        - Responsibilities were extracted
        - Text has reasonable length
        """
        score = 0.0

        # Role identified (not "other"): +0.25
        if title_info.canonical != "other":
            score += 0.25

        # Seniority identified (not "mid" default): +0.10
        if title_info.seniority != "mid":
            score += 0.10

        # Skills found: +0.25 (scaled by count)
        skill_count = len(all_skills)
        if skill_count >= 5:
            score += 0.25
        elif skill_count >= 2:
            score += 0.15
        elif skill_count >= 1:
            score += 0.05

        # Must-have classified: +0.15
        if must_have:
            score += 0.15

        # Responsibilities extracted: +0.10
        if responsibilities:
            score += 0.10

        # Text length (reasonable JD is 300-5000 chars): +0.15
        text_len = len(cleaned_text)
        if 300 <= text_len <= 5000:
            score += 0.15
        elif text_len > 100:
            score += 0.05

        return min(score, 1.0)
