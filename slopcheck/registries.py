"""Registry API clients for PyPI, npm, crates.io, Go, RubyGems, Maven, and Packagist."""

import requests
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

from slopcheck import __version__


@dataclass
class PackageInfo:
    """What we know about a package from its registry."""
    name: str
    ecosystem: str
    exists: bool
    created: Optional[datetime] = None
    downloads: Optional[int] = None       # monthly or recent
    latest_version: Optional[str] = None
    description: Optional[str] = None
    repo_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def age_days(self) -> Optional[int]:
        if self.created is None:
            return None
        now = datetime.now(timezone.utc)
        return (now - self.created).days


TIMEOUT = 8  # seconds -- don't hang on slow registries


def check_pypi(name: str) -> PackageInfo:
    """Hit PyPI JSON API + pypistats for download counts."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 404:
            return PackageInfo(name=name, ecosystem="pypi", exists=False)
        r.raise_for_status()
        data = r.json()
        info = data.get("info", {})

        # Parse creation date from oldest release
        releases = data.get("releases", {})
        created = None
        if releases:
            for ver in sorted(releases.keys()):
                files = releases[ver]
                if files:
                    upload = files[0].get("upload_time_iso_8601") or files[0].get("upload_time")
                    if upload:
                        # Handle both formats
                        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                created = datetime.strptime(upload, fmt).replace(tzinfo=timezone.utc)
                                break
                            except ValueError:
                                continue
                    if created:
                        break

        # Repo URL: project_urls dict (PEP 566) > home_page (deprecated)
        # Keys vary in casing across packages, so normalize to lowercase.
        repo_url = None
        project_urls = info.get("project_urls") or {}
        urls_lower = {k.lower(): v for k, v in project_urls.items()}
        for key in ("source", "source code", "repository", "github", "homepage"):
            if key in urls_lower:
                repo_url = urls_lower[key]
                break
        if not repo_url:
            repo_url = info.get("home_page") or None

        # Download count from pypistats (best-effort, don't block on failure)
        downloads = None
        try:
            dl_r = requests.get(
                f"https://pypistats.org/api/packages/{name}/recent",
                timeout=TIMEOUT,
            )
            if dl_r.status_code == 200:
                dl_data = dl_r.json().get("data", {})
                downloads = dl_data.get("last_month")
        except requests.RequestException:
            pass

        return PackageInfo(
            name=name,
            ecosystem="pypi",
            exists=True,
            created=created,
            downloads=downloads,
            latest_version=info.get("version"),
            description=info.get("summary", ""),
            repo_url=repo_url,
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="pypi", exists=False, error=str(e))


def check_npm(name: str) -> PackageInfo:
    """Hit npm registry API."""
    url = f"https://registry.npmjs.org/{name}"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 404:
            return PackageInfo(name=name, ecosystem="npm", exists=False)
        r.raise_for_status()
        data = r.json()

        # Creation date
        created = None
        time_data = data.get("time", {})
        if "created" in time_data:
            try:
                created = datetime.fromisoformat(time_data["created"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Downloads -- separate API call
        downloads = None
        try:
            dl_r = requests.get(
                f"https://api.npmjs.org/downloads/point/last-month/{name}",
                timeout=TIMEOUT
            )
            if dl_r.status_code == 200:
                downloads = dl_r.json().get("downloads")
        except requests.RequestException:
            pass

        latest = data.get("dist-tags", {}).get("latest")
        desc = data.get("description", "")
        repo = data.get("repository", {})
        repo_url = repo.get("url", "") if isinstance(repo, dict) else ""

        return PackageInfo(
            name=name,
            ecosystem="npm",
            exists=True,
            created=created,
            downloads=downloads,
            latest_version=latest,
            description=desc,
            repo_url=repo_url,
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="npm", exists=False, error=str(e))


def check_crates(name: str) -> PackageInfo:
    """Hit crates.io API."""
    url = f"https://crates.io/api/v1/crates/{name}"
    headers = {"User-Agent": f"slopcheck/{__version__} (supply-chain-safety)"}
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code == 404:
            return PackageInfo(name=name, ecosystem="crates.io", exists=False)
        r.raise_for_status()
        data = r.json().get("crate", {})

        created = None
        if data.get("created_at"):
            try:
                created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return PackageInfo(
            name=name,
            ecosystem="crates.io",
            exists=True,
            created=created,
            downloads=data.get("recent_downloads"),
            latest_version=data.get("newest_version"),
            description=data.get("description", ""),
            repo_url=data.get("repository"),
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="crates.io", exists=False, error=str(e))


def check_go(name: str) -> PackageInfo:
    """Hit Go module proxy."""
    url = f"https://proxy.golang.org/{name}/@latest"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code in (404, 410):
            return PackageInfo(name=name, ecosystem="go", exists=False)
        r.raise_for_status()
        data = r.json()

        created = None
        if data.get("Time"):
            try:
                created = datetime.fromisoformat(data["Time"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return PackageInfo(
            name=name,
            ecosystem="go",
            exists=True,
            created=created,
            latest_version=data.get("Version"),
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="go", exists=False, error=str(e))


def check_rubygems(name: str) -> PackageInfo:
    """Hit RubyGems.org API."""
    url = f"https://rubygems.org/api/v1/gems/{name}.json"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 404:
            return PackageInfo(name=name, ecosystem="rubygems", exists=False)
        r.raise_for_status()
        data = r.json()

        created = None
        if data.get("created_at"):
            try:
                created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return PackageInfo(
            name=name,
            ecosystem="rubygems",
            exists=True,
            created=created,
            downloads=data.get("downloads"),
            latest_version=data.get("version"),
            description=data.get("info", ""),
            repo_url=data.get("source_code_uri") or data.get("homepage_uri"),
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="rubygems", exists=False, error=str(e))


def check_maven(name: str) -> PackageInfo:
    """Hit Maven Central search API. Expects 'group:artifact' format.

    NOTE: Maven Central's `timestamp` field is the *latest version* upload time,
    not the first-publish date. We intentionally skip the created field here to
    avoid false positives from the age-based detection signals. The versionCount
    field is used as a maturity proxy via downloads (more versions = more established).
    """
    # If user passes group:artifact, split it. Otherwise search by artifact name.
    if ":" in name:
        group, artifact = name.split(":", 1)
        query = f"g:{group}+AND+a:{artifact}"
    else:
        artifact = name
        query = f"a:{artifact}"

    url = f"https://search.maven.org/solrsearch/select?q={query}&rows=1&wt=json"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        docs = data.get("response", {}).get("docs", [])

        if not docs:
            return PackageInfo(name=name, ecosystem="maven", exists=False)

        doc = docs[0]

        # Use versionCount as a rough maturity proxy (no real download stats
        # available from Maven Central search). A package with 50+ versions
        # is clearly established; one with 1-2 versions is new.
        version_count = doc.get("versionCount", 0)

        return PackageInfo(
            name=name,
            ecosystem="maven",
            exists=True,
            created=None,  # intentionally skipped -- see docstring
            downloads=version_count,  # proxy: version count as "downloads"
            latest_version=doc.get("latestVersion"),
            description="",
            repo_url=None,
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="maven", exists=False, error=str(e))


def check_packagist(name: str) -> PackageInfo:
    """Hit Packagist (PHP/Composer) API. Expects 'vendor/package' format."""
    url = f"https://repo.packagist.org/p2/{name}.json"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 404:
            return PackageInfo(name=name, ecosystem="packagist", exists=False)
        r.raise_for_status()
        data = r.json()

        # p2 format: {"packages": {"vendor/name": [{"version": "...", ...}]}}
        versions = data.get("packages", {}).get(name, [])
        if not versions:
            return PackageInfo(name=name, ecosystem="packagist", exists=False)

        latest = versions[0] if versions else {}

        # Downloads from stats endpoint (best-effort)
        downloads = None
        try:
            stats_r = requests.get(
                f"https://packagist.org/packages/{name}/stats.json",
                timeout=TIMEOUT,
            )
            if stats_r.status_code == 200:
                downloads = stats_r.json().get("downloads", {}).get("monthly")
        except requests.RequestException:
            pass

        # Created date from the oldest version's time
        created = None
        if versions:
            oldest = versions[-1]
            if oldest.get("time"):
                try:
                    created = datetime.fromisoformat(oldest["time"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

        return PackageInfo(
            name=name,
            ecosystem="packagist",
            exists=True,
            created=created,
            downloads=downloads,
            latest_version=latest.get("version"),
            description=latest.get("description", ""),
            repo_url=latest.get("source", {}).get("url") if isinstance(latest.get("source"), dict) else None,
        )
    except requests.RequestException as e:
        return PackageInfo(name=name, ecosystem="packagist", exists=False, error=str(e))


# Map ecosystem names to check functions
REGISTRY_CHECKERS = {
    "pypi": check_pypi,
    "npm": check_npm,
    "crates.io": check_crates,
    "go": check_go,
    "rubygems": check_rubygems,
    "maven": check_maven,
    "packagist": check_packagist,
}
