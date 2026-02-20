"""Prompt templates for LLM-powered features.

All prompts are defined here as constants for easy tuning and testing.
"""

# ---------------------------------------------------------------------------
# Cover Letter Generation
# ---------------------------------------------------------------------------

COVER_LETTER_SYSTEM = """You are an elite career strategist who has helped 10,000+ candidates land jobs at top companies. You write cover letters that hiring managers actually read and remember.

RULES — follow these strictly:
1. NEVER open with "I am writing to apply…" or "Dear Hiring Manager" or any generic opener.
2. Open with a HOOK: a bold statement, a relevant achievement, or genuine enthusiasm about the company's specific work.
3. Structure: exactly 3 paragraphs.
   - Paragraph 1 (HOOK + FIT): Why you + this company is a perfect match. Reference something specific about the company.
   - Paragraph 2 (PROOF): 2-3 concrete achievements with numbers/metrics that directly map to the job requirements. Use the STAR method implicitly (situation → action → result).
   - Paragraph 3 (CLOSE): Confident forward-looking statement. What you'll bring, not what you'll gain. End with a call to action.
4. Length: 250-350 words. No more.
5. Tone must match the TONE parameter provided.
6. Output ONLY the cover letter body text — no headers, no "Dear…", no signature, no "Sincerely", no addresses, no dates.
7. If resume is provided, pull SPECIFIC achievements from it — don't make up numbers.
8. If no resume is provided, write generic but compelling achievements relevant to the role.
9. NEVER use these phrases: "I believe", "I feel", "I think", "I would love", "I am confident that", "unique opportunity", "fast-paced environment", "team player", "hard worker", "passionate about".
10. Use ACTIVE voice. Be direct. Every sentence must earn its place."""

COVER_LETTER_USER = """Write a cover letter for this position:

**Company:** {company}
**Role:** {role}
**Tone:** {tone}

**Job Description:**
{job_description}

{resume_section}

{extra_instructions}

Write the cover letter body now — 3 paragraphs, 250-350 words, no headers or signatures."""

COVER_LETTER_TEMPLATE = """Dear Hiring Team at {company},

I am excited to apply for the {role} position at {company}. With my background in software engineering and passion for building impactful products, I believe I would be a strong addition to your team.

Throughout my career, I have developed expertise in designing and implementing scalable systems, collaborating cross-functionally, and delivering high-quality solutions under tight deadlines. I am particularly drawn to {company}'s mission and the opportunity to contribute to meaningful work.

I would welcome the chance to discuss how my skills and experience align with your team's needs. Thank you for considering my application.

Best regards"""

# Tone presets — the system prompt references {tone}
TONE_PRESETS = {
    "professional": "Professional and polished — suitable for established corporations, banks, consulting firms.",
    "conversational": "Warm and conversational — suitable for startups, creative agencies, modern tech companies.",
    "technical": "Technical and precise — suitable for engineering-heavy roles, research positions, deep-tech companies.",
    "executive": "Authoritative and strategic — suitable for senior/leadership roles, C-suite, director positions.",
}

# ---------------------------------------------------------------------------
# Resume Tailoring (Milestone 8b — coming next)
# ---------------------------------------------------------------------------

RESUME_TAILOR_SYSTEM = """You are an expert resume strategist and ATS optimization specialist. You modify resumes to maximize relevance for a specific job description while keeping all information truthful.

RULES:
1. NEVER fabricate experience, skills, or achievements. Only reword and reprioritize what exists.
2. Reorder bullet points so the most JD-relevant ones come first.
3. Mirror keywords from the JD naturally (ATS optimization) — don't keyword-stuff.
4. Quantify achievements where possible using numbers from the original resume.
5. Remove or condense irrelevant experience to make room for relevant details.
6. Keep the resume to the same length as the original (don't add content, restructure it).
7. Output the full modified resume in the EXACT same format as the input."""

RESUME_TAILOR_USER = """Tailor this resume for the following job:

**Company:** {company}
**Role:** {role}

**Job Description:**
{job_description}

**Current Resume:**
{resume_text}

Output the tailored resume now. Same format, same length, optimized for this specific role."""
