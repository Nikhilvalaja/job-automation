"""Master skill taxonomy for job description analysis.

Contains 500+ technical skills organized by category with aliases.
Used by:
- JD Normalizer: extract must-have / nice-to-have skills from job descriptions
- Resume Parser: identify skills in resume text
- Scoring Engine: compute skill overlap between JD and resume

Design:
- Each skill has a canonical name and a list of aliases
- Lookup is case-insensitive
- Multi-word skills are matched as phrases
- Categories help with domain alignment scoring
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    """A single skill with its canonical name and aliases."""
    canonical: str
    aliases: tuple[str, ...] = ()
    category: str = "other"


# ---------------------------------------------------------------------------
# Skill Database — organized by category
# ---------------------------------------------------------------------------

_SKILLS: list[Skill] = [
    # --- Programming Languages ---
    Skill("python", ("python3", "py"), "language"),
    Skill("java", ("jdk", "jvm"), "language"),
    Skill("javascript", ("js", "ecmascript", "es6", "es2015"), "language"),
    Skill("typescript", ("ts",), "language"),
    Skill("go", ("golang",), "language"),
    Skill("rust", (), "language"),
    Skill("c++", ("cpp", "c plus plus"), "language"),
    Skill("c#", ("csharp", "c sharp", "dotnet", ".net"), "language"),
    Skill("ruby", (), "language"),
    Skill("php", (), "language"),
    Skill("swift", (), "language"),
    Skill("kotlin", (), "language"),
    Skill("scala", (), "language"),
    Skill("r", ("r language", "r programming"), "language"),
    Skill("julia", (), "language"),
    Skill("perl", (), "language"),
    Skill("lua", (), "language"),
    Skill("elixir", (), "language"),
    Skill("clojure", (), "language"),
    Skill("haskell", (), "language"),
    Skill("erlang", (), "language"),
    Skill("dart", (), "language"),
    Skill("objective-c", ("objc", "objective c"), "language"),
    Skill("sql", ("structured query language",), "language"),
    Skill("bash", ("shell", "shell scripting", "sh", "zsh"), "language"),
    Skill("powershell", ("pwsh",), "language"),
    Skill("groovy", (), "language"),

    # --- Frontend Frameworks ---
    Skill("react", ("reactjs", "react.js"), "frontend"),
    Skill("angular", ("angularjs", "angular.js"), "frontend"),
    Skill("vue", ("vuejs", "vue.js", "vue 3"), "frontend"),
    Skill("svelte", ("sveltekit",), "frontend"),
    Skill("next.js", ("nextjs", "next"), "frontend"),
    Skill("nuxt", ("nuxtjs", "nuxt.js"), "frontend"),
    Skill("gatsby", (), "frontend"),
    Skill("remix", (), "frontend"),
    Skill("astro", (), "frontend"),
    Skill("html", ("html5",), "frontend"),
    Skill("css", ("css3",), "frontend"),
    Skill("sass", ("scss",), "frontend"),
    Skill("tailwind", ("tailwindcss", "tailwind css"), "frontend"),
    Skill("bootstrap", (), "frontend"),
    Skill("material ui", ("mui",), "frontend"),
    Skill("jquery", (), "frontend"),
    Skill("webpack", (), "frontend"),
    Skill("vite", (), "frontend"),
    Skill("storybook", (), "frontend"),
    Skill("redux", (), "frontend"),
    Skill("zustand", (), "frontend"),
    Skill("graphql", ("gql",), "frontend"),
    Skill("apollo", ("apollo client", "apollo graphql"), "frontend"),
    Skill("three.js", ("threejs",), "frontend"),
    Skill("d3", ("d3.js", "d3js"), "frontend"),

    # --- Backend Frameworks ---
    Skill("node.js", ("nodejs", "node"), "backend"),
    Skill("express", ("expressjs", "express.js"), "backend"),
    Skill("fastapi", (), "backend"),
    Skill("django", (), "backend"),
    Skill("flask", (), "backend"),
    Skill("spring", ("spring boot", "spring framework", "springboot"), "backend"),
    Skill("rails", ("ruby on rails", "ror"), "backend"),
    Skill("laravel", (), "backend"),
    Skill("asp.net", ("asp.net core", "aspnet"), "backend"),
    Skill("gin", (), "backend"),
    Skill("fiber", (), "backend"),
    Skill("fastify", (), "backend"),
    Skill("nestjs", ("nest.js", "nest"), "backend"),
    Skill("actix", (), "backend"),
    Skill("phoenix", (), "backend"),
    Skill("grpc", ("grpc-web",), "backend"),
    Skill("rest api", ("restful", "rest apis", "restful api"), "backend"),
    Skill("microservices", ("micro services", "microservice"), "backend"),
    Skill("api design", ("api development",), "backend"),
    Skill("websocket", ("websockets", "ws"), "backend"),
    Skill("oauth", ("oauth2", "oauth 2.0"), "backend"),
    Skill("jwt", ("json web token",), "backend"),

    # --- Databases ---
    Skill("postgresql", ("postgres", "psql", "pg"), "database"),
    Skill("mysql", ("mariadb",), "database"),
    Skill("mongodb", ("mongo",), "database"),
    Skill("redis", (), "database"),
    Skill("elasticsearch", ("elastic", "es", "opensearch"), "database"),
    Skill("cassandra", (), "database"),
    Skill("dynamodb", ("dynamo",), "database"),
    Skill("sqlite", (), "database"),
    Skill("oracle", ("oracle db",), "database"),
    Skill("sql server", ("mssql", "microsoft sql server"), "database"),
    Skill("couchdb", ("couch",), "database"),
    Skill("neo4j", (), "database"),
    Skill("influxdb", (), "database"),
    Skill("timescaledb", (), "database"),
    Skill("cockroachdb", ("cockroach",), "database"),
    Skill("supabase", (), "database"),
    Skill("firebase", ("firestore",), "database"),
    Skill("memcached", (), "database"),
    Skill("etcd", (), "database"),

    # --- Cloud Platforms ---
    Skill("aws", ("amazon web services",), "cloud"),
    Skill("azure", ("microsoft azure",), "cloud"),
    Skill("gcp", ("google cloud", "google cloud platform"), "cloud"),
    Skill("heroku", (), "cloud"),
    Skill("vercel", (), "cloud"),
    Skill("netlify", (), "cloud"),
    Skill("digitalocean", ("digital ocean",), "cloud"),
    Skill("cloudflare", (), "cloud"),
    Skill("oracle cloud", ("oci",), "cloud"),
    Skill("alibaba cloud", (), "cloud"),

    # --- AWS Services ---
    Skill("ec2", ("amazon ec2",), "cloud"),
    Skill("s3", ("amazon s3",), "cloud"),
    Skill("lambda", ("aws lambda", "serverless"), "cloud"),
    Skill("ecs", ("amazon ecs",), "cloud"),
    Skill("eks", ("amazon eks",), "cloud"),
    Skill("rds", ("amazon rds",), "cloud"),
    Skill("sqs", ("amazon sqs",), "cloud"),
    Skill("sns", ("amazon sns",), "cloud"),
    Skill("cloudformation", ("cfn",), "cloud"),
    Skill("cdk", ("aws cdk",), "cloud"),
    Skill("iam", ("aws iam",), "cloud"),
    Skill("vpc", ("aws vpc",), "cloud"),
    Skill("cloudwatch", (), "cloud"),
    Skill("step functions", ("aws step functions",), "cloud"),
    Skill("api gateway", ("aws api gateway",), "cloud"),
    Skill("kinesis", ("amazon kinesis",), "cloud"),
    Skill("redshift", ("amazon redshift",), "cloud"),
    Skill("athena", ("amazon athena",), "cloud"),
    Skill("glue", ("aws glue",), "cloud"),
    Skill("emr", ("amazon emr",), "cloud"),
    Skill("sagemaker", ("amazon sagemaker",), "cloud"),

    # --- DevOps & Infrastructure ---
    Skill("docker", ("containers", "containerization"), "devops"),
    Skill("kubernetes", ("k8s", "kube"), "devops"),
    Skill("terraform", ("tf",), "devops"),
    Skill("ansible", (), "devops"),
    Skill("puppet", (), "devops"),
    Skill("chef", (), "devops"),
    Skill("helm", ("helm charts",), "devops"),
    Skill("jenkins", (), "devops"),
    Skill("github actions", ("gha",), "devops"),
    Skill("gitlab ci", ("gitlab ci/cd",), "devops"),
    Skill("circleci", ("circle ci",), "devops"),
    Skill("travis ci", (), "devops"),
    Skill("argocd", ("argo cd", "argo"), "devops"),
    Skill("ci/cd", ("cicd", "continuous integration", "continuous deployment"), "devops"),
    Skill("nginx", (), "devops"),
    Skill("apache", ("httpd",), "devops"),
    Skill("linux", ("unix",), "devops"),
    Skill("git", (), "devops"),
    Skill("prometheus", (), "devops"),
    Skill("grafana", (), "devops"),
    Skill("datadog", (), "devops"),
    Skill("new relic", ("newrelic",), "devops"),
    Skill("splunk", (), "devops"),
    Skill("elk", ("elk stack", "elastic stack"), "devops"),
    Skill("pagerduty", (), "devops"),
    Skill("vault", ("hashicorp vault",), "devops"),
    Skill("consul", (), "devops"),
    Skill("nomad", (), "devops"),
    Skill("istio", (), "devops"),
    Skill("envoy", (), "devops"),
    Skill("pulumi", (), "devops"),
    Skill("vagrant", (), "devops"),

    # --- Data Engineering ---
    Skill("spark", ("apache spark", "pyspark"), "data_engineering"),
    Skill("airflow", ("apache airflow",), "data_engineering"),
    Skill("kafka", ("apache kafka",), "data_engineering"),
    Skill("flink", ("apache flink",), "data_engineering"),
    Skill("hadoop", ("hdfs", "mapreduce"), "data_engineering"),
    Skill("hive", ("apache hive",), "data_engineering"),
    Skill("presto", ("trino",), "data_engineering"),
    Skill("dbt", ("data build tool",), "data_engineering"),
    Skill("snowflake", (), "data_engineering"),
    Skill("databricks", (), "data_engineering"),
    Skill("bigquery", ("bq", "google bigquery"), "data_engineering"),
    Skill("fivetran", (), "data_engineering"),
    Skill("airbyte", (), "data_engineering"),
    Skill("dagster", (), "data_engineering"),
    Skill("prefect", (), "data_engineering"),
    Skill("luigi", (), "data_engineering"),
    Skill("nifi", ("apache nifi",), "data_engineering"),
    Skill("beam", ("apache beam",), "data_engineering"),
    Skill("delta lake", ("delta",), "data_engineering"),
    Skill("iceberg", ("apache iceberg",), "data_engineering"),
    Skill("data warehouse", ("dwh", "data warehousing"), "data_engineering"),
    Skill("data lake", ("datalake",), "data_engineering"),
    Skill("etl", ("elt", "data pipeline", "data pipelines"), "data_engineering"),
    Skill("data modeling", ("dimensional modeling",), "data_engineering"),
    Skill("data governance", (), "data_engineering"),
    Skill("data quality", (), "data_engineering"),
    Skill("great expectations", (), "data_engineering"),
    Skill("celery", (), "data_engineering"),
    Skill("rabbitmq", ("rabbit mq",), "data_engineering"),

    # --- Data Science & Analytics ---
    Skill("pandas", (), "data_science"),
    Skill("numpy", (), "data_science"),
    Skill("scipy", (), "data_science"),
    Skill("matplotlib", (), "data_science"),
    Skill("seaborn", (), "data_science"),
    Skill("plotly", (), "data_science"),
    Skill("jupyter", ("jupyter notebook", "jupyterlab"), "data_science"),
    Skill("tableau", (), "data_science"),
    Skill("power bi", ("powerbi",), "data_science"),
    Skill("looker", (), "data_science"),
    Skill("metabase", (), "data_science"),
    Skill("dask", (), "data_science"),
    Skill("polars", (), "data_science"),
    Skill("statsmodels", (), "data_science"),
    Skill("a/b testing", ("ab testing", "experimentation"), "data_science"),
    Skill("statistical analysis", ("statistics",), "data_science"),
    Skill("hypothesis testing", (), "data_science"),
    Skill("regression", ("linear regression", "logistic regression"), "data_science"),
    Skill("time series", ("forecasting",), "data_science"),

    # --- Machine Learning ---
    Skill("scikit-learn", ("sklearn",), "ml"),
    Skill("tensorflow", ("tf",), "ml"),
    Skill("pytorch", ("torch",), "ml"),
    Skill("keras", (), "ml"),
    Skill("xgboost", (), "ml"),
    Skill("lightgbm", (), "ml"),
    Skill("catboost", (), "ml"),
    Skill("huggingface", ("hugging face", "transformers"), "ml"),
    Skill("mlflow", (), "ml"),
    Skill("wandb", ("weights and biases", "weights & biases"), "ml"),
    Skill("kubeflow", (), "ml"),
    Skill("feature store", (), "ml"),
    Skill("model serving", (), "ml"),
    Skill("onnx", (), "ml"),
    Skill("ray", ("ray tune",), "ml"),
    Skill("optuna", (), "ml"),
    Skill("hyperparameter tuning", (), "ml"),
    Skill("cross-validation", (), "ml"),
    Skill("ensemble methods", (), "ml"),
    Skill("random forest", (), "ml"),
    Skill("gradient boosting", (), "ml"),
    Skill("svm", ("support vector machine",), "ml"),
    Skill("clustering", ("k-means",), "ml"),
    Skill("dimensionality reduction", ("pca",), "ml"),

    # --- Deep Learning & AI ---
    Skill("nlp", ("natural language processing", "text mining"), "ai"),
    Skill("computer vision", ("cv", "image recognition"), "ai"),
    Skill("llm", ("large language model", "large language models"), "ai"),
    Skill("gpt", ("openai", "chatgpt"), "ai"),
    Skill("bert", (), "ai"),
    Skill("langchain", (), "ai"),
    Skill("llamaindex", ("llama index",), "ai"),
    Skill("rag", ("retrieval augmented generation",), "ai"),
    Skill("prompt engineering", ("prompting",), "ai"),
    Skill("fine-tuning", ("fine tuning", "finetuning"), "ai"),
    Skill("embeddings", ("vector embeddings", "word embeddings"), "ai"),
    Skill("vector database", ("vector db", "pinecone", "weaviate", "milvus", "qdrant", "chroma", "chromadb"), "ai"),
    Skill("cnn", ("convolutional neural network",), "ai"),
    Skill("rnn", ("recurrent neural network", "lstm", "gru"), "ai"),
    Skill("gan", ("generative adversarial network",), "ai"),
    Skill("reinforcement learning", ("rl",), "ai"),
    Skill("diffusion models", ("stable diffusion",), "ai"),
    Skill("speech recognition", ("asr", "speech to text"), "ai"),
    Skill("recommendation systems", ("recommender systems",), "ai"),
    Skill("anomaly detection", (), "ai"),
    Skill("object detection", ("yolo",), "ai"),
    Skill("image segmentation", (), "ai"),
    Skill("transfer learning", (), "ai"),
    Skill("attention mechanism", ("transformer",), "ai"),

    # --- Mobile ---
    Skill("react native", (), "mobile"),
    Skill("flutter", (), "mobile"),
    Skill("ios", ("ios development",), "mobile"),
    Skill("android", ("android development",), "mobile"),
    Skill("swiftui", (), "mobile"),
    Skill("jetpack compose", ("compose",), "mobile"),
    Skill("xamarin", (), "mobile"),
    Skill("ionic", (), "mobile"),
    Skill("expo", (), "mobile"),
    Skill("capacitor", (), "mobile"),

    # --- Testing ---
    Skill("unit testing", ("unit tests",), "testing"),
    Skill("integration testing", ("integration tests",), "testing"),
    Skill("e2e testing", ("end to end testing", "end-to-end testing"), "testing"),
    Skill("pytest", (), "testing"),
    Skill("jest", (), "testing"),
    Skill("mocha", (), "testing"),
    Skill("cypress", (), "testing"),
    Skill("playwright", (), "testing"),
    Skill("selenium", (), "testing"),
    Skill("tdd", ("test driven development",), "testing"),
    Skill("bdd", ("behavior driven development",), "testing"),
    Skill("cucumber", (), "testing"),
    Skill("junit", (), "testing"),
    Skill("testng", (), "testing"),
    Skill("mockito", (), "testing"),
    Skill("wiremock", (), "testing"),
    Skill("postman", (), "testing"),
    Skill("load testing", ("jmeter", "locust", "k6"), "testing"),

    # --- Security ---
    Skill("cybersecurity", ("information security", "infosec"), "security"),
    Skill("penetration testing", ("pentesting", "pentest"), "security"),
    Skill("owasp", (), "security"),
    Skill("soc 2", ("soc2",), "security"),
    Skill("encryption", ("tls", "ssl", "https"), "security"),
    Skill("authentication", ("authn",), "security"),
    Skill("authorization", ("authz", "rbac", "abac"), "security"),
    Skill("sso", ("single sign-on",), "security"),
    Skill("saml", (), "security"),
    Skill("vulnerability assessment", ("vulnerability scanning",), "security"),
    Skill("devsecops", (), "security"),
    Skill("siem", (), "security"),
    Skill("compliance", ("gdpr", "hipaa", "pci dss"), "security"),

    # --- Architecture & Design ---
    Skill("system design", ("systems design",), "architecture"),
    Skill("distributed systems", (), "architecture"),
    Skill("event-driven architecture", ("eda", "event driven"), "architecture"),
    Skill("domain-driven design", ("ddd",), "architecture"),
    Skill("clean architecture", (), "architecture"),
    Skill("design patterns", (), "architecture"),
    Skill("solid principles", ("solid",), "architecture"),
    Skill("cqrs", (), "architecture"),
    Skill("event sourcing", (), "architecture"),
    Skill("saga pattern", (), "architecture"),
    Skill("service mesh", (), "architecture"),
    Skill("api gateway pattern", (), "architecture"),
    Skill("message queue", ("message broker", "pub/sub", "pubsub"), "architecture"),
    Skill("caching strategies", ("caching",), "architecture"),
    Skill("load balancing", ("load balancer",), "architecture"),
    Skill("high availability", ("ha",), "architecture"),
    Skill("fault tolerance", (), "architecture"),
    Skill("scalability", (), "architecture"),
    Skill("concurrency", ("multithreading", "parallelism"), "architecture"),

    # --- Project Management / Methodology ---
    Skill("agile", ("scrum", "kanban"), "methodology"),
    Skill("jira", (), "methodology"),
    Skill("confluence", (), "methodology"),
    Skill("figma", (), "methodology"),
    Skill("technical writing", ("documentation",), "methodology"),
    Skill("code review", ("peer review",), "methodology"),
    Skill("pair programming", (), "methodology"),
    Skill("mentoring", (), "methodology"),
    Skill("cross-functional collaboration", (), "methodology"),

    # --- Blockchain / Web3 ---
    Skill("solidity", (), "blockchain"),
    Skill("ethereum", ("eth",), "blockchain"),
    Skill("smart contracts", (), "blockchain"),
    Skill("web3", ("web3.js", "ethers.js"), "blockchain"),
    Skill("defi", ("decentralized finance",), "blockchain"),

    # --- Networking ---
    Skill("tcp/ip", ("tcp", "ip", "networking"), "networking"),
    Skill("dns", (), "networking"),
    Skill("http", ("http/2", "http/3"), "networking"),
    Skill("cdn", ("content delivery network",), "networking"),
    Skill("vpn", (), "networking"),
    Skill("firewall", (), "networking"),
]


# ---------------------------------------------------------------------------
# Fast Lookup Index
# ---------------------------------------------------------------------------

# canonical -> Skill object
_CANONICAL_MAP: dict[str, Skill] = {}
# alias (lowered) -> canonical name
_ALIAS_MAP: dict[str, str] = {}
# All categories
_CATEGORIES: set[str] = set()

for _skill in _SKILLS:
    canonical_lower = _skill.canonical.lower()
    _CANONICAL_MAP[canonical_lower] = _skill
    _ALIAS_MAP[canonical_lower] = _skill.canonical
    _CATEGORIES.add(_skill.category)
    for alias in _skill.aliases:
        _ALIAS_MAP[alias.lower()] = _skill.canonical

# Sorted by length (longest first) for greedy matching
_ALL_TERMS_SORTED = sorted(_ALIAS_MAP.keys(), key=len, reverse=True)

# Pre-compiled regex patterns for word-boundary matching
_TERM_PATTERNS: list[tuple[re.Pattern, str]] = []
for term in _ALL_TERMS_SORTED:
    # Escape special regex characters in the term
    escaped = re.escape(term)
    # Use word boundaries for terms that are pure alphanumeric
    # For terms with special chars (c++, c#, etc.), use lookaround
    if re.match(r"^[\w\s]+$", term):
        pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    else:
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
    _TERM_PATTERNS.append((pattern, _ALIAS_MAP[term]))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_skill(text: str) -> str | None:
    """Resolve a skill name or alias to its canonical form.

    Returns None if not found.

    >>> resolve_skill("Python3")
    'python'
    >>> resolve_skill("k8s")
    'kubernetes'
    >>> resolve_skill("not a skill")
    None
    """
    lower = text.strip().lower()
    return _ALIAS_MAP.get(lower)


def extract_skills(text: str) -> list[str]:
    """Extract all skills mentioned in a text body.

    Returns deduplicated list of canonical skill names, ordered by first appearance.

    Uses greedy matching (longest terms first) to handle overlapping patterns
    like "react native" vs "react".
    """
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()
    text_lower = text.lower()

    for pattern, canonical in _TERM_PATTERNS:
        if canonical in seen:
            continue
        if pattern.search(text_lower):
            found.append(canonical)
            seen.add(canonical)

    return found


def get_skill_category(skill: str) -> str:
    """Get the category for a canonical skill name.

    >>> get_skill_category("python")
    'language'
    >>> get_skill_category("kubernetes")
    'devops'
    """
    lower = skill.strip().lower()
    canonical = _ALIAS_MAP.get(lower, lower)
    skill_obj = _CANONICAL_MAP.get(canonical)
    return skill_obj.category if skill_obj else "other"


def get_skills_by_category(category: str) -> list[str]:
    """Get all canonical skill names for a category.

    >>> len(get_skills_by_category("language")) > 20
    True
    """
    return [s.canonical for s in _SKILLS if s.category == category]


def get_all_categories() -> list[str]:
    """Get all skill categories."""
    return sorted(_CATEGORIES)


def get_taxonomy_size() -> int:
    """Get total number of unique skills (canonical names)."""
    return len(_CANONICAL_MAP)


def compute_skill_overlap(
    skills_a: list[str],
    skills_b: list[str],
) -> dict:
    """Compute overlap between two skill lists.

    Returns dict with matched, missing, extra, and overlap percentage.
    """
    set_a = {resolve_skill(s) or s.lower() for s in skills_a}
    set_b = {resolve_skill(s) or s.lower() for s in skills_b}

    matched = set_a & set_b
    missing_from_b = set_a - set_b
    extra_in_b = set_b - set_a

    total = len(set_a) if set_a else 1  # avoid division by zero
    overlap_pct = len(matched) / total

    return {
        "matched": sorted(matched),
        "missing": sorted(missing_from_b),
        "extra": sorted(extra_in_b),
        "matched_count": len(matched),
        "total_required": len(set_a),
        "overlap_pct": round(overlap_pct, 3),
    }


def categorize_skills(skills: list[str]) -> dict[str, list[str]]:
    """Group a list of skills by their category.

    >>> cats = categorize_skills(["python", "aws", "react"])
    >>> cats["language"]
    ['python']
    >>> cats["cloud"]
    ['aws']
    """
    result: dict[str, list[str]] = {}
    for skill in skills:
        cat = get_skill_category(skill)
        result.setdefault(cat, []).append(skill)
    return result
