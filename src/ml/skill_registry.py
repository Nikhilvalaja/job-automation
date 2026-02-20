"""Skill entity registry with computed transferability scoring.

Each skill has rich metadata: category, subcategory, platform, abstraction level.
Transfer scoring is COMPUTED between individual skills — not static family-level.

Rules:
- Deterministic, explainable, context-aware, platform-aware
- LLM is NOT used for transfer logic
- NEVER auto-substitute skills on a resume
- Transfer scores inform match_score, not rewriting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class AbstractionLevel(IntEnum):
    """How close to bare metal vs managed service."""
    INFRASTRUCTURE = 1   # Raw compute, networking, OS-level
    SERVICE = 2          # Self-managed services (install, configure, run)
    MANAGED = 3          # Fully managed cloud services (SaaS-level)
    CONCEPT = 4          # Abstract concepts (REST, CI/CD, microservices)


@dataclass(frozen=True)
class Skill:
    """Rich skill entity with metadata for transfer computation."""
    name: str
    category: str               # "language", "database", "cloud", "devops", etc.
    subcategory: str            # "relational", "object_storage", "frontend", etc.
    platform: str = "neutral"   # "aws", "gcp", "azure", "neutral"
    abstraction_level: int = 2  # 1=infra, 2=service, 3=managed, 4=concept
    aliases: tuple[str, ...] = ()  # Alternative names for matching


# ---------------------------------------------------------------------------
# Skill Registry — comprehensive catalog
# ---------------------------------------------------------------------------

_SKILLS: list[Skill] = []


def _reg(*skills: Skill) -> None:
    """Register skills into the global registry."""
    _SKILLS.extend(skills)


# ===== Programming Languages =====
_reg(
    Skill("Python", "language", "general_purpose", abstraction_level=2),
    Skill("Ruby", "language", "general_purpose", abstraction_level=2),
    Skill("Perl", "language", "general_purpose", abstraction_level=2),
    Skill("Java", "language", "jvm", abstraction_level=2),
    Skill("Kotlin", "language", "jvm", abstraction_level=2),
    Skill("Scala", "language", "jvm", abstraction_level=2),
    Skill("Groovy", "language", "jvm", abstraction_level=2),
    Skill("C#", "language", "dotnet", abstraction_level=2),
    Skill(".NET", "language", "dotnet", abstraction_level=2, aliases=("dotnet",)),
    Skill("F#", "language", "dotnet", abstraction_level=2),
    Skill("JavaScript", "language", "web", abstraction_level=2, aliases=("JS",)),
    Skill("TypeScript", "language", "web", abstraction_level=2, aliases=("TS",)),
    Skill("Go", "language", "systems", abstraction_level=2, aliases=("Golang",)),
    Skill("Rust", "language", "systems", abstraction_level=2),
    Skill("C++", "language", "systems", abstraction_level=1, aliases=("CPP",)),
    Skill("C", "language", "systems", abstraction_level=1),
    Skill("Swift", "language", "mobile", abstraction_level=2),
    Skill("Objective-C", "language", "mobile", abstraction_level=2),
    Skill("R", "language", "data_science", abstraction_level=2),
    Skill("Julia", "language", "data_science", abstraction_level=2),
    Skill("MATLAB", "language", "data_science", abstraction_level=2),
    Skill("Haskell", "language", "functional", abstraction_level=2),
    Skill("Erlang", "language", "functional", abstraction_level=2),
    Skill("Elixir", "language", "functional", abstraction_level=2),
    Skill("Clojure", "language", "functional", abstraction_level=2),
    Skill("Bash", "language", "shell", abstraction_level=2, aliases=("Shell",)),
    Skill("PowerShell", "language", "shell", abstraction_level=2),
    Skill("PHP", "language", "web", abstraction_level=2),
    Skill("Dart", "language", "mobile", abstraction_level=2),
)

# ===== Databases =====
_reg(
    Skill("PostgreSQL", "database", "relational", abstraction_level=2, aliases=("Postgres",)),
    Skill("MySQL", "database", "relational", abstraction_level=2),
    Skill("MariaDB", "database", "relational", abstraction_level=2),
    Skill("SQL Server", "database", "relational", "azure", abstraction_level=2, aliases=("MSSQL",)),
    Skill("Oracle DB", "database", "relational", abstraction_level=2, aliases=("Oracle",)),
    Skill("SQLite", "database", "relational", abstraction_level=2),
    Skill("MongoDB", "database", "document", abstraction_level=2),
    Skill("CouchDB", "database", "document", abstraction_level=2),
    Skill("Couchbase", "database", "document", abstraction_level=2),
    Skill("DynamoDB", "database", "wide_column", "aws", abstraction_level=3),
    Skill("Cassandra", "database", "wide_column", abstraction_level=2),
    Skill("HBase", "database", "wide_column", abstraction_level=2),
    Skill("ScyllaDB", "database", "wide_column", abstraction_level=2),
    Skill("Firestore", "database", "document", "gcp", abstraction_level=3),
    Skill("CosmosDB", "database", "multi_model", "azure", abstraction_level=3),
    Skill("Redis", "database", "key_value", abstraction_level=2),
    Skill("Memcached", "database", "key_value", abstraction_level=2),
    Skill("etcd", "database", "key_value", abstraction_level=2),
    Skill("Neo4j", "database", "graph", abstraction_level=2),
    Skill("ArangoDB", "database", "graph", abstraction_level=2),
    Skill("Amazon Neptune", "database", "graph", "aws", abstraction_level=3),
    Skill("InfluxDB", "database", "time_series", abstraction_level=2),
    Skill("TimescaleDB", "database", "time_series", abstraction_level=2),
    Skill("Elasticsearch", "database", "search", abstraction_level=2, aliases=("ES",)),
    Skill("OpenSearch", "database", "search", "aws", abstraction_level=2),
    Skill("Solr", "database", "search", abstraction_level=2),
    Skill("Pinecone", "database", "vector", abstraction_level=3),
    Skill("Weaviate", "database", "vector", abstraction_level=2),
    Skill("Milvus", "database", "vector", abstraction_level=2),
    Skill("ChromaDB", "database", "vector", abstraction_level=2),
    Skill("pgvector", "database", "vector", abstraction_level=2),
)

# ===== Cloud — Object Storage =====
_reg(
    Skill("S3", "cloud", "object_storage", "aws", abstraction_level=3),
    Skill("GCS", "cloud", "object_storage", "gcp", abstraction_level=3, aliases=("Google Cloud Storage",)),
    Skill("Blob Storage", "cloud", "object_storage", "azure", abstraction_level=3, aliases=("Azure Blob",)),
)

# ===== Cloud — Compute =====
_reg(
    Skill("EC2", "cloud", "compute", "aws", abstraction_level=1),
    Skill("Compute Engine", "cloud", "compute", "gcp", abstraction_level=1),
    Skill("Azure VMs", "cloud", "compute", "azure", abstraction_level=1, aliases=("Virtual Machines",)),
)

# ===== Cloud — Serverless =====
_reg(
    Skill("Lambda", "cloud", "serverless", "aws", abstraction_level=3, aliases=("AWS Lambda",)),
    Skill("Cloud Functions", "cloud", "serverless", "gcp", abstraction_level=3),
    Skill("Azure Functions", "cloud", "serverless", "azure", abstraction_level=3),
)

# ===== Cloud — Container Orchestration =====
_reg(
    Skill("ECS", "cloud", "container_orchestration", "aws", abstraction_level=3),
    Skill("EKS", "cloud", "container_orchestration", "aws", abstraction_level=3),
    Skill("GKE", "cloud", "container_orchestration", "gcp", abstraction_level=3),
    Skill("AKS", "cloud", "container_orchestration", "azure", abstraction_level=3),
)

# ===== Cloud — Database Services =====
_reg(
    Skill("RDS", "cloud", "sql_managed", "aws", abstraction_level=3),
    Skill("Cloud SQL", "cloud", "sql_managed", "gcp", abstraction_level=3),
    Skill("Azure SQL", "cloud", "sql_managed", "azure", abstraction_level=3),
)

# ===== Cloud — Message Queue =====
_reg(
    Skill("SQS", "cloud", "message_queue", "aws", abstraction_level=3),
    Skill("Pub/Sub", "cloud", "message_queue", "gcp", abstraction_level=3, aliases=("Google Pub/Sub",)),
    Skill("Azure Service Bus", "cloud", "message_queue", "azure", abstraction_level=3),
)

# ===== Cloud — Streaming =====
_reg(
    Skill("Kinesis", "cloud", "streaming", "aws", abstraction_level=3),
    Skill("Dataflow", "cloud", "streaming", "gcp", abstraction_level=3),
    Skill("Event Hubs", "cloud", "streaming", "azure", abstraction_level=3),
)

# ===== Cloud — Data Warehouse =====
_reg(
    Skill("Redshift", "cloud", "data_warehouse", "aws", abstraction_level=3),
    Skill("BigQuery", "cloud", "data_warehouse", "gcp", abstraction_level=3),
    Skill("Synapse", "cloud", "data_warehouse", "azure", abstraction_level=3, aliases=("Azure Synapse",)),
)

# ===== Cloud — ML Platform =====
_reg(
    Skill("SageMaker", "cloud", "ml_platform", "aws", abstraction_level=3),
    Skill("Vertex AI", "cloud", "ml_platform", "gcp", abstraction_level=3),
    Skill("Azure ML", "cloud", "ml_platform", "azure", abstraction_level=3),
)

# ===== Cloud — CDN =====
_reg(
    Skill("CloudFront", "cloud", "cdn", "aws", abstraction_level=3),
    Skill("Cloud CDN", "cloud", "cdn", "gcp", abstraction_level=3),
    Skill("Azure CDN", "cloud", "cdn", "azure", abstraction_level=3),
)

# ===== Cloud — IAM =====
_reg(
    Skill("IAM", "cloud", "iam", "aws", abstraction_level=3, aliases=("AWS IAM",)),
    Skill("Cloud IAM", "cloud", "iam", "gcp", abstraction_level=3),
    Skill("Azure AD", "cloud", "iam", "azure", abstraction_level=3, aliases=("Entra ID",)),
)

# ===== Cloud — Monitoring =====
_reg(
    Skill("CloudWatch", "cloud", "monitoring", "aws", abstraction_level=3),
    Skill("Cloud Monitoring", "cloud", "monitoring", "gcp", abstraction_level=3),
    Skill("Azure Monitor", "cloud", "monitoring", "azure", abstraction_level=3),
)

# ===== Cloud — Secrets =====
_reg(
    Skill("AWS Secrets Manager", "cloud", "secrets", "aws", abstraction_level=3),
    Skill("Secret Manager", "cloud", "secrets", "gcp", abstraction_level=3, aliases=("GCP Secret Manager",)),
    Skill("Key Vault", "cloud", "secrets", "azure", abstraction_level=3, aliases=("Azure Key Vault",)),
)

# ===== Cloud — Provider (top-level) =====
_reg(
    Skill("AWS", "cloud", "provider", "aws", abstraction_level=4, aliases=("Amazon Web Services",)),
    Skill("GCP", "cloud", "provider", "gcp", abstraction_level=4, aliases=("Google Cloud", "Google Cloud Platform")),
    Skill("Azure", "cloud", "provider", "azure", abstraction_level=4, aliases=("Microsoft Azure",)),
)

# ===== Frameworks — Python Web =====
_reg(
    Skill("Django", "framework", "python_web", abstraction_level=2),
    Skill("Flask", "framework", "python_web", abstraction_level=2),
    Skill("FastAPI", "framework", "python_web", abstraction_level=2),
    Skill("Tornado", "framework", "python_web", abstraction_level=2),
    Skill("Starlette", "framework", "python_web", abstraction_level=2),
)

# ===== Frameworks — Java Web =====
_reg(
    Skill("Spring Boot", "framework", "java_web", abstraction_level=2, aliases=("Spring",)),
    Skill("Micronaut", "framework", "java_web", abstraction_level=2),
    Skill("Quarkus", "framework", "java_web", abstraction_level=2),
)

# ===== Frameworks — Node Web =====
_reg(
    Skill("Express", "framework", "node_web", abstraction_level=2, aliases=("Express.js",)),
    Skill("Fastify", "framework", "node_web", abstraction_level=2),
    Skill("NestJS", "framework", "node_web", abstraction_level=2),
    Skill("Koa", "framework", "node_web", abstraction_level=2),
)

# ===== Frameworks — Frontend =====
_reg(
    Skill("React", "framework", "frontend", abstraction_level=2, aliases=("React.js", "ReactJS")),
    Skill("Vue", "framework", "frontend", abstraction_level=2, aliases=("Vue.js", "VueJS")),
    Skill("Angular", "framework", "frontend", abstraction_level=2),
    Skill("Svelte", "framework", "frontend", abstraction_level=2),
    Skill("Next.js", "framework", "frontend", abstraction_level=2, aliases=("NextJS",)),
    Skill("Nuxt.js", "framework", "frontend", abstraction_level=2, aliases=("NuxtJS",)),
)

# ===== Frameworks — CSS =====
_reg(
    Skill("Tailwind CSS", "framework", "css", abstraction_level=2, aliases=("Tailwind",)),
    Skill("Bootstrap", "framework", "css", abstraction_level=2),
    Skill("Material UI", "framework", "css", abstraction_level=2, aliases=("MUI",)),
)

# ===== Frameworks — Mobile =====
_reg(
    Skill("React Native", "framework", "mobile_cross", abstraction_level=2),
    Skill("Flutter", "framework", "mobile_cross", abstraction_level=2),
    Skill("Xamarin", "framework", "mobile_cross", abstraction_level=2),
)

# ===== Data Processing =====
_reg(
    Skill("Spark", "data", "batch_processing", abstraction_level=2, aliases=("Apache Spark", "PySpark")),
    Skill("Flink", "data", "batch_processing", abstraction_level=2, aliases=("Apache Flink",)),
    Skill("MapReduce", "data", "batch_processing", abstraction_level=2),
    Skill("Beam", "data", "batch_processing", abstraction_level=2, aliases=("Apache Beam",)),
    Skill("Airflow", "data", "workflow_orchestrator", abstraction_level=2, aliases=("Apache Airflow",)),
    Skill("Prefect", "data", "workflow_orchestrator", abstraction_level=2),
    Skill("Dagster", "data", "workflow_orchestrator", abstraction_level=2),
    Skill("Luigi", "data", "workflow_orchestrator", abstraction_level=2),
    Skill("Snowflake", "data", "data_warehouse", abstraction_level=3),
    Skill("Databricks", "data", "data_warehouse", abstraction_level=3),
    Skill("ClickHouse", "data", "data_warehouse", abstraction_level=2),
    Skill("dbt", "data", "etl_tool", abstraction_level=2),
    Skill("Fivetran", "data", "etl_tool", abstraction_level=3),
    Skill("Airbyte", "data", "etl_tool", abstraction_level=2),
)

# ===== ML =====
_reg(
    Skill("TensorFlow", "ml", "ml_framework", abstraction_level=2, aliases=("TF",)),
    Skill("PyTorch", "ml", "ml_framework", abstraction_level=2),
    Skill("JAX", "ml", "ml_framework", abstraction_level=2),
    Skill("Keras", "ml", "ml_framework", abstraction_level=2),
    Skill("scikit-learn", "ml", "ml_framework", abstraction_level=2, aliases=("sklearn",)),
    Skill("MLflow", "ml", "mlops", abstraction_level=2),
    Skill("Kubeflow", "ml", "mlops", abstraction_level=2),
    Skill("Weights & Biases", "ml", "mlops", abstraction_level=3, aliases=("W&B", "wandb")),
    Skill("Hugging Face", "ml", "nlp", abstraction_level=2, aliases=("HuggingFace", "Transformers")),
    Skill("spaCy", "ml", "nlp", abstraction_level=2),
    Skill("Pandas", "ml", "data_analysis", abstraction_level=2),
    Skill("NumPy", "ml", "data_analysis", abstraction_level=2),
    Skill("Polars", "ml", "data_analysis", abstraction_level=2),
)

# ===== DevOps =====
_reg(
    Skill("Docker", "devops", "container_runtime", abstraction_level=2),
    Skill("Podman", "devops", "container_runtime", abstraction_level=2),
    Skill("Kubernetes", "devops", "container_orchestration", abstraction_level=2, aliases=("K8s",)),
    Skill("Docker Swarm", "devops", "container_orchestration", abstraction_level=2),
    Skill("Nomad", "devops", "container_orchestration", abstraction_level=2),
    Skill("GitHub Actions", "devops", "ci_cd", abstraction_level=3),
    Skill("GitLab CI", "devops", "ci_cd", abstraction_level=3),
    Skill("Jenkins", "devops", "ci_cd", abstraction_level=2),
    Skill("CircleCI", "devops", "ci_cd", abstraction_level=3),
    Skill("ArgoCD", "devops", "ci_cd", abstraction_level=2),
    Skill("Terraform", "devops", "iac", abstraction_level=2),
    Skill("Pulumi", "devops", "iac", abstraction_level=2),
    Skill("CloudFormation", "devops", "iac", "aws", abstraction_level=3),
    Skill("Ansible", "devops", "iac", abstraction_level=2),
    Skill("CDK", "devops", "iac", "aws", abstraction_level=3, aliases=("AWS CDK",)),
    Skill("Prometheus", "devops", "monitoring", abstraction_level=2),
    Skill("Grafana", "devops", "monitoring", abstraction_level=2),
    Skill("Datadog", "devops", "monitoring", abstraction_level=3),
    Skill("New Relic", "devops", "monitoring", abstraction_level=3),
    Skill("Splunk", "devops", "logging", abstraction_level=2),
    Skill("ELK Stack", "devops", "logging", abstraction_level=2),
    Skill("Fluentd", "devops", "logging", abstraction_level=2),
    Skill("Loki", "devops", "logging", abstraction_level=2),
    Skill("Vault", "devops", "secrets", abstraction_level=2, aliases=("HashiCorp Vault",)),
    Skill("Istio", "devops", "service_mesh", abstraction_level=2),
    Skill("Linkerd", "devops", "service_mesh", abstraction_level=2),
    Skill("Envoy", "devops", "service_mesh", abstraction_level=2),
)

# ===== Messaging =====
_reg(
    Skill("Kafka", "messaging", "message_broker", abstraction_level=2, aliases=("Apache Kafka",)),
    Skill("RabbitMQ", "messaging", "message_broker", abstraction_level=2),
    Skill("ActiveMQ", "messaging", "message_broker", abstraction_level=2),
    Skill("Pulsar", "messaging", "message_broker", abstraction_level=2, aliases=("Apache Pulsar",)),
    Skill("NATS", "messaging", "message_broker", abstraction_level=2),
)

# ===== API =====
_reg(
    Skill("REST", "api", "api_style", abstraction_level=4, aliases=("RESTful",)),
    Skill("GraphQL", "api", "api_style", abstraction_level=4),
    Skill("gRPC", "api", "api_style", abstraction_level=4),
    Skill("Kong", "api", "api_gateway", abstraction_level=2),
    Skill("Nginx", "api", "api_gateway", abstraction_level=2),
    Skill("Traefik", "api", "api_gateway", abstraction_level=2),
)

# ===== Testing =====
_reg(
    Skill("pytest", "testing", "python_testing", abstraction_level=2),
    Skill("Jest", "testing", "js_testing", abstraction_level=2),
    Skill("Mocha", "testing", "js_testing", abstraction_level=2),
    Skill("Vitest", "testing", "js_testing", abstraction_level=2),
    Skill("JUnit", "testing", "java_testing", abstraction_level=2),
    Skill("Selenium", "testing", "e2e_testing", abstraction_level=2),
    Skill("Playwright", "testing", "e2e_testing", abstraction_level=2),
    Skill("Cypress", "testing", "e2e_testing", abstraction_level=2),
    Skill("Locust", "testing", "load_testing", abstraction_level=2),
    Skill("k6", "testing", "load_testing", abstraction_level=2),
    Skill("JMeter", "testing", "load_testing", abstraction_level=2),
)

# ===== VCS =====
_reg(
    Skill("Git", "vcs", "version_control", abstraction_level=2),
    Skill("GitHub", "vcs", "git_platform", abstraction_level=3),
    Skill("GitLab", "vcs", "git_platform", abstraction_level=3),
    Skill("Bitbucket", "vcs", "git_platform", abstraction_level=3),
    Skill("Jira", "vcs", "project_management", abstraction_level=3),
    Skill("Linear", "vcs", "project_management", abstraction_level=3),
)

# ===== SQL (query language) =====
_reg(
    Skill("SQL", "database", "query_language", abstraction_level=4),
    Skill("T-SQL", "database", "query_language", "azure", abstraction_level=4),
    Skill("PL/SQL", "database", "query_language", abstraction_level=4),
)


# ---------------------------------------------------------------------------
# Lookup index — built once on module load
# ---------------------------------------------------------------------------

class SkillIndex:
    """Fast lookup index for skills by name/alias."""

    def __init__(self, skills: list[Skill]):
        self._by_name: dict[str, Skill] = {}
        for s in skills:
            self._by_name[s.name.lower()] = s
            for alias in s.aliases:
                self._by_name[alias.lower()] = s

    def find(self, name: str) -> Skill | None:
        """Find a skill by exact name or alias (case-insensitive)."""
        return self._by_name.get(name.lower())

    def find_fuzzy(self, name: str) -> Skill | None:
        """Find a skill by substring match (for longer names, min 4 chars)."""
        exact = self.find(name)
        if exact:
            return exact
        name_lower = name.lower()
        if len(name_lower) < 4:
            return None
        for key, skill in self._by_name.items():
            if name_lower in key or key in name_lower:
                return skill
        return None

    @property
    def all_skills(self) -> list[Skill]:
        """All unique skills in the registry."""
        seen = set()
        result = []
        for skill in self._by_name.values():
            if skill.name not in seen:
                seen.add(skill.name)
                result.append(skill)
        return result


# Global index — built once on import
SKILL_INDEX = SkillIndex(_SKILLS)


# ---------------------------------------------------------------------------
# Computed Transfer Scoring
# ---------------------------------------------------------------------------

def compute_transfer(source: str, target: str) -> TransferResult:
    """Compute transfer score between two skills.

    Scoring rules (deterministic):
    - Same skill (exact match): 1.0
    - Same subcategory: base 0.7
      + same abstraction level: +0.1
      + same platform (or both neutral): +0.1
      - different platform: -0.1
    - Same category, different subcategory: base 0.4
      + same abstraction level: +0.05
    - Different category entirely: 0.0

    Returns TransferResult with score and explanation.
    """
    source_skill = SKILL_INDEX.find_fuzzy(source)
    target_skill = SKILL_INDEX.find_fuzzy(target)

    # Unknown skills — can't compute transfer
    if not source_skill or not target_skill:
        return TransferResult(
            source=source, target=target,
            score=0.0, transferable=False,
            explanation=f"Unknown skill(s): "
                        f"{'[' + source + ']' if not source_skill else ''}"
                        f"{'[' + target + ']' if not target_skill else ''}",
        )

    # Exact same skill
    if source_skill is target_skill:
        return TransferResult(
            source=source, target=target,
            score=1.0, transferable=True,
            source_skill=source_skill, target_skill=target_skill,
            explanation=f"Exact match: {source_skill.name}",
        )

    score = 0.0
    reasons = []

    # Same subcategory
    if (source_skill.category == target_skill.category
            and source_skill.subcategory == target_skill.subcategory):
        score = 0.7
        reasons.append(f"Same subcategory: {source_skill.category}/{source_skill.subcategory}")

        # Abstraction level bonus
        if source_skill.abstraction_level == target_skill.abstraction_level:
            score += 0.1
            reasons.append(f"Same abstraction level ({source_skill.abstraction_level})")

        # Platform bonus/penalty
        if source_skill.platform == target_skill.platform:
            score += 0.1
            reasons.append("Same platform")
        elif source_skill.platform == "neutral" or target_skill.platform == "neutral":
            score += 0.05
            reasons.append("One is platform-neutral")
        else:
            score -= 0.1
            reasons.append(
                f"Different platforms ({source_skill.platform} vs {target_skill.platform})"
            )

    # Same category, different subcategory
    elif source_skill.category == target_skill.category:
        score = 0.4
        reasons.append(
            f"Same category ({source_skill.category}), "
            f"different subcategory ({source_skill.subcategory} vs {target_skill.subcategory})"
        )
        if source_skill.abstraction_level == target_skill.abstraction_level:
            score += 0.05
            reasons.append("Same abstraction level")

    # Different category
    else:
        score = 0.0
        reasons.append(
            f"Different categories ({source_skill.category} vs {target_skill.category})"
        )

    score = max(0.0, min(1.0, score))
    transferable = score >= 0.3

    return TransferResult(
        source=source, target=target,
        score=round(score, 3), transferable=transferable,
        source_skill=source_skill, target_skill=target_skill,
        explanation=" | ".join(reasons),
    )


@dataclass
class TransferResult:
    """Result of computing skill transfer between two skills."""
    source: str
    target: str
    score: float                # 0.0-1.0
    transferable: bool          # score >= 0.3
    source_skill: Skill | None = None
    target_skill: Skill | None = None
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "score": self.score,
            "transferable": self.transferable,
            "explanation": self.explanation,
            "source_meta": {
                "category": self.source_skill.category,
                "subcategory": self.source_skill.subcategory,
                "platform": self.source_skill.platform,
                "abstraction_level": self.source_skill.abstraction_level,
            } if self.source_skill else None,
            "target_meta": {
                "category": self.target_skill.category,
                "subcategory": self.target_skill.subcategory,
                "platform": self.target_skill.platform,
                "abstraction_level": self.target_skill.abstraction_level,
            } if self.target_skill else None,
        }


# ---------------------------------------------------------------------------
# Batch analysis — skill gap analysis with computed scores
# ---------------------------------------------------------------------------

def analyze_skill_gaps_v2(
    resume_skills: list[str],
    jd_skills: list[str],
) -> dict:
    """Analyze skill gaps using computed per-skill transfer scores.

    Returns:
    - exact_matches: list of exact skill matches
    - transferable: list of {jd_skill, best_resume_skill, score, explanation}
    - gaps: list of JD skills with no match or transfer
    - match_rate: fraction of exact matches
    - coverage_rate: fraction covered by exact + transferable
    - weighted_score: quality-weighted coverage (considers transfer scores)
    """
    resume_lower = {s.lower(): s for s in resume_skills}
    exact_matches = []
    transferable = []
    gaps = []

    total_transfer_score = 0.0

    for jd_skill in jd_skills:
        jd_lower = jd_skill.lower()

        # Exact match
        if jd_lower in resume_lower:
            exact_matches.append(jd_skill)
            total_transfer_score += 1.0
            continue

        # Compute transfer against all resume skills
        best = None
        for rs_lower, rs_original in resume_lower.items():
            result = compute_transfer(rs_original, jd_skill)
            if result.transferable:
                if best is None or result.score > best.score:
                    best = result

        if best:
            transferable.append({
                "jd_skill": jd_skill,
                "best_resume_skill": best.source,
                "score": best.score,
                "explanation": best.explanation,
            })
            total_transfer_score += best.score
        else:
            gaps.append(jd_skill)

    n = max(len(jd_skills), 1)
    return {
        "exact_matches": exact_matches,
        "transferable": transferable,
        "gaps": gaps,
        "match_rate": len(exact_matches) / n,
        "coverage_rate": (len(exact_matches) + len(transferable)) / n,
        "weighted_score": total_transfer_score / n,
    }
