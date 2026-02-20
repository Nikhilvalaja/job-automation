"""Prompt templates for LLM-powered features.

All prompts are defined here as constants for easy tuning and testing.
"""

COVER_LETTER_SYSTEM = """You are an expert career coach and professional writer.
You write compelling, personalized cover letters that:
- Are concise (300-400 words max)
- Open with a strong hook (not "I am writing to apply...")
- Highlight 2-3 specific achievements relevant to the role
- Show genuine knowledge of the company
- Match the tone to the industry (formal for finance, energetic for startups)
- End with a confident call to action
- Never use generic filler phrases

Format: Plain text paragraphs (no headers, no bullet points, no signatures).
Do NOT include the applicant's address, date, or "Dear Hiring Manager" — just the body text."""

COVER_LETTER_USER = """Write a cover letter for this position:

**Company:** {company}
**Role:** {role}

**Job Description:**
{job_description}

{resume_section}

Write the cover letter body now. Be specific and compelling."""

COVER_LETTER_TEMPLATE = """Dear Hiring Team at {company},

I am excited to apply for the {role} position at {company}. With my background in software engineering and passion for building impactful products, I believe I would be a strong addition to your team.

Throughout my career, I have developed expertise in designing and implementing scalable systems, collaborating cross-functionally, and delivering high-quality solutions under tight deadlines. I am particularly drawn to {company}'s mission and the opportunity to contribute to meaningful work.

I would welcome the chance to discuss how my skills and experience align with your team's needs. Thank you for considering my application.

Best regards"""
