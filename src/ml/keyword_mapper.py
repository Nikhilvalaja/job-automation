"""Keyword mapper — safe keyword swaps and skill transferability matrix.

Rules:
- Only swap keywords that are TRUTHFUL transformations (same meaning, different phrasing)
- NEVER substitute skills/platforms directly (Python ≠ Java, AWS ≠ GCP)
- Transferability is noted at the CATEGORY level only (for scoring)
- Every swap must be approved by the validation engine
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KeywordSwap:
    """A safe keyword substitution."""
    source: str         # Original keyword in resume
    target: str         # Replacement aligned with JD
    category: str       # "action_verb", "technical", "abstraction"
    bidirectional: bool = True  # Can swap in either direction


# --- Safe Action Verb Swaps ---
# These are truly interchangeable in resume context
ACTION_VERB_SWAPS = [
    KeywordSwap("built", "developed", "action_verb"),
    KeywordSwap("built", "engineered", "action_verb"),
    KeywordSwap("created", "designed", "action_verb"),
    KeywordSwap("led", "spearheaded", "action_verb"),
    KeywordSwap("managed", "oversaw", "action_verb"),
    KeywordSwap("improved", "enhanced", "action_verb"),
    KeywordSwap("improved", "optimized", "action_verb"),
    KeywordSwap("reduced", "decreased", "action_verb"),
    KeywordSwap("reduced", "minimized", "action_verb"),
    KeywordSwap("increased", "grew", "action_verb"),
    KeywordSwap("increased", "boosted", "action_verb"),
    KeywordSwap("implemented", "deployed", "action_verb"),
    KeywordSwap("implemented", "delivered", "action_verb"),
    KeywordSwap("automated", "streamlined", "action_verb"),
    KeywordSwap("migrated", "transitioned", "action_verb"),
    KeywordSwap("refactored", "restructured", "action_verb"),
    KeywordSwap("maintained", "supported", "action_verb"),
    KeywordSwap("scaled", "expanded", "action_verb"),
    KeywordSwap("architected", "designed", "action_verb"),
    KeywordSwap("integrated", "incorporated", "action_verb"),
    KeywordSwap("mentored", "coached", "action_verb"),
    KeywordSwap("analyzed", "evaluated", "action_verb"),
    KeywordSwap("collaborated", "partnered", "action_verb"),
]

# --- Safe Technical Abstraction Swaps ---
# These describe the SAME concept at different abstraction levels
TECHNICAL_SWAPS = [
    KeywordSwap("API", "service endpoint", "technical"),
    KeywordSwap("REST API", "web service", "technical"),
    KeywordSwap("microservices", "distributed services", "technical"),
    KeywordSwap("monolith", "legacy system", "technical"),
    KeywordSwap("data pipeline", "ETL pipeline", "technical"),
    KeywordSwap("data pipeline", "data workflow", "technical"),
    KeywordSwap("CI/CD", "continuous integration", "technical"),
    KeywordSwap("CI/CD pipeline", "deployment pipeline", "technical"),
    KeywordSwap("caching layer", "cache infrastructure", "technical"),
    KeywordSwap("database", "data store", "technical"),
    KeywordSwap("message queue", "event bus", "technical"),
    KeywordSwap("containerized", "Docker-based", "technical", bidirectional=False),
    KeywordSwap("orchestrated", "managed containers", "technical"),
    KeywordSwap("real-time", "low-latency", "technical"),
    KeywordSwap("batch processing", "offline processing", "technical"),
    KeywordSwap("machine learning model", "ML model", "technical"),
    KeywordSwap("feature engineering", "feature extraction", "technical"),
]


# --- Skill Transferability Matrix ---
# Tracks which skills are CONCEPTUALLY equivalent across ecosystems
# Used for scoring (category-level match), NOT for substitution
# NEVER swap one skill for another on a resume — only note transferability

@dataclass
class SkillFamily:
    """Skills that serve the same purpose in different ecosystems."""
    category: str           # "programming_language", "database", etc.
    subcategory: str        # More specific grouping
    skills: list[str]       # List of equivalent skills
    transfer_score: float = 0.7  # How transferable (0.0-1.0), higher = more similar


# -- Programming Languages --
LANGUAGE_FAMILIES = [
    SkillFamily("language", "general_purpose",
                ["Python", "Ruby", "Perl"], 0.75),
    SkillFamily("language", "systems",
                ["Go", "Rust", "C++", "C"], 0.6),
    SkillFamily("language", "jvm",
                ["Java", "Kotlin", "Scala", "Groovy"], 0.8),
    SkillFamily("language", "dotnet",
                ["C#", ".NET", "F#", "VB.NET"], 0.8),
    SkillFamily("language", "web_scripting",
                ["JavaScript", "TypeScript"], 0.9),
    SkillFamily("language", "functional",
                ["Haskell", "Erlang", "Elixir", "Clojure", "OCaml"], 0.6),
    SkillFamily("language", "data_science",
                ["Python", "R", "Julia", "MATLAB"], 0.7),
    SkillFamily("language", "mobile_native",
                ["Swift", "Objective-C"], 0.75),
    SkillFamily("language", "shell",
                ["Bash", "Shell", "Zsh", "PowerShell"], 0.85),
]

# -- Databases --
DATABASE_FAMILIES = [
    SkillFamily("database", "relational",
                ["PostgreSQL", "MySQL", "MariaDB", "SQL Server", "Oracle DB", "SQLite"], 0.8),
    SkillFamily("database", "document_nosql",
                ["MongoDB", "CouchDB", "Couchbase", "RavenDB"], 0.75),
    SkillFamily("database", "wide_column",
                ["Cassandra", "HBase", "ScyllaDB", "DynamoDB"], 0.7),
    SkillFamily("database", "key_value",
                ["Redis", "Memcached", "etcd", "Aerospike"], 0.8),
    SkillFamily("database", "graph",
                ["Neo4j", "ArangoDB", "JanusGraph", "Amazon Neptune"], 0.7),
    SkillFamily("database", "time_series",
                ["InfluxDB", "TimescaleDB", "Prometheus", "QuestDB"], 0.75),
    SkillFamily("database", "search_engine",
                ["Elasticsearch", "OpenSearch", "Solr", "Meilisearch", "Algolia"], 0.8),
    SkillFamily("database", "vector_db",
                ["Pinecone", "Weaviate", "Milvus", "Qdrant", "ChromaDB", "pgvector"], 0.8),
    SkillFamily("database", "query_language",
                ["SQL", "T-SQL", "PL/SQL", "PL/pgSQL"], 0.9),
]

# -- Web Frameworks --
FRAMEWORK_FAMILIES = [
    SkillFamily("framework", "python_web",
                ["Django", "Flask", "FastAPI", "Tornado", "Pyramid", "Starlette"], 0.8),
    SkillFamily("framework", "java_web",
                ["Spring Boot", "Spring", "Micronaut", "Quarkus", "Jakarta EE"], 0.8),
    SkillFamily("framework", "node_web",
                ["Express", "Fastify", "NestJS", "Koa", "Hapi"], 0.8),
    SkillFamily("framework", "frontend",
                ["React", "Vue", "Angular", "Svelte", "SolidJS", "Preact"], 0.7),
    SkillFamily("framework", "css",
                ["Tailwind CSS", "Bootstrap", "Material UI", "Chakra UI", "Ant Design"], 0.85),
    SkillFamily("framework", "ruby_web",
                ["Rails", "Ruby on Rails", "Sinatra", "Hanami"], 0.8),
    SkillFamily("framework", "dotnet_web",
                ["ASP.NET", "ASP.NET Core", "Blazor"], 0.85),
    SkillFamily("framework", "go_web",
                ["Gin", "Echo", "Fiber", "Chi"], 0.85),
    SkillFamily("framework", "mobile_cross",
                ["React Native", "Flutter", "Ionic", "Xamarin", "MAUI"], 0.7),
]

# -- Data & ML --
DATA_ML_FAMILIES = [
    SkillFamily("data", "batch_processing",
                ["Spark", "Apache Spark", "PySpark", "Flink", "MapReduce", "Beam"], 0.75),
    SkillFamily("data", "workflow_orchestrator",
                ["Airflow", "Apache Airflow", "Prefect", "Dagster", "Luigi", "Argo Workflows"], 0.8),
    SkillFamily("data", "streaming",
                ["Kafka", "Apache Kafka", "Pulsar", "Kinesis", "Flink", "Storm"], 0.7),
    SkillFamily("data", "data_warehouse",
                ["Snowflake", "BigQuery", "Redshift", "Databricks", "Synapse", "ClickHouse"], 0.75),
    SkillFamily("data", "etl_tool",
                ["dbt", "Fivetran", "Airbyte", "Stitch", "Matillion", "Talend"], 0.75),
    SkillFamily("ml", "ml_framework",
                ["TensorFlow", "PyTorch", "JAX", "Keras", "MXNet"], 0.75),
    SkillFamily("ml", "ml_ops",
                ["MLflow", "Kubeflow", "SageMaker", "Vertex AI", "Weights & Biases", "Neptune.ai"], 0.7),
    SkillFamily("ml", "nlp",
                ["spaCy", "NLTK", "Hugging Face", "Transformers", "Gensim"], 0.75),
    SkillFamily("ml", "data_analysis",
                ["Pandas", "NumPy", "Polars", "Dask", "Vaex"], 0.85),
    SkillFamily("ml", "visualization",
                ["Matplotlib", "Plotly", "Seaborn", "D3.js", "Grafana", "Tableau", "Power BI"], 0.7),
]

# -- DevOps & Infrastructure --
DEVOPS_FAMILIES = [
    SkillFamily("devops", "container_runtime",
                ["Docker", "Podman", "containerd", "CRI-O"], 0.85),
    SkillFamily("devops", "container_orchestration",
                ["Kubernetes", "K8s", "Docker Swarm", "Nomad", "ECS", "EKS", "GKE", "AKS"], 0.75),
    SkillFamily("devops", "ci_cd",
                ["GitHub Actions", "GitLab CI", "Jenkins", "CircleCI", "Travis CI",
                 "Azure DevOps", "TeamCity", "Buildkite", "ArgoCD"], 0.8),
    SkillFamily("devops", "iac",
                ["Terraform", "Pulumi", "CloudFormation", "Ansible", "Chef", "Puppet", "CDK"], 0.7),
    SkillFamily("devops", "monitoring",
                ["Prometheus", "Grafana", "Datadog", "New Relic", "Splunk",
                 "CloudWatch", "PagerDuty", "Dynatrace"], 0.75),
    SkillFamily("devops", "logging",
                ["ELK Stack", "Elasticsearch", "Logstash", "Fluentd", "Splunk",
                 "Loki", "CloudWatch Logs"], 0.8),
    SkillFamily("devops", "service_mesh",
                ["Istio", "Linkerd", "Envoy", "Consul Connect"], 0.75),
    SkillFamily("devops", "secrets_management",
                ["Vault", "HashiCorp Vault", "AWS Secrets Manager",
                 "Azure Key Vault", "GCP Secret Manager"], 0.8),
]

# -- Message Brokers & Queues --
MESSAGING_FAMILIES = [
    SkillFamily("messaging", "message_broker",
                ["Kafka", "RabbitMQ", "ActiveMQ", "Pulsar", "NATS"], 0.75),
    SkillFamily("messaging", "cloud_queue",
                ["SQS", "Pub/Sub", "Azure Service Bus", "Azure Queue Storage"], 0.8),
    SkillFamily("messaging", "event_streaming",
                ["Kafka", "Kinesis", "EventBridge", "Pub/Sub", "Event Hubs"], 0.7),
]

# -- API & Protocols --
API_FAMILIES = [
    SkillFamily("api", "api_style",
                ["REST", "RESTful", "GraphQL", "gRPC", "SOAP"], 0.6),
    SkillFamily("api", "api_gateway",
                ["Kong", "Apigee", "AWS API Gateway", "Nginx", "Traefik", "HAProxy"], 0.75),
    SkillFamily("api", "api_docs",
                ["Swagger", "OpenAPI", "Postman", "Insomnia"], 0.85),
]

# -- Testing --
TESTING_FAMILIES = [
    SkillFamily("testing", "python_testing",
                ["pytest", "unittest", "nose2", "tox"], 0.9),
    SkillFamily("testing", "java_testing",
                ["JUnit", "TestNG", "Mockito", "Spock"], 0.85),
    SkillFamily("testing", "js_testing",
                ["Jest", "Mocha", "Vitest", "Jasmine", "Cypress", "Playwright"], 0.8),
    SkillFamily("testing", "load_testing",
                ["Locust", "k6", "JMeter", "Gatling", "Artillery"], 0.8),
    SkillFamily("testing", "e2e_testing",
                ["Selenium", "Playwright", "Cypress", "Puppeteer", "TestCafe"], 0.8),
]

# -- Version Control & Collaboration --
VCS_FAMILIES = [
    SkillFamily("vcs", "version_control",
                ["Git", "SVN", "Mercurial", "Perforce"], 0.7),
    SkillFamily("vcs", "git_platform",
                ["GitHub", "GitLab", "Bitbucket", "Azure Repos"], 0.9),
    SkillFamily("vcs", "project_management",
                ["Jira", "Linear", "Asana", "Trello", "Azure Boards", "Shortcut"], 0.85),
]

# -- Cloud Platforms (provider-level) --
CLOUD_FAMILIES = [
    SkillFamily("cloud", "cloud_provider",
                ["AWS", "GCP", "Google Cloud", "Azure", "Microsoft Azure"], 0.65),
]

# Aggregate all skill families into one list for easy lookup
ALL_SKILL_FAMILIES: list[SkillFamily] = (
    LANGUAGE_FAMILIES + DATABASE_FAMILIES + FRAMEWORK_FAMILIES
    + DATA_ML_FAMILIES + DEVOPS_FAMILIES + MESSAGING_FAMILIES
    + API_FAMILIES + TESTING_FAMILIES + VCS_FAMILIES + CLOUD_FAMILIES
)


# --- Cloud Service Transferability (provider-specific detail) ---
# More granular than SkillFamily — maps specific cloud services by provider
# Used for richer context when the candidate uses one cloud and JD asks for another
@dataclass
class CloudEquivalent:
    """Cloud services that serve the same purpose."""
    category: str       # "object_storage", "compute", "serverless", etc.
    services: dict      # {"aws": "S3", "gcp": "GCS", "azure": "Blob Storage"}


CLOUD_TRANSFERABILITY = [
    CloudEquivalent("object_storage", {"aws": "S3", "gcp": "GCS", "azure": "Blob Storage"}),
    CloudEquivalent("compute", {"aws": "EC2", "gcp": "Compute Engine", "azure": "Virtual Machines"}),
    CloudEquivalent("serverless", {"aws": "Lambda", "gcp": "Cloud Functions", "azure": "Azure Functions"}),
    CloudEquivalent("container_orchestration", {"aws": "ECS/EKS", "gcp": "GKE", "azure": "AKS"}),
    CloudEquivalent("nosql_db", {"aws": "DynamoDB", "gcp": "Firestore", "azure": "CosmosDB"}),
    CloudEquivalent("sql_db", {"aws": "RDS", "gcp": "Cloud SQL", "azure": "Azure SQL"}),
    CloudEquivalent("message_queue", {"aws": "SQS", "gcp": "Pub/Sub", "azure": "Service Bus"}),
    CloudEquivalent("streaming", {"aws": "Kinesis", "gcp": "Dataflow", "azure": "Event Hubs"}),
    CloudEquivalent("data_warehouse", {"aws": "Redshift", "gcp": "BigQuery", "azure": "Synapse"}),
    CloudEquivalent("ml_platform", {"aws": "SageMaker", "gcp": "Vertex AI", "azure": "Azure ML"}),
    CloudEquivalent("cdn", {"aws": "CloudFront", "gcp": "Cloud CDN", "azure": "Azure CDN"}),
    CloudEquivalent("iam", {"aws": "IAM", "gcp": "Cloud IAM", "azure": "Azure AD"}),
    CloudEquivalent("monitoring", {"aws": "CloudWatch", "gcp": "Cloud Monitoring", "azure": "Azure Monitor"}),
    CloudEquivalent("secrets", {"aws": "Secrets Manager", "gcp": "Secret Manager", "azure": "Key Vault"}),
]


def get_safe_swaps(source_word: str) -> list[KeywordSwap]:
    """Get all safe swaps for a given word."""
    source_lower = source_word.lower()
    results = []
    for swap in ACTION_VERB_SWAPS + TECHNICAL_SWAPS:
        if swap.source.lower() == source_lower:
            results.append(swap)
        elif swap.bidirectional and swap.target.lower() == source_lower:
            results.append(KeywordSwap(
                source=swap.target, target=swap.source,
                category=swap.category, bidirectional=True,
            ))
    return results


def find_swap_for_jd(resume_word: str, jd_words: list[str]) -> KeywordSwap | None:
    """Find a safe swap from resume_word to a word used in the JD.

    Returns None if no safe swap exists — meaning the original word stays.
    """
    jd_lower = {w.lower() for w in jd_words}
    for swap in get_safe_swaps(resume_word):
        if swap.target.lower() in jd_lower:
            return swap
    return None


def get_cloud_category(service_name: str) -> str | None:
    """Get the cloud category for a specific service (e.g., 'S3' -> 'object_storage')."""
    service_lower = service_name.lower()
    for equiv in CLOUD_TRANSFERABILITY:
        for provider, name in equiv.services.items():
            if name.lower() == service_lower or service_lower in name.lower():
                return equiv.category
    return None


def check_cloud_transferability(resume_service: str, jd_service: str) -> dict:
    """Check if two cloud services are transferable (same category).

    Returns a dict with:
    - transferable: bool
    - category: str (if transferable)
    - resume_provider: str
    - jd_provider: str
    - note: str (explanation for the user)

    IMPORTANT: This does NOT mean we should substitute one for the other.
    It means the candidate has TRANSFERABLE experience in the same domain.
    """
    resume_cat = None
    resume_provider = None
    jd_cat = None
    jd_provider = None

    for equiv in CLOUD_TRANSFERABILITY:
        for provider, name in equiv.services.items():
            if name.lower() in resume_service.lower() or resume_service.lower() in name.lower():
                resume_cat = equiv.category
                resume_provider = provider
            if name.lower() in jd_service.lower() or jd_service.lower() in name.lower():
                jd_cat = equiv.category
                jd_provider = provider

    if resume_cat and jd_cat and resume_cat == jd_cat:
        return {
            "transferable": True,
            "category": resume_cat,
            "resume_provider": resume_provider,
            "jd_provider": jd_provider,
            "note": f"Your {resume_service} experience transfers to {jd_service} ({resume_cat})",
        }

    return {"transferable": False, "category": None, "note": "Not transferable"}


def suggest_keyword_alignment(
    resume_bullets: list[str],
    jd_text: str,
) -> list[dict]:
    """Analyze resume bullets and suggest safe keyword alignments with JD.

    Returns a list of suggestions, each with:
    - bullet_index: int
    - original_word: str
    - suggested_word: str
    - category: str
    - reason: str
    """
    jd_words = jd_text.lower().split()
    suggestions = []

    for i, bullet in enumerate(resume_bullets):
        words = bullet.split()
        for word in words:
            swap = find_swap_for_jd(word, jd_words)
            if swap:
                suggestions.append({
                    "bullet_index": i,
                    "original_word": word,
                    "suggested_word": swap.target,
                    "category": swap.category,
                    "reason": f"JD uses '{swap.target}' — safe synonym swap",
                })

    return suggestions


# ---- General Skill Transferability Functions ----

def _skill_matches(skill_a: str, skill_b: str) -> bool:
    """Check if two skill strings refer to the same skill.

    Uses exact match first, then substring match only if the shorter
    string is at least 4 chars (prevents 'R', 'C', 'Go' false positives).
    """
    a, b = skill_a.lower(), skill_b.lower()
    if a == b:
        return True
    # Substring match only for multi-word or longer skill names
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 4 and shorter in longer:
        return True
    return False


def find_skill_family(skill_name: str) -> list[SkillFamily]:
    """Find all skill families that contain a given skill.

    A skill can appear in multiple families (e.g., 'Kafka' is in both
    message_broker and event_streaming).
    """
    results = []
    for family in ALL_SKILL_FAMILIES:
        for s in family.skills:
            if _skill_matches(s, skill_name):
                results.append(family)
                break
    return results


def check_skill_transferability(resume_skill: str, jd_skill: str) -> dict:
    """Check if two skills are transferable (same family/category).

    Works for ALL skill types: languages, databases, frameworks, tools, cloud, etc.

    Returns a dict with:
    - transferable: bool
    - category: str (if transferable)
    - subcategory: str (if transferable)
    - transfer_score: float (0.0-1.0)
    - resume_skill: str
    - jd_skill: str
    - family_skills: list[str] (other skills in the family)
    - note: str (explanation)

    IMPORTANT: This does NOT mean we should substitute one for the other.
    It means the candidate has TRANSFERABLE experience in the same domain.
    """
    resume_families = find_skill_family(resume_skill)
    jd_families = find_skill_family(jd_skill)

    # Find overlapping families
    for rf in resume_families:
        for jf in jd_families:
            if rf is jf:  # Same family object
                return {
                    "transferable": True,
                    "category": rf.category,
                    "subcategory": rf.subcategory,
                    "transfer_score": rf.transfer_score,
                    "resume_skill": resume_skill,
                    "jd_skill": jd_skill,
                    "family_skills": rf.skills,
                    "note": (
                        f"Your {resume_skill} experience transfers to {jd_skill} "
                        f"({rf.subcategory}, score: {rf.transfer_score:.0%})"
                    ),
                }

    # Also check cloud service transferability for richer context
    cloud_result = check_cloud_transferability(resume_skill, jd_skill)
    if cloud_result["transferable"]:
        return {
            "transferable": True,
            "category": "cloud_service",
            "subcategory": cloud_result["category"],
            "transfer_score": 0.65,
            "resume_skill": resume_skill,
            "jd_skill": jd_skill,
            "family_skills": [],
            "note": cloud_result["note"],
        }

    return {
        "transferable": False,
        "category": None,
        "subcategory": None,
        "transfer_score": 0.0,
        "resume_skill": resume_skill,
        "jd_skill": jd_skill,
        "family_skills": [],
        "note": "Not transferable — different skill domains",
    }


def analyze_skill_gaps(
    resume_skills: list[str],
    jd_skills: list[str],
) -> dict:
    """Analyze skill gaps between resume and JD, noting transferable skills.

    Returns:
    - exact_matches: skills that match exactly
    - transferable: skills where resume has equivalent experience
    - gaps: skills in JD with no match or transfer
    - transfer_details: full transferability info per transferable skill
    """
    resume_lower = {s.lower(): s for s in resume_skills}
    exact_matches = []
    transferable = []
    transfer_details = []
    gaps = []

    for jd_skill in jd_skills:
        jd_lower = jd_skill.lower()

        # Check exact match first
        if jd_lower in resume_lower:
            exact_matches.append(jd_skill)
            continue

        # Check transferability against all resume skills
        best_transfer = None
        for rs_lower, rs_original in resume_lower.items():
            result = check_skill_transferability(rs_original, jd_skill)
            if result["transferable"]:
                if best_transfer is None or result["transfer_score"] > best_transfer["transfer_score"]:
                    best_transfer = result

        if best_transfer:
            transferable.append(jd_skill)
            transfer_details.append(best_transfer)
        else:
            gaps.append(jd_skill)

    return {
        "exact_matches": exact_matches,
        "transferable": transferable,
        "transfer_details": transfer_details,
        "gaps": gaps,
        "match_rate": len(exact_matches) / max(len(jd_skills), 1),
        "coverage_rate": (len(exact_matches) + len(transferable)) / max(len(jd_skills), 1),
    }
