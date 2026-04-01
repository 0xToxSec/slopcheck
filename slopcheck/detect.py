"""Detection engine. Takes PackageInfo, returns a verdict."""

from dataclasses import dataclass, field
from typing import List, Optional
from slopcheck.registries import PackageInfo


# ---------------------------------------------------------------------------
# Hallucination pattern corpus
# LLMs love smashing a popular package name + a buzzy suffix together.
# These combos almost never exist. When they do, they're bait.
# ---------------------------------------------------------------------------

HALLUCINATION_PREFIXES = [
    "easy-", "simple-", "quick-", "fast-", "auto-", "smart-",
    "py-", "python-", "node-", "go-", "rust-",
    "ai-", "gpt-", "llm-", "ml-", "openai-", "langchain-",
]

HALLUCINATION_SUFFIXES = [
    "-helper", "-helpers", "-utils", "-util", "-tools", "-tool",
    "-wrapper", "-client", "-sdk", "-api", "-lib",
    "-ai", "-gpt", "-llm", "-ml", "-openai",
    "-easy", "-simple", "-fast", "-plus", "-pro", "-lite",
    "-extra", "-extended", "-enhanced", "-advanced",
]

# Packages LLMs commonly reference -- used for typosquat "did you mean?" checks
POPULAR_PACKAGES = {
    "pypi": [
        "requests", "flask", "django", "fastapi", "numpy", "pandas",
        "scipy", "matplotlib", "sqlalchemy", "celery", "redis", "boto3",
        "pillow", "beautifulsoup4", "scrapy", "pytest", "black",
        "httpx", "pydantic", "uvicorn", "gunicorn", "click", "typer",
        "openai", "langchain", "transformers", "torch", "tensorflow",
        "scikit-learn", "streamlit", "gradio", "anthropic",
        "cryptography", "paramiko", "fabric", "jinja2", "aiohttp",
    ],
    "npm": [
        "express", "react", "next", "vue", "svelte", "axios",
        "lodash", "moment", "dayjs", "chalk", "commander", "inquirer",
        "webpack", "vite", "esbuild", "typescript", "eslint", "prettier",
        "socket.io", "mongoose", "prisma", "sequelize", "passport",
        "jsonwebtoken", "bcrypt", "dotenv", "cors", "helmet",
        "openai", "langchain", "puppeteer", "playwright",
    ],
    "crates.io": [
        "serde", "tokio", "reqwest", "clap", "axum", "actix-web",
        "diesel", "sqlx", "tracing", "anyhow", "thiserror", "rand",
        "hyper", "warp", "rocket", "rayon", "crossbeam", "regex",
        "chrono", "uuid", "log", "env_logger", "config",
    ],
    "go": [
        "github.com/gin-gonic/gin", "github.com/gorilla/mux",
        "github.com/go-chi/chi", "github.com/stretchr/testify",
        "github.com/spf13/cobra", "github.com/spf13/viper",
        "gorm.io/gorm", "github.com/gofiber/fiber",
        "github.com/labstack/echo", "github.com/sirupsen/logrus",
        "go.uber.org/zap", "github.com/redis/go-redis",
    ],
    "rubygems": [
        "rails", "rack", "sinatra", "devise", "pundit", "sidekiq",
        "rspec", "capybara", "puma", "nokogiri", "faker", "rubocop",
        "activerecord", "actionpack", "activesupport", "bundler",
        "json", "httparty", "faraday", "redis", "pg", "mysql2",
        "aws-sdk", "stripe", "minitest", "resque", "whenever",
    ],
    "maven": [
        "org.springframework:spring-core", "org.springframework.boot:spring-boot",
        "com.google.guava:guava", "org.apache.commons:commons-lang3",
        "junit:junit", "org.mockito:mockito-core", "org.slf4j:slf4j-api",
        "com.fasterxml.jackson.core:jackson-databind", "org.projectlombok:lombok",
        "org.apache.httpcomponents:httpclient", "com.squareup.okhttp3:okhttp",
        "org.hibernate:hibernate-core", "com.google.code.gson:gson",
        "org.apache.logging.log4j:log4j-core", "io.netty:netty-all",
    ],
    "packagist": [
        "laravel/framework", "symfony/symfony", "guzzlehttp/guzzle",
        "monolog/monolog", "phpunit/phpunit", "doctrine/orm",
        "twig/twig", "league/flysystem", "vlucas/phpdotenv",
        "briannesbitt/carbon", "ramsey/uuid", "spatie/laravel-permission",
        "barryvdh/laravel-debugbar", "fzaninotto/faker", "predis/predis",
        "intervention/image", "maatwebsite/excel", "league/oauth2-server",
    ],
}


