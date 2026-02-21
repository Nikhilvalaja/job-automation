"""Job discovery sources — RSS feeds, public APIs, and career page monitors.

500+ sources covering:
- 20+ public job board APIs & RSS feeds (no key needed)
- 200+ Greenhouse-hosted company career feeds
- 90+ Lever-hosted company career feeds
- 40+ Ashby-hosted company career feeds
- 80+ SmartRecruiters-hosted enterprise career feeds
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
    """Greenhouse JSON API — returns ALL roles for a company."""
    return JobSource(name=name, source_type=SourceType.API,
                     parser="greenhouse",
                     url_template=f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                     rate_limit_seconds=1.0)


def _lever(name: str, slug: str) -> JobSource:
    """Lever JSON API — returns all open postings for a company."""
    return JobSource(name=name, source_type=SourceType.API,
                     parser="lever",
                     url_template=f"https://api.lever.co/v0/postings/{slug}?mode=json",
                     rate_limit_seconds=1.0)


def _ashby(name: str, slug: str) -> JobSource:
    """Ashby JSON API — returns open job postings for a company."""
    return JobSource(name=name, source_type=SourceType.API,
                     parser="ashby",
                     url_template=f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                     rate_limit_seconds=1.0)


def _sr(name: str, slug: str) -> JobSource:
    """SmartRecruiters JSON API — enterprise companies worldwide."""
    return JobSource(name=name, source_type=SourceType.API,
                     parser="smartrecruiters",
                     url_template=f"https://careers.smartrecruiters.com/{slug}/postings?format=json&limit=100",
                     rate_limit_seconds=1.5)


# ---------------------------------------------------------------------------
# Public Job Board APIs (free, no API key required)
# ---------------------------------------------------------------------------

JOB_BOARD_SOURCES = [
    # ---- APIs (highest quality, structured data) ----
    JobSource(name="RemoteOK", source_type=SourceType.API,
              url_template="https://remoteok.com/api", parser="remoteok",
              headers={"User-Agent": "JobPilot/1.0 (job search assistant)"}),
    JobSource(name="Arbeitnow", source_type=SourceType.API,
              url_template="https://www.arbeitnow.com/api/job-board-api", parser="arbeitnow"),
    # Remotive — all remote jobs, multiple categories
    JobSource(name="Remotive (Engineering)", source_type=SourceType.API,
              url_template="https://remotive.com/api/remote-jobs?category=software-dev&limit=100",
              parser="remotive", rate_limit_seconds=2.0),
    JobSource(name="Remotive (DevOps)", source_type=SourceType.API,
              url_template="https://remotive.com/api/remote-jobs?category=devops-sysadmin&limit=100",
              parser="remotive", rate_limit_seconds=2.0),
    JobSource(name="Remotive (Data)", source_type=SourceType.API,
              url_template="https://remotive.com/api/remote-jobs?category=data&limit=100",
              parser="remotive", rate_limit_seconds=2.0),
    # Jobicy — remote jobs feed
    JobSource(name="Jobicy", source_type=SourceType.API,
              url_template="https://jobicy.com/api/v2/remote-jobs?count=100", parser="jobicy"),
    # FindWork — tech jobs
    JobSource(name="FindWork", source_type=SourceType.API,
              url_template="https://findwork.dev/api/jobs/?sort_by=relevance", parser="findwork"),
    # Himalayas — quality remote jobs
    JobSource(name="Himalayas", source_type=SourceType.API,
              url_template="https://himalayas.app/jobs/api?limit=100", parser="himalayas"),

    # ---- RSS Feeds (still working) ----
    JobSource(name="We Work Remotely (Backend)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (Full-Stack)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (DevOps)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (Data)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/categories/remote-data-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="We Work Remotely (All)", source_type=SourceType.RSS,
              url_template="https://weworkremotely.com/remote-jobs.rss",
              rate_limit_seconds=2.0),
    JobSource(name="Remotive RSS", source_type=SourceType.RSS,
              url_template="https://remotive.com/rss/remote-jobs/software-dev",
              rate_limit_seconds=2.0),
    JobSource(name="Remote.co RSS", source_type=SourceType.RSS,
              url_template="https://remote.co/remote-jobs/feed/",
              rate_limit_seconds=2.0),
    JobSource(name="BuiltIn (Engineering)", source_type=SourceType.RSS,
              url_template="https://builtin.com/jobs/remote/dev-engineering/entry-level/mid-level/senior/rss",
              rate_limit_seconds=3.0),
    JobSource(name="BuiltIn (Data)", source_type=SourceType.RSS,
              url_template="https://builtin.com/jobs/remote/data-analytics/entry-level/mid-level/senior/rss",
              rate_limit_seconds=3.0),
    JobSource(name="AngelList RSS", source_type=SourceType.RSS,
              url_template="https://angel.co/job_listings.rss",
              rate_limit_seconds=3.0),
    JobSource(name="Y Combinator Jobs", source_type=SourceType.RSS,
              url_template="https://news.ycombinator.com/jobs.rss",
              rate_limit_seconds=2.0),
    # HN Who's Hiring — monthly thread parsing
    JobSource(name="HN Who's Hiring", source_type=SourceType.API,
              url_template="https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
              parser="hackernews", rate_limit_seconds=1.0),

    # The Muse — 20K+ quality US tech jobs, multiple role categories
    JobSource(name="The Muse (Engineering)", source_type=SourceType.API,
              url_template="https://www.themuse.com/api/public/jobs?level=Mid%20Level&level=Entry%20Level&level=Senior%20Level&category=Software%20Engineer&page=0&descending=true",
              parser="muse", rate_limit_seconds=2.0),
    JobSource(name="The Muse (Data Science)", source_type=SourceType.API,
              url_template="https://www.themuse.com/api/public/jobs?level=Mid%20Level&level=Entry%20Level&level=Senior%20Level&category=Data%20Science&page=0&descending=true",
              parser="muse", rate_limit_seconds=2.0),
    JobSource(name="The Muse (IT)", source_type=SourceType.API,
              url_template="https://www.themuse.com/api/public/jobs?level=Mid%20Level&level=Entry%20Level&level=Senior%20Level&category=IT&page=0&descending=true",
              parser="muse", rate_limit_seconds=2.0),
    JobSource(name="The Muse (Product)", source_type=SourceType.API,
              url_template="https://www.themuse.com/api/public/jobs?level=Mid%20Level&level=Entry%20Level&level=Senior%20Level&category=Product&page=1&descending=true",
              parser="muse", rate_limit_seconds=2.0),
    JobSource(name="The Muse (Analytics)", source_type=SourceType.API,
              url_template="https://www.themuse.com/api/public/jobs?level=Mid%20Level&level=Entry%20Level&level=Senior%20Level&category=Analytics&page=0&descending=true",
              parser="muse", rate_limit_seconds=2.0),
    # Adzuna (needs free API key — set ADZUNA_APP_ID + ADZUNA_API_KEY in .env)
    # JobSource(name="Adzuna (US Tech)", source_type=SourceType.API,
    #           url_template="https://api.adzuna.com/v1/api/jobs/us/search/1?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_API_KEY}&results_per_page=50&what=software+engineer&content-type=application/json",
    #           parser="adzuna", rate_limit_seconds=2.0, enabled=False),
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

    # More AI / ML companies
    _gh("Aleph Alpha", "alephalpha"),
    _gh("Typeface", "typeface"),
    _gh("Writer AI", "writer"),
    _gh("Coze AI", "cozeai"),
    _gh("Gleen AI", "gleenai"),
    _gh("Magic AI", "magicai"),
    _gh("Imbue AI", "imbue"),
    _gh("Abacus AI", "abacusai"),
    _gh("Mosaic ML", "mosaicml"),
    _gh("Alectio", "alectio"),
    _gh("Gretel AI", "gretelai"),
    _gh("Pachyderm", "pachyderm"),
    _gh("Fiddler AI", "fiddlerlabs"),
    _gh("Evidently AI", "evidentlyai"),
    _gh("Arthur AI", "arthur"),
    _gh("Weights & Biases (2)", "weightsandbiases"),
    _gh("Determined AI", "determinedai"),
    _gh("Run AI", "runai"),
    _gh("OctoML", "octoml"),
    _gh("Modular", "modular"),
    _gh("Groq AI", "groq"),
    _gh("SambaNova", "sambanova"),
    _gh("Graphcore", "graphcore"),
    _gh("Mythic", "mythic"),

    # More SaaS / B2B
    _gh("Algolia", "algolia"),
    _gh("Braze", "braze"),
    _gh("Iterable", "iterable"),
    _gh("Klaviyo", "klaviyo"),
    _gh("Attentive", "attentive"),
    _gh("Sendbird", "sendbird"),
    _gh("Mixpanel", "mixpanel"),
    _gh("FullStory", "fullstory"),
    _gh("LogRocket", "logrocket"),
    _gh("Hotjar", "hotjar"),
    _gh("Heap Analytics", "heap"),
    _gh("Contentsquare", "contentsquare"),
    _gh("Dynatrace", "dynatrace"),
    _gh("AppDynamics", "appdynamics"),
    _gh("Sumo Logic", "sumologic"),
    _gh("Honeycomb", "honeycomb"),
    _gh("CircleCI", "circleci"),
    _gh("Harness", "harness"),
    _gh("Astronomer", "astronomer"),
    _gh("Atlan", "atlan"),
    _gh("Alation", "alation"),
    _gh("Collibra", "collibra"),
    _gh("Informatica", "informatica"),
    _gh("DataRobot", "datarobot"),
    _gh("H2O.ai", "h2oai"),
    _gh("Domino Data Lab", "dominodatalab"),
    _gh("Alteryx", "alteryx"),
    _gh("ThoughtSpot", "thoughtspot"),
    _gh("Sigma Computing", "sigmacomputing"),
    _gh("Starburst (2)", "starburstdata"),
    _gh("Dremio", "dremio"),
    _gh("Rockset", "rockset"),
    _gh("Pinecone", "pinecone"),
    _gh("Weaviate", "weaviate"),
    _gh("Qdrant", "qdrant"),
    _gh("Chroma DB", "chroma"),
    _gh("Milvus", "milvus"),
    _gh("Zilliz", "zilliz"),

    # More Fintech
    _gh("Robinhood", "robinhood"),
    _gh("SoFi", "sofi"),
    _gh("Nerdwallet", "nerdwallet"),
    _gh("Credit Karma", "creditkarma"),
    _gh("Blend", "blend"),
    _gh("Figure", "figure"),
    _gh("Divvy", "divvy"),
    _gh("Kabbage", "kabbage"),
    _gh("Carta", "carta"),
    _gh("Rippling", "rippling"),
    _gh("Deel (GH)", "deel"),
    _gh("Remote (GH)", "remote"),
    _gh("Oyster HR", "oysterhr"),
    _gh("Paylocity", "paylocity"),
    _gh("Paycom", "paycom"),
    _gh("ADP (GH)", "adp"),
    _gh("Paychex", "paychex"),
    _gh("Toast", "toast"),
    _gh("Square (GH)", "square"),
    _gh("Adyen", "adyen"),
    _gh("Checkout.com", "checkoutcom"),
    _gh("Rapyd", "rapyd"),

    # Media / Publishing
    _gh("New York Times", "nytimes"),
    _gh("Vox Media", "voxmedia"),
    _gh("BuzzFeed", "buzzfeed"),
    _gh("The Atlantic", "theatlantic"),
    _gh("Condé Nast", "condenast"),
    _gh("Hearst", "hearst"),
    _gh("Spotify (GH)", "spotifytechnology"),
    _gh("SoundCloud", "soundcloud"),
    _gh("Pandora", "pandora"),
    _gh("Deezer", "deezer"),

    # Healthcare Tech
    _gh("Teladoc", "teladoc"),
    _gh("One Medical (GH)", "onemedical"),
    _gh("Zocdoc", "zocdoc"),
    _gh("HealthJoy", "healthjoy"),
    _gh("Accolade", "accolade"),
    _gh("Clarify Health", "clarifyhealth"),
    _gh("Collective Health", "collectivehealth"),
    _gh("Bright Health", "brighthealth"),
    _gh("Privia Health", "priviahealth"),
    _gh("PointClickCare", "pointclickcare"),
    _gh("athenahealth", "athenahealth"),
    _gh("Veracyte", "veracyte"),
    _gh("Natera", "natera"),
    _gh("10x Genomics", "10xgenomics"),
    _gh("Pacific Biosciences", "pacificbiosciences"),
    _gh("Benchling", "benchling"),
    _gh("Gingko Bioworks", "ginkgobioworks"),
    _gh("Recursion Pharma", "recursionpharmaceuticals"),

    # Legal Tech / Compliance
    _gh("Ironclad (GH)", "ironclad"),
    _gh("ContractPodAi", "contractpodai"),
    _gh("Clio", "clio"),
    _gh("MyCase", "mycase"),
    _gh("Relativity", "relativity"),
    _gh("Everlaw", "everlaw"),
    _gh("Logikcull", "logikcull"),
    _gh("Disco Legal", "csdisco"),

    # PropTech / Real Estate
    _gh("CoStar Group", "costargroup"),
    _gh("Loftium", "loftium"),
    _gh("Arrived Homes", "arrivedhomes"),
    _gh("Vacasa", "vacasa"),
    _gh("Sonder", "sonder"),
    _gh("Evolve Vacation", "evolve"),
    _gh("TurnKey", "turnkeyvr"),

    # More Cloud / DevOps / Infra
    _gh("Fastly", "fastly"),
    _gh("Cloudinary", "cloudinary"),
    _gh("Akamai", "akamai"),
    _gh("Rackspace", "rackspace"),
    _gh("Pure Storage", "purestorage"),
    _gh("NetApp", "netapp"),
    _gh("Nutanix", "nutanix"),
    _gh("VMware (GH)", "vmware"),
    _gh("Palo Alto Networks (2)", "paloaltonetworks2"),
    _gh("Fortinet", "fortinet"),
    _gh("Qualys", "qualys"),
    _gh("Rapid7", "rapid7"),
    _gh("Tenable", "tenable"),
    _gh("CyberArk", "cyberark"),
    _gh("Duo Security", "duo"),
    _gh("SailPoint", "sailpoint"),
    _gh("BeyondTrust", "beyondtrust"),
    _gh("Ping Identity", "pingidentity"),
    _gh("ForgeRock", "forgerock"),

    # Enterprise / Supply Chain
    _gh("Coupa Software", "coupa"),
    _gh("Jaggaer", "jaggaer"),
    _gh("Ivalua", "ivalua"),
    _gh("Zycus", "zycus"),
    _gh("GEP Worldwide", "gep"),
    _gh("Netsuite (GH)", "netsuite"),
    _gh("Sage Group", "sage"),
    _gh("Epicor", "epicor"),
    _gh("IFS", "ifs"),
    _gh("Unit4", "unit4"),
    _gh("Infor", "infor"),

    # Climate / Sustainability Tech
    _gh("Samsara", "samsara"),
    _gh("Arcadia Power", "arcadia"),
    _gh("Stem Inc", "stem"),
    _gh("Omnidian", "omnidian"),
    _gh("Sunrun", "sunrun"),
    _gh("Sunpower", "sunpower"),
    _gh("Sunnova", "sunnova"),
    _gh("Energy Vault", "energyvault"),
    _gh("Form Energy", "formenergy"),
    _gh("Turntide Technologies", "turntide"),
    _gh("Redwood Materials", "redwoodmaterials"),
    _gh("Li-Cycle", "licycle"),
    _gh("Twelve CO2", "twelve"),

    # Food / Agriculture Tech
    _gh("Apeel Sciences", "apeel"),
    _gh("AeroFarms", "aerofarms"),
    _gh("AppHarvest", "appharvest"),
    _gh("Plenty", "plentyag"),
    _gh("Bowery Farming", "bowery"),
    _gh("NotCo", "notco"),
    _gh("Eat Just", "eatjust"),
    _gh("Impossible Foods", "impossiblefoods"),

    # Additional popular tech companies
    _gh("Quora", "quora"),
    _gh("Dropbox", "dropbox"),
    _gh("Box (GH)", "box"),
    _gh("Evernote", "evernote"),
    _gh("LastPass", "lastpass"),
    _gh("Dashlane", "dashlane"),
    _gh("Bitwarden", "bitwarden"),
    _gh("NordSecurity", "nordsec"),
    _gh("ExpressVPN", "expressvpn"),
    _gh("Surfshark", "surfshark"),
    _gh("Cloudflare (2)", "cloudflaredev"),
    _gh("Fastmail", "fastmail"),
    _gh("ProtonMail", "proton"),
    _gh("Tutanota", "tutanota"),
    _gh("Skiff", "skiff"),
    _gh("Notion (GH2)", "notionlabs"),
    _gh("Craft Docs", "craft"),
    _gh("Obsidian", "obsidian"),
    _gh("Roam Research", "roamresearch"),
    _gh("Mem", "mem"),
    _gh("Logseq", "logseq"),
    _gh("Capacities", "capacities"),
    _gh("Tana", "tana"),
    _gh("Readwise", "readwise"),
    _gh("Matter Reader", "matter"),
    _gh("Pocket (GH)", "pocket"),
    _gh("Instapaper", "instapaper"),
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
    # More Lever companies (expanded list)
    _lever("Asana (Lever)", "asana"),
    _lever("Dropbox (Lever)", "dropbox"),
    _lever("Box (Lever)", "box"),
    _lever("RingCentral", "ringcentral"),
    _lever("Dialpad", "dialpad"),
    _lever("Vonage", "vonage"),
    _lever("Twilio (Lever)", "twilio"),
    _lever("Zendesk (Lever)", "zendesk"),
    _lever("HubSpot (Lever)", "hubspot"),
    _lever("Marketo", "marketo"),
    _lever("Pardot", "pardot"),
    _lever("Mailchimp", "mailchimp"),
    _lever("Klaviyo (Lever)", "klaviyo"),
    _lever("Braze (Lever)", "braze"),
    _lever("Iterable (Lever)", "iterable"),
    _lever("Customer.io", "customerio"),
    _lever("Amplitude (Lever)", "amplitude"),
    _lever("Mixpanel (Lever)", "mixpanel"),
    _lever("FullStory (Lever)", "fullstory"),
    _lever("Heap (Lever)", "heap"),
    _lever("Segment (Lever)", "segment"),
    _lever("Treasure Data", "treasuredata"),
    _lever("mParticle", "mparticle"),
    _lever("Rudderstack", "rudderstack"),
    _lever("Census (Lever)", "census"),
    _lever("Hightouch (Lever)", "hightouch"),
    _lever("Stitch Data", "stitch"),
    _lever("Matillion", "matillion"),
    _lever("Airbyte (Lever)", "airbyte"),
    _lever("Fivetran (Lever)", "fivetran"),
    _lever("Talend", "talend"),
    _lever("MuleSoft", "mulesoft"),
    _lever("Boomi", "boomi"),
    _lever("Jitterbit", "jitterbit"),
    _lever("Workato", "workato"),
    _lever("Tray.io", "tray"),
    _lever("Celigo", "celigo"),
    _lever("Cyclr", "cyclr"),
    _lever("Pipedream", "pipedream"),
    _lever("n8n", "n8n"),
    _lever("Make (Integromat)", "make"),
    _lever("Pabbly", "pabbly"),
    _lever("Latenode", "latenode"),
    _lever("Alloy Automation", "alloy"),
    _lever("Linear (Lever)", "linear"),
    _lever("Loom (Lever)", "loom"),
    _lever("Coda (Lever2)", "coda2"),
    _lever("Range", "range"),
    _lever("Basecamp", "basecamp"),
    _lever("ClickUp", "clickup"),
    _lever("Height App", "height"),
    _lever("Plane", "plane"),
    _lever("Shortcut", "shortcut"),
    _lever("Jira (Atlassian)", "atlassian"),
    _lever("Trello (Lever)", "trello"),
    _lever("Miro (Lever)", "miro"),
    _lever("Mural", "mural"),
    _lever("FigJam", "figjam"),
    _lever("Excalidraw", "excalidraw"),
    _lever("Whimsical", "whimsical"),
    _lever("Overflow", "overflow"),
    _lever("Balsamiq", "balsamiq"),
    _lever("Maze", "maze"),
    _lever("UsabilityHub", "usabilityhub"),
    _lever("Sprig", "sprig"),
    _lever("Pendo (Lever)", "pendo"),
    _lever("Appcues", "appcues"),
    _lever("Intercom (Lever)", "intercom"),
    _lever("Drift", "drift"),
    _lever("Zendesk Chat", "zendeskgarden"),
    _lever("Freshdesk", "freshdesk"),
    _lever("Gladly", "gladly"),
    _lever("Kustomer", "kustomer"),
    _lever("Gorgias", "gorgias"),
    _lever("Reamaze", "reamaze"),
    _lever("Help Scout", "helpscout"),
    _lever("Groove", "groove"),
    _lever("HappyFox", "happyfox"),
    _lever("Jira Service", "jiraservice"),
    _lever("ServiceNow (Lever)", "servicenow"),
    _lever("BMC Software", "bmc"),
    _lever("Cherwell", "cherwell"),
    _lever("TOPdesk", "topdesk"),
    _lever("Remedy", "remedy"),
    _lever("SolarWinds", "solarwinds"),
    _lever("ManageEngine", "manageengine"),
    _lever("Freshservice", "freshservice"),
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
    # More Ashby companies
    _ashby("Luma", "luma"),
    _ashby("Fathom", "fathom"),
    _ashby("Cal.com", "calcom"),
    _ashby("Rewind AI", "rewind"),
    _ashby("Raycast", "raycast"),
    _ashby("Fig", "fig"),
    _ashby("Zed Industries", "zed"),
    _ashby("Pieces", "pieces"),
    _ashby("Novu", "novu"),
    _ashby("Trieve", "trieve"),
    _ashby("Browserbase", "browserbase"),
    _ashby("E2B", "e2b"),
    _ashby("Composio", "composio"),
    _ashby("Skyvern AI", "skyvern"),
    _ashby("Dify AI", "dify"),
    _ashby("Braintrust", "braintrust"),
    _ashby("Credal AI", "credal"),
    _ashby("Humanloop", "humanloop"),
    _ashby("Vapi AI", "vapi"),
    _ashby("ElevenLabs", "elevenlabs"),
    _ashby("Cartesia", "cartesia"),
    _ashby("Coqui", "coqui"),
    _ashby("Hedra", "hedra"),
    _ashby("Pika Labs", "pika"),
    _ashby("Luma Dream Machine", "lumai"),
]

# ---------------------------------------------------------------------------
# SmartRecruiters-hosted careers (80+ enterprise companies worldwide)
# Format: careers.smartrecruiters.com/{slug}/postings?format=json
# ---------------------------------------------------------------------------

SMARTRECRUITERS_FEEDS = [
    # Global Technology Consulting
    _sr("Accenture", "AccentureTechnology"),
    _sr("Capgemini", "Capgemini"),
    _sr("Infosys", "Infosys"),
    _sr("Wipro", "Wipro"),
    _sr("Tata Consultancy", "TataConsultancyServices"),
    _sr("HCL Technologies", "HCLTechnologies"),
    _sr("Cognizant", "Cognizant"),
    _sr("DXC Technology", "DXCTechnology"),
    _sr("CGI Group", "CGI"),
    _sr("Sopra Steria", "SopraSteria"),

    # Financial Services / Insurance
    _sr("KPMG", "KPMG"),
    _sr("PwC", "PwC"),
    _sr("Deloitte", "DeloitteUS"),
    _sr("Allianz", "Allianz"),
    _sr("ING", "ING"),
    _sr("Zurich Insurance", "ZurichInsurance"),
    _sr("AXA", "AXA"),
    _sr("Visa", "Visa"),
    _sr("Mastercard", "Mastercard"),
    _sr("American Express", "AmericanExpress"),
    _sr("Deutsche Bank", "DeutscheBank"),
    _sr("Commerzbank", "Commerzbank"),
    _sr("BBVA", "BBVA"),
    _sr("Santander", "Santander"),
    _sr("BNP Paribas", "BNPParibas"),
    _sr("Credit Agricole", "CreditAgricole"),
    _sr("ING Direct", "INGDirect"),

    # Technology / Electronics
    _sr("Philips", "Philips"),
    _sr("Siemens", "Siemens"),
    _sr("Ericsson", "Ericsson"),
    _sr("Nokia", "Nokia"),
    _sr("Bosch", "BoschGroup"),
    _sr("SAP", "SAP"),
    _sr("LG Electronics", "LGElectronics"),
    _sr("Panasonic", "Panasonic"),
    _sr("Fujitsu", "Fujitsu"),
    _sr("NEC", "NEC"),
    _sr("Huawei", "Huawei"),
    _sr("Lenovo", "Lenovo"),
    _sr("Logitech", "Logitech"),
    _sr("Zebra Technologies", "ZebraTechnologies"),
    _sr("Keysight Technologies", "KeysightTechnologies"),
    _sr("Trimble", "Trimble"),

    # E-commerce / Retail
    _sr("Zalando", "Zalando"),
    _sr("About You", "AboutYou"),
    _sr("Delivery Hero", "DeliveryHero"),
    _sr("HelloFresh", "HelloFresh"),
    _sr("Wayfair", "Wayfair"),
    _sr("Booking.com", "Booking"),
    _sr("trivago", "trivago"),
    _sr("TUI", "TUIGroup"),
    _sr("Experian", "Experian"),

    # Automotive / Manufacturing
    _sr("Volkswagen Group", "VolkswagenGroup"),
    _sr("BMW Group", "BMWGroup"),
    _sr("Continental AG", "ContinentalAG"),
    _sr("ZF Friedrichshafen", "ZFGroup"),
    _sr("Schaeffler", "Schaeffler"),
    _sr("MAHLE", "MAHLE"),
    _sr("Valeo", "Valeo"),
    _sr("Aptiv", "Aptiv"),
    _sr("Visteon", "Visteon"),

    # Media / Advertising
    _sr("Publicis Groupe", "PublicisGroupe"),
    _sr("Dentsu", "Dentsu"),
    _sr("WPP", "WPP"),
    _sr("IPG", "IPG"),
    _sr("Criteo", "Criteo"),
    _sr("Xandr", "Xandr"),
    _sr("DoubleVerify", "DoubleVerify"),

    # Healthcare / Pharma
    _sr("Bayer", "Bayer"),
    _sr("Merck KGaA", "MerckKGaA"),
    _sr("Sanofi", "Sanofi"),
    _sr("Novartis", "Novartis"),
    _sr("Roche", "Roche"),
    _sr("AstraZeneca", "AstraZeneca"),
    _sr("Abbott", "Abbott"),
    _sr("Becton Dickinson", "BectonDickinson"),
    _sr("Danaher", "Danaher"),
    _sr("IQVIA", "IQVIA"),
    _sr("Medidata Solutions", "Medidata"),

    # Telecom / Infrastructure
    _sr("Deutsche Telekom", "DeutscheTelekom"),
    _sr("Orange", "Orange"),
    _sr("Vodafone", "Vodafone"),
    _sr("Telefonica", "Telefonica"),
    _sr("BT Group", "BTGroup"),
    _sr("Lumen Technologies", "Lumen"),
    _sr("Crown Castle", "CrownCastle"),

    # Energy / Utilities
    _sr("Schneider Electric", "SchneiderElectric"),
    _sr("ABB", "ABB"),
    _sr("Enel", "Enel"),
    _sr("Engie", "Engie"),
    _sr("Vestas", "Vestas"),
    _sr("Siemens Energy", "SiemensEnergy"),
    _sr("GE Renewable Energy", "GEGrid"),

    # Tech startups on SmartRecruiters
    _sr("Amadeus IT", "AmadeusITGroup"),
    _sr("Dassault Systemes", "DassaultSystemes"),
    _sr("ANSYS", "ANSYS"),
    _sr("PTC", "PTC"),
    _sr("OpenText", "OpenText"),
    _sr("Nuance Communications", "Nuance"),
    _sr("Verint Systems", "Verint"),
    _sr("NICE Systems", "NICESystems"),
    _sr("Genesys", "Genesys"),
    _sr("Avaya", "Avaya"),
    _sr("Mitel Networks", "Mitel"),
]

# ---------------------------------------------------------------------------
# All sources combined
# ---------------------------------------------------------------------------

COMPANY_CAREER_FEEDS = BIG_TECH_FEEDS + GREENHOUSE_FEEDS + LEVER_FEEDS + ASHBY_FEEDS + SMARTRECRUITERS_FEEDS
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
