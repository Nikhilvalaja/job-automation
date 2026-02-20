"""Job discovery sources — RSS feeds, public APIs, and career page monitors.

260+ sources covering:
- 14 public job board APIs & RSS feeds (no key needed)
- 150+ Greenhouse-hosted company career feeds
- 65+ Lever-hosted company career feeds
- 30+ Ashby-hosted company career feeds
- Big Tech career RSS feeds

All sources are ToS-compliant:
- RSS feeds are explicitly designed for automated consumption
- Public APIs have documented rate limits we respect
- No scraping of pages that prohibit it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SourceType(str, Enum):
    RSS = "rss"
    API = "api"
    CAREER_RSS = "career_rss"


@dataclass
class JobSource:
    """A single job discovery source."""
    name: str
    source_type: SourceType
    url_template: str
    enabled: bool = True
    rate_limit_seconds: float = 2.0
    parser: str = "default"
    headers: dict = field(default_factory=dict)


def _gh(name: str, slug: str) -> JobSource:
    """Shorthand to create a Greenhouse career feed source."""
    return JobSource(name=name, source_type=SourceType.CAREER_RSS,
                     url_template=f"https://boards.greenhouse.io/{slug}/feed")


def _lever(name: str, slug: str) -> JobSource:
    """Shorthand to create a Lever career feed source."""
    return JobSource(name=name, source_type=SourceType.CAREER_RSS,
                     url_template=f"https://jobs.lever.co/{slug}/feed")


def _ashby(name: str, slug: str) -> JobSource:
    """Shorthand to create an Ashby career feed source."""
    return JobSource(name=name, source_type=SourceType.CAREER_RSS,
                     url_template=f"https://jobs.ashbyhq.com/{slug}/feed")


# ---------------------------------------------------------------------------
# Public Job Board APIs (free, no API key required)
# ---------------------------------------------------------------------------

JOB_BOARD_SOURCES = [
    JobSource(name="RemoteOK", source_type=SourceType.API,
              url_template="https://remoteok.com/api", parser="remoteok",
              headers={"User-Agent": "JobPilot/1.0 (job search assistant)"}),
    JobSource(name="Arbeitnow", source_type=SourceType.API,
              url_template="https://www.arbeitnow.com/api/job-board-api", parser="arbeitnow"),
    JobSource(name="Indeed", source_type=SourceType.RSS,
              url_template="https://www.indeed.com/rss?q={query}&l={location}&sort=date",
              rate_limit_seconds=3.0),
    JobSource(name="HN Who's Hiring", source_type=SourceType.API,
              url_template="https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
              parser="hackernews", rate_limit_seconds=1.0),
    JobSource(name="Jobicy", source_type=SourceType.API,
              url_template="https://jobicy.com/api/v2/remote-jobs?count=50&tag={query}", parser="jobicy"),
    JobSource(name="FindWork", source_type=SourceType.API,
              url_template="https://findwork.dev/api/jobs/?search={query}&sort_by=relevance", parser="findwork"),
    # Additional job board feeds
    JobSource(name="We Work Remotely", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (Full-Stack)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (Front-End)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (DevOps)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (Data)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-data-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="BuiltIn", source_type=SourceType.RSS,
              url_template="https://builtin.com/jobs/remote/dev-engineering/entry-level/mid-level/senior/rss",
              rate_limit_seconds=3.0),
    JobSource(name="BuiltIn (Data Science)", source_type=SourceType.RSS,
              url_template="https://builtin.com/jobs/remote/data-analytics/entry-level/mid-level/senior/rss",
              rate_limit_seconds=3.0),
    JobSource(name="Himalayas", source_type=SourceType.API,
              url_template="https://himalayas.app/jobs/api?limit=50", parser="himalayas"),
]

# ---------------------------------------------------------------------------
# Big Tech Career RSS
# ---------------------------------------------------------------------------

BIG_TECH_FEEDS = [
    JobSource(name="Google Careers", source_type=SourceType.CAREER_RSS,
              url_template="https://careers.google.com/jobs/results/rss/?q={query}"),
    JobSource(name="Microsoft Careers", source_type=SourceType.CAREER_RSS,
              url_template="https://careers.microsoft.com/professionals/us/en/rss?q={query}"),
    JobSource(name="Apple Careers", source_type=SourceType.CAREER_RSS,
              url_template="https://jobs.apple.com/en-us/search?search={query}&rss=true"),
]

# ---------------------------------------------------------------------------
# Greenhouse-hosted careers (100+ companies)
# Format: https://boards.greenhouse.io/{slug}/feed
# ---------------------------------------------------------------------------

GREENHOUSE_FEEDS = [
    # AI / ML
    _gh("OpenAI", "openai"),
    _gh("Anthropic", "anthropic"),
    _gh("Scale AI", "scaleai"),
    _gh("Cohere", "cohere"),
    _gh("Hugging Face", "huggingface"),
    _gh("Stability AI", "stabilityai"),
    _gh("Inflection AI", "inflectionai"),
    _gh("Adept AI", "adeptailabs"),
    _gh("Character AI", "character"),
    _gh("Mistral AI", "mistral"),
    _gh("Runway", "runwayml"),
    _gh("Jasper AI", "jasper"),
    _gh("Weights & Biases", "wandb"),
    _gh("Together AI", "togetherai"),
    _gh("Cerebras", "cerebras"),
    _gh("Shield AI", "shieldai"),
    _gh("Covariant", "covariant"),
    _gh("Wayve", "wayve"),
    _gh("DeepL", "deepl"),
    _gh("Turing", "turing"),

    # Fintech / Payments
    _gh("Stripe", "stripe"),
    _gh("Coinbase", "coinbase"),
    _gh("Plaid", "plaid"),
    _gh("Ramp", "ramp"),
    _gh("Brex", "brex"),
    _gh("Affirm", "affirm"),
    _gh("Chime", "chime"),
    _gh("Mercury", "mercury"),
    _gh("Marqeta", "marqeta"),
    _gh("Blockchain.com", "blockchain"),
    _gh("Anchorage Digital", "anchoragedigital"),
    _gh("Circle", "circle"),
    _gh("Ripple", "ripple"),
    _gh("Uniswap Labs", "uniswaplabs"),
    _gh("Chainalysis", "chainalysis"),
    _gh("Alchemy", "alchemy"),

    # Quantitative Finance / Trading
    _gh("Two Sigma", "twosigma"),
    _gh("Citadel", "citadel"),
    _gh("Jane Street", "janestreet"),
    _gh("Point72", "point72"),
    _gh("D.E. Shaw", "deshaw"),
    _gh("Jump Trading", "jumptrading"),
    _gh("Hudson River Trading", "hudsonrivertrading"),
    _gh("Bridgewater Associates", "bridgewater"),
    _gh("AQR Capital", "aqr"),

    # Developer Tools / Infra
    _gh("Vercel", "vercel"),
    _gh("Supabase", "supabase"),
    _gh("Cloudflare", "cloudflare"),
    _gh("Datadog", "datadog"),
    _gh("GitLab", "gitlab"),
    _gh("Figma", "figma"),
    _gh("Notion", "notion"),
    _gh("Airtable", "airtable"),
    _gh("Retool", "retool"),
    _gh("PlanetScale", "planetscale"),
    _gh("Fly.io", "flyio"),
    _gh("Railway", "railway"),
    _gh("Render", "render"),
    _gh("Netlify", "netlify"),
    _gh("Snyk", "snyk"),
    _gh("LaunchDarkly", "launchdarkly"),
    _gh("HashiCorp", "hashicorp"),
    _gh("Grafana Labs", "grafanalabs"),
    _gh("Elastic", "elastic"),
    _gh("Kong", "kong"),
    _gh("PostHog", "posthog"),
    _gh("Sentry", "sentry"),
    _gh("DigitalOcean", "digitalocean"),
    _gh("MongoDB", "mongodb"),
    _gh("CockroachDB", "cockroachlabs"),
    _gh("Prisma", "prisma"),
    _gh("Temporal Technologies", "temporaltechnologies"),

    # SaaS / Enterprise
    _gh("Twilio", "twilio"),
    _gh("Zendesk", "zendesk"),
    _gh("HubSpot", "hubspot"),
    _gh("Amplitude", "amplitude"),
    _gh("Segment", "segment"),
    _gh("Contentful", "contentful"),
    _gh("Webflow", "webflow"),
    _gh("Canva", "canva"),
    _gh("Miro", "miro"),
    _gh("Loom", "loom"),
    _gh("Calendly", "calendly"),
    _gh("Intercom", "intercom"),
    _gh("Grammarly", "grammarly"),
    _gh("1Password", "1password"),
    _gh("Zapier", "zapier"),
    _gh("Gusto", "gusto"),
    _gh("Lattice", "lattice"),
    _gh("Dbt Labs", "dbtlabs"),
    _gh("Fivetran", "fivetran"),
    _gh("Asana", "asana"),
    _gh("Monday.com", "mondaycom"),
    _gh("Freshworks", "freshworks"),
    _gh("ServiceNow", "servicenow"),
    _gh("Workday", "workday"),

    # Social / Consumer
    _gh("Discord", "discord"),
    _gh("Twitch", "twitch"),
    _gh("Pinterest", "pinterest"),
    _gh("Bumble", "bumble"),
    _gh("Duolingo", "duolingo"),
    _gh("Calm", "calm"),
    _gh("Strava", "strava"),
    _gh("AllTrails", "alltrails"),
    _gh("Nextdoor", "nextdoor"),
    _gh("BeReal", "bereal"),

    # Security / Cyber
    _gh("CrowdStrike", "crowdstrike"),
    _gh("SentinelOne", "sentinelone"),
    _gh("Palo Alto Networks", "paloaltonetworks"),
    _gh("Okta", "okta"),
    _gh("Wiz", "wiz"),
    _gh("Lacework", "lacework"),
    _gh("Trellix", "trellix"),
    _gh("Recorded Future", "recordedfuture"),

    # Health / Bio
    _gh("Tempus", "tempus"),
    _gh("Ro", "ro"),
    _gh("Hims & Hers", "himsandhers"),
    _gh("Color Health", "color"),
    _gh("Noom", "noom"),
    _gh("Oscar Health", "oscarhealth"),
    _gh("Flatiron Health", "flatironhealth"),
    _gh("Devoted Health", "devotedhealth"),
    _gh("Cityblock Health", "cityblockhealth"),
    _gh("Veeva Systems", "veeva"),

    # E-commerce / Marketplace
    _gh("Instacart", "instacart"),
    _gh("DoorDash", "doordash"),
    _gh("Faire", "faire"),
    _gh("Etsy", "etsy"),
    _gh("Gopuff", "gopuff"),
    _gh("Chewy", "chewy"),
    _gh("Shopify", "shopify"),
    _gh("StockX", "stockx"),
    _gh("Poshmark", "poshmark"),
    _gh("Zillow", "zillow"),
    _gh("Redfin", "redfin"),
    _gh("Compass Real Estate", "compass"),
    _gh("Opendoor", "opendoor"),

    # Autonomous / Robotics / Hardware
    _gh("Cruise", "cruise"),
    _gh("Aurora", "aurora"),
    _gh("Nuro", "nuro"),
    _gh("Zipline", "zipline"),
    _gh("Joby Aviation", "jobyaviation"),
    _gh("Relativity Space", "relativityspace"),
    _gh("Anduril Industries", "andurilindustries"),
    _gh("SpaceX", "spacex"),
    _gh("Palantir", "palantir"),
    _gh("Rivian", "rivian"),
    _gh("Lucid Motors", "lucidmotors"),
    _gh("Archer Aviation", "archeraviation"),
    _gh("Skydio", "skydio"),
    _gh("Boston Dynamics", "bostondynamics"),

    # Data / Analytics
    _gh("Snowflake", "snowflake"),
    _gh("Databricks", "databricks"),
    _gh("Monte Carlo", "montecarlodata"),
    _gh("Hex", "hex"),
    _gh("Mode Analytics", "mode"),
    _gh("Census", "census"),
    _gh("Hightouch", "hightouch"),
    _gh("Airbyte", "airbyte"),
    _gh("Confluent", "confluent"),
    _gh("Starburst", "starburst"),
    _gh("dbt Labs (GH)", "dbtlabsinc"),
    _gh("Immuta", "immuta"),

    # Gaming / Entertainment
    _gh("Riot Games", "riotgames"),
    _gh("Epic Games", "epicgames"),
    _gh("Roblox", "roblox"),
    _gh("Unity", "unity"),
    _gh("Niantic", "niantic"),
    _gh("Supercell", "supercell"),
    _gh("King", "king"),

    # Education
    _gh("Coursera", "coursera"),
    _gh("Khan Academy", "khanacademy"),
    _gh("Chegg", "chegg"),
    _gh("Clever", "clever"),
    _gh("Instructure", "instructure"),

    # Transportation / Logistics
    _gh("Lyft", "lyft"),
    _gh("Uber", "uber"),
    _gh("Waymo", "waymo"),
    _gh("Flexport (GH)", "flexport"),
    _gh("Convoy", "convoy"),

    # Consulting / Professional Services
    _gh("McKinsey Digital", "mckinseydigital"),
    _gh("BCG X", "bcgx"),
    _gh("Slalom", "slalom"),
    _gh("ThoughtWorks", "thoughtworks"),
]

# ---------------------------------------------------------------------------
# Lever-hosted careers (50+ companies)
# Format: https://jobs.lever.co/{slug}/feed
# ---------------------------------------------------------------------------

LEVER_FEEDS = [
    _lever("Netflix", "netflix"),
    _lever("Spotify", "spotify"),
    _lever("Reddit", "reddit"),
    _lever("Anduril", "anduril"),
    _lever("Upstart", "upstart"),
    _lever("Flexport", "flexport"),
    _lever("Cruise Automation", "cruise"),
    _lever("Movable Ink", "movableink"),
    _lever("Whatnot", "whatnot"),
    _lever("Vanta", "vanta"),
    _lever("Modern Treasury", "moderntreasury"),
    _lever("Navan", "navan"),
    _lever("Coda", "coda"),
    _lever("Astra", "astra"),
    _lever("Applied Intuition", "applied"),
    _lever("Persona", "persona"),
    _lever("Watershed", "watershed"),
    _lever("Replit", "replit"),
    _lever("WorkOS", "workos"),
    _lever("Material Security", "materialsecurity"),
    _lever("Pulley", "pulley"),
    _lever("Assembled", "assembled"),
    _lever("Livekit", "livekit"),
    _lever("Epirus", "epirus"),
    _lever("Abridge", "abridge"),
    _lever("Weights & Biases (Lever)", "wandb"),
    _lever("Abnormal Security", "abnormalsecurity"),
    _lever("Island", "island"),
    _lever("Pave", "pave"),
    _lever("Handshake", "joinhandshake"),
    _lever("Alto Pharmacy", "alto"),
    _lever("Vouch Insurance", "vouch"),
    _lever("Tines", "tines"),
    _lever("Sourcegraph", "sourcegraph"),
    _lever("Temporal", "temporal"),
    _lever("Neon", "neon"),
    _lever("Modal", "modal"),
    _lever("Glean", "glean"),
    _lever("Harvey AI", "harvey"),
    _lever("Sierra AI", "sierra"),
    _lever("EvenUp", "evenup"),
    _lever("Coframe", "coframe"),
    _lever("Tome", "tome"),
    _lever("Perplexity", "perplexity"),
    _lever("Cursor", "anysphere"),

    # Additional Lever companies
    _lever("Deel", "deel"),
    _lever("Remote.com", "remote"),
    _lever("Notion (Lever)", "notionhq"),
    _lever("Figma (Lever)", "figma"),
    _lever("Airtable (Lever)", "airtable"),
    _lever("Lemonade", "lemonade"),
    _lever("Chili Piper", "chilipiper"),
    _lever("Drata", "drata"),
    _lever("Gong", "gong"),
    _lever("Outreach", "outreach"),
    _lever("UserTesting", "usertesting"),
    _lever("LaunchDarkly (Lever)", "launchdarkly"),
    _lever("Cockroach Labs (Lever)", "cockroach-labs"),
    _lever("PagerDuty", "pagerduty"),
    _lever("Grafana (Lever)", "grafana"),
    _lever("Tailscale", "tailscale"),
    _lever("Snorkel AI", "snorkelai"),
    _lever("Anyscale", "anyscale"),
    _lever("Weights & Biases V2", "wandbv2"),
    _lever("Ironclad", "ironclad"),
    _lever("Plaid (Lever)", "plaid"),
]

# ---------------------------------------------------------------------------
# Ashby-hosted careers (20+ companies)
# Format: https://jobs.ashbyhq.com/{slug}/feed
# ---------------------------------------------------------------------------

ASHBY_FEEDS = [
    _ashby("Linear", "linear"),
    _ashby("Resend", "resend"),
    _ashby("Clerk", "clerk"),
    _ashby("Inngest", "inngest"),
    _ashby("Tinybird", "tinybird"),
    _ashby("Axiom", "axiom"),
    _ashby("Mintlify", "mintlify"),
    _ashby("Pylon", "pylon"),
    _ashby("Unkey", "unkey"),
    _ashby("Nango", "nango"),
    _ashby("Trigger.dev", "trigger-dev"),
    _ashby("Resonate", "resonate"),
    _ashby("Depot", "depot"),
    _ashby("Turso", "turso"),
    _ashby("Val Town", "val-town"),
    _ashby("SST", "sst"),
    _ashby("Arcjet", "arcjet"),
    _ashby("Knock", "knock"),
    _ashby("Plain", "plain"),
    _ashby("Stainless", "stainlessapi"),

    # Additional Ashby companies
    _ashby("Vercel (Ashby)", "vercel"),
    _ashby("Supabase (Ashby)", "supabase"),
    _ashby("Warp", "warp"),
    _ashby("Fly.io (Ashby)", "fly"),
    _ashby("Railway (Ashby)", "railway"),
    _ashby("Dagster", "dagster"),
    _ashby("Prefect", "prefect"),
    _ashby("Metaplane", "metaplane"),
    _ashby("Modal (Ashby)", "modal"),
    _ashby("Baseten", "baseten"),
]

# ---------------------------------------------------------------------------
# All sources combined
# ---------------------------------------------------------------------------

COMPANY_CAREER_FEEDS = BIG_TECH_FEEDS + GREENHOUSE_FEEDS + LEVER_FEEDS + ASHBY_FEEDS
ALL_SOURCES = JOB_BOARD_SOURCES + COMPANY_CAREER_FEEDS


def get_enabled_sources(source_names: list[str] | None = None) -> list[JobSource]:
    """Get enabled sources, optionally filtered by name."""
    sources = [s for s in ALL_SOURCES if s.enabled]

    if source_names:
        filtered = []
        for s in sources:
            for name in source_names:
                if name.lower() in s.name.lower():
                    filtered.append(s)
                    break
        return filtered

    return sources


def get_greenhouse_feed_url(company_slug: str) -> str:
    """Generate a Greenhouse RSS feed URL for any company."""
    return f"https://boards.greenhouse.io/{company_slug}/feed"


def get_lever_feed_url(company_slug: str) -> str:
    """Generate a Lever RSS feed URL for any company."""
    return f"https://jobs.lever.co/{company_slug}/feed"


def get_ashby_feed_url(company_slug: str) -> str:
    """Generate an Ashby RSS feed URL for any company."""
    return f"https://jobs.ashbyhq.com/{company_slug}/feed"