def _levenshtein(s1: str, s2: str) -> int:
    """Textbook Levenshtein. Fine for short package names."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(s2)]


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass
class Flag:
    """One thing we noticed about a package."""
    signal: str      # e.g. "NOT_FOUND", "FRESH_PACKAGE", "LOW_DOWNLOADS"
    severity: str    # "critical", "warning", "info"
    message: str     # human-readable, blunt

@dataclass
class Verdict:
    """Final call on a package."""
    package: str
    ecosystem: str
    status: str          # "SLOP", "SUS", "OK", "ERROR"
    flags: List[Flag] = field(default_factory=list)
    suggestion: Optional[str] = None  # "did you mean X?"

    @property
    def is_bad(self) -> bool:
        return self.status in ("SLOP", "SUS")


def _check_hallucination_pattern(name: str) -> Optional[str]:
    """Does this name smell like LLM output?"""
    lower = name.lower()
    for prefix in HALLUCINATION_PREFIXES:
        if lower.startswith(prefix):
            remainder = lower[len(prefix):]
            if remainder and len(remainder) > 2:
                return f"Name starts with '{prefix}' -- classic LLM naming pattern"
    for suffix in HALLUCINATION_SUFFIXES:
        if lower.endswith(suffix):
            remainder = lower[:-len(suffix)]
            if remainder and len(remainder) > 2:
                return f"Name ends with '{suffix}' -- classic LLM naming pattern"
    return None


def _find_similar(name: str, ecosystem: str, max_distance: int = 2) -> Optional[str]:
    """Find the closest real package by Levenshtein distance."""
    candidates = POPULAR_PACKAGES.get(ecosystem, [])
    best = None
    best_dist = max_distance + 1
    lower = name.lower()
    for pkg in candidates:
        # For Go modules, just compare the last segment
        compare = pkg.split("/")[-1] if "/" in pkg else pkg
        dist = _levenshtein(lower, compare.lower())
        if dist > 0 and dist < best_dist:
            best = pkg
            best_dist = dist
    return best if best_dist <= max_distance else None


def analyze(info: PackageInfo) -> Verdict:
    """Run all detection signals against a PackageInfo. Return a Verdict."""
    flags: List[Flag] = []

    # ---- Signal 0: Did the registry check fail? ----
    if info.error and not info.exists:
        flags.append(Flag(
            signal="REGISTRY_ERROR",
            severity="error",
            message=f"Could not reach {info.ecosystem} registry: {info.error}"
        ))
        return Verdict(
            package=info.name,
            ecosystem=info.ecosystem,
            status="ERROR",
            flags=flags,
        )

    # ---- Signal 1: Does it exist? ----
    if not info.exists:
        flags.append(Flag(
            signal="NOT_FOUND",
            severity="critical",
            message=f"Package '{info.name}' does not exist on {info.ecosystem}. Your AI made it up."
        ))

        # Check hallucination pattern even on non-existent packages
        pattern_msg = _check_hallucination_pattern(info.name)
        if pattern_msg:
            flags.append(Flag(
                signal="HALLUCINATION_PATTERN",
                severity="critical",
                message=pattern_msg
            ))

        suggestion = _find_similar(info.name, info.ecosystem)
        return Verdict(
            package=info.name,
            ecosystem=info.ecosystem,
            status="SLOP",
            flags=flags,
            suggestion=suggestion,
        )

    # ---- Package exists. Now: is it sketchy? ----

    # Signal 2: How old is it?
    age = info.age_days
    if age is not None:
        if age < 7:
            flags.append(Flag(
                signal="BRAND_NEW",
                severity="critical",
                message=f"Created {age} days ago. That's basically yesterday. High chance someone registered this to trap you."
            ))
        elif age < 30:
            flags.append(Flag(
                signal="FRESH_PACKAGE",
                severity="warning",
                message=f"Only {age} days old. New packages deserve extra scrutiny."
            ))
        elif age < 90:
            flags.append(Flag(
                signal="RECENTLY_CREATED",
                severity="info",
                message=f"Created {age} days ago. Relatively new."
            ))

    # Signal 3: Download count
    if info.downloads is not None:
        if info.downloads < 100:
            flags.append(Flag(
                signal="GHOST_TOWN",
                severity="warning",
                message=f"Only {info.downloads} downloads. Nobody uses this."
            ))
        elif info.downloads < 1000:
            flags.append(Flag(
                signal="LOW_DOWNLOADS",
                severity="info",
                message=f"{info.downloads} downloads. Not exactly popular."
            ))

    # Signal 4: Hallucination pattern on existing package (could be registered bait)
    # But if the package is old and popular, it's just a naming coincidence.
    pattern_msg = _check_hallucination_pattern(info.name)
    if pattern_msg:
        is_established = (
            (age is not None and age > 365)
            or (info.downloads is not None and info.downloads > 10_000)
        )
        if is_established:
            flags.append(Flag(
                signal="HALLUCINATION_PATTERN",
                severity="info",
                message=f"{pattern_msg}. Name looks like LLM bait but package is established."
            ))
        else:
            flags.append(Flag(
                signal="HALLUCINATION_PATTERN",
                severity="warning",
                message=f"{pattern_msg}. Package exists but the name screams 'LLM bait'."
            ))

    # Signal 5: No repo link (legitimate packages almost always have one)
    if not info.repo_url:
        flags.append(Flag(
            signal="NO_REPO",
            severity="info",
            message="No source repository linked. Harder to verify what this code actually does."
        ))

    # Signal 6: Typosquat check (skip if the package itself is a known popular package)
    popular_set = {p.lower() for p in POPULAR_PACKAGES.get(info.ecosystem, [])}
    similar = _find_similar(info.name, info.ecosystem, max_distance=2)
    if similar and similar.lower() != info.name.lower() and info.name.lower() not in popular_set:
        flags.append(Flag(
            signal="TYPOSQUAT_RISK",
            severity="warning",
            message=f"Suspiciously close to '{similar}'. Could be a typosquat."
        ))

    # ---- Determine overall status ----
    crits = sum(1 for f in flags if f.severity == "critical")
    warns = sum(1 for f in flags if f.severity == "warning")

    if crits > 0:
        status = "SLOP"
    elif warns > 0:
        status = "SUS"
    else:
        status = "OK"

    # Only suggest alternatives if we're actually flagging something
    show_suggestion = (
        similar
        and similar.lower() != info.name.lower()
        and info.name.lower() not in popular_set
        and status != "OK"
    )

    return Verdict(
        package=info.name,
        ecosystem=info.ecosystem,
        status=status,
        flags=flags,
        suggestion=similar if show_suggestion else None,
    )
