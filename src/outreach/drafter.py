"""Outreach drafter — generates personalized cold email drafts.

Strategy:
  1. Template drafter (always works, no API key needed)
  2. LLM drafter (OpenAI/Claude, optional — falls back to template)

Rules:
  - Max 150 words per email
  - No fake claims or fake mutual connections
  - Always mention: who you are, why them, one specific ask
  - Subject lines: short, specific, no clickbait
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class DraftResult:
    subject: str
    body: str
    variant_id: str
    drafted_by: str  # "template" | "llm"
    word_count: int


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------

_INITIAL_TEMPLATES = [
    {
        "variant": "A",
        "subject": "Interested in opportunities at {company}",
        "body": (
            "Hi {name},\n\n"
            "I came across {company} while researching {industry} companies and was impressed by your work on {topic}.\n\n"
            "I'm a software engineer with experience in {skills} and I'd love to learn more about engineering opportunities on your team.\n\n"
            "Would you be open to a 15-minute call this week or next?\n\n"
            "Thanks,\n{sender_name}"
        ),
    },
    {
        "variant": "B",
        "subject": "Software engineer interested in {company}",
        "body": (
            "Hi {name},\n\n"
            "I'm reaching out because {company}'s approach to {topic} stood out to me — "
            "especially your recent work in this space.\n\n"
            "I'm a backend/full-stack engineer with {experience} years of experience "
            "in {skills}. I'd be happy to share my background if there's an opening on your team.\n\n"
            "Happy to connect briefly — would a quick call work?\n\n"
            "Best,\n{sender_name}"
        ),
    },
]

_FOLLOW_UP_1_TEMPLATES = [
    {
        "variant": "A",
        "subject": "Re: Interested in opportunities at {company}",
        "body": (
            "Hi {name},\n\n"
            "Just following up on my note from a few days ago. "
            "I'm still very interested in what {company} is building.\n\n"
            "If now isn't the right time, I completely understand — happy to reconnect later. "
            "Or if you could point me to the right person on your team, that would be great.\n\n"
            "Thanks for your time,\n{sender_name}"
        ),
    },
    {
        "variant": "B",
        "subject": "Quick follow-up",
        "body": (
            "Hi {name},\n\n"
            "Wanted to circle back on my earlier email. I know inboxes get busy!\n\n"
            "I'm particularly interested in {company} given your work in {topic}. "
            "If there's a better way to connect — or a colleague who handles hiring — I'm flexible.\n\n"
            "Best,\n{sender_name}"
        ),
    },
]

_FOLLOW_UP_2_TEMPLATES = [
    {
        "variant": "A",
        "subject": "Last note — {company}",
        "body": (
            "Hi {name},\n\n"
            "I'll keep this brief — this is my last follow-up so I don't clutter your inbox.\n\n"
            "If {company} ever needs a backend/full-stack engineer with experience in {skills}, "
            "I'd love to be considered. My portfolio is at [your link].\n\n"
            "Wishing you and the team the best,\n{sender_name}"
        ),
    },
]

_TEMPLATES_BY_STAGE: dict[str, list[dict]] = {
    "initial": _INITIAL_TEMPLATES,
    "follow_up_1": _FOLLOW_UP_1_TEMPLATES,
    "follow_up_2": _FOLLOW_UP_2_TEMPLATES,
}


def _fill_template(template: str, context: dict) -> str:
    """Fill template placeholders with context, leaving unfilled ones in."""
    for key, value in context.items():
        template = template.replace(f"{{{key}}}", str(value))
    return template


def _count_words(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Template drafter
# ---------------------------------------------------------------------------

def draft_with_template(
    stage: str,
    contact_name: str,
    company: str,
    sender_name: str = "Nikhil",
    skills: str = "Python, backend engineering, distributed systems",
    industry: str = "technology",
    topic: str = "your engineering challenges",
    experience: str = "3",
    variant_id: str | None = None,
) -> DraftResult:
    """Generate a draft from pre-written templates."""
    templates = _TEMPLATES_BY_STAGE.get(stage, _INITIAL_TEMPLATES)

    if variant_id:
        tmpl = next((t for t in templates if t["variant"] == variant_id), templates[0])
    else:
        tmpl = random.choice(templates)

    context = {
        "name": contact_name or "there",
        "company": company or "your company",
        "sender_name": sender_name,
        "skills": skills,
        "industry": industry,
        "topic": topic,
        "experience": experience,
    }

    subject = _fill_template(tmpl["subject"], context)
    body = _fill_template(tmpl["body"], context)

    # Enforce 150-word limit on body
    words = body.split()
    if len(words) > 150:
        body = " ".join(words[:150]) + "\n\n[Truncated — edit before sending]"

    return DraftResult(
        subject=subject,
        body=body,
        variant_id=tmpl["variant"],
        drafted_by="template",
        word_count=_count_words(body),
    )


# ---------------------------------------------------------------------------
# LLM drafter (optional — falls back to template)
# ---------------------------------------------------------------------------

def draft_with_llm(
    stage: str,
    contact_name: str,
    company: str,
    sender_name: str = "Nikhil",
    skills: str = "Python, backend engineering",
    job_title: str = "",
    signal_context: str = "",
    variant_id: str = "A",
) -> DraftResult:
    """Generate a draft using LLM (OpenAI). Falls back to template if unavailable."""
    try:
        from src.llm.client import get_client
        client = get_client()

        stage_label = {
            "initial": "a cold outreach email",
            "follow_up_1": "a first follow-up email (they haven't replied)",
            "follow_up_2": "a final follow-up email (last attempt, keep it graceful)",
        }.get(stage, "an outreach email")

        signal_note = f"\nContext about the company: {signal_context}" if signal_context else ""
        job_note = f"\nTarget role: {job_title}" if job_title else ""

        prompt = (
            f"Write {stage_label} from {sender_name} to {contact_name or 'a hiring manager'} "
            f"at {company or 'their company'}.\n"
            f"Sender's skills: {skills}.{job_note}{signal_note}\n\n"
            "Requirements:\n"
            "- Max 120 words for the body\n"
            "- No fake claims or fake mutual connections\n"
            "- One clear ask (brief call or reply)\n"
            "- Professional but warm tone\n"
            "- No generic fluff\n\n"
            "Output format:\n"
            "SUBJECT: <subject line>\n"
            "BODY:\n<body text>"
        )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse subject / body
        subject, body = "", text
        if "SUBJECT:" in text and "BODY:" in text:
            lines = text.split("\n")
            sub_line = next((l for l in lines if l.startswith("SUBJECT:")), "")
            subject = sub_line.replace("SUBJECT:", "").strip()
            body_idx = text.index("BODY:") + len("BODY:")
            body = text[body_idx:].strip()

        # Enforce 150-word limit
        words = body.split()
        if len(words) > 150:
            body = " ".join(words[:150])

        if not subject:
            subject = f"Interested in opportunities at {company}"

        return DraftResult(
            subject=subject,
            body=body,
            variant_id=variant_id,
            drafted_by="llm",
            word_count=_count_words(body),
        )
    except Exception:
        # Fall back to template silently
        return draft_with_template(
            stage=stage,
            contact_name=contact_name,
            company=company,
            sender_name=sender_name,
            skills=skills,
            variant_id=variant_id,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_draft(
    stage: str,
    contact_name: str,
    company: str,
    sender_name: str = "Nikhil",
    skills: str = "Python, backend engineering, distributed systems",
    job_title: str = "",
    signal_context: str = "",
    use_llm: bool = False,
    variant_id: str | None = None,
) -> DraftResult:
    """Generate a draft for the given stage. LLM optional, template always available."""
    if use_llm:
        return draft_with_llm(
            stage=stage,
            contact_name=contact_name,
            company=company,
            sender_name=sender_name,
            skills=skills,
            job_title=job_title,
            signal_context=signal_context,
            variant_id=variant_id or "A",
        )
    return draft_with_template(
        stage=stage,
        contact_name=contact_name,
        company=company,
        sender_name=sender_name,
        skills=skills,
        variant_id=variant_id,
    )
