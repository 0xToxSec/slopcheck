# slopcheck

Detect AI-hallucinated packages before you install them.

When your AI coding assistant suggests `flask-gpt-helper` or `easy-requests`, those packages probably don't exist. But someone might register them as malware before you notice. That's [slopsquatting](https://blog.sethlarson.dev/slopsquatting).

**slopcheck** catches it first.

## Install

```bash
pip install slopcheck
```

Or one-liner if you're in a hurry:

**Mac/Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/0xToxSec/slopcheck/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/0xToxSec/slopcheck/main/install.ps1 | iex
```

## Usage

### Scan your project

```bash
# Auto-detect dependency files in current directory
slopcheck .

# Scan a specific file
slopcheck requirements.txt
```

### Safe install (check first, install if clean)

```bash
# Instead of: pip install flask requests sketchy-package
slopcheck install flask requests sketchy-package

# Auto-detects ecosystem from your project (package.json = npm, etc.)
# Or force it:
slopcheck install express lodash --ecosystem npm

# Install suspicious packages anyway (slop is ALWAYS blocked):
slopcheck install some-package --force
```

Slop gets blocked. Always. Suspicious packages get skipped unless you pass `--force`. Clean packages install normally through your real package manager.

### Auto-fix (remove slop from your files)

```bash
# Scan and auto-remove hallucinated packages
slopcheck . --fix

# Fix a specific file
slopcheck requirements.txt --fix
```

SLOP packages get commented out with `# [slopcheck] removed:` so you can see what was killed. JSON files (package.json, Pipfile.lock) get the keys deleted.

### Set up git hook (one command)

```bash
slopcheck init
```

That's it. Now slopcheck runs before every commit. If slop is found, the commit is blocked. Run `slopcheck . --fix` to clean up, then commit again.

### Check a single package

```bash
slopcheck flask-gpt-helper --pkg pypi
slopcheck react-ai-utils --pkg npm
slopcheck easy-http --pkg crates.io
slopcheck github.com/fake/module --pkg go
slopcheck fake-gem --pkg rubygems
slopcheck com.fake:library --pkg maven
slopcheck fake/package --pkg packagist
```

### Output

```
  [SLOP] flask-gpt-helper (pypi)
    > Package 'flask-gpt-helper' does not exist on pypi. Your AI made it up.
    > Name ends with '-helper' -- classic LLM naming pattern

  [SLOP] reqeusts (pypi)
    > Package 'reqeusts' does not exist on pypi. Your AI made it up.
    ? Did you mean: requests

  [SUS] easy-requests (pypi)
    > Name starts with 'easy-' -- classic LLM naming pattern. Package exists but the name screams 'LLM bait'.

  [OK] requests (pypi)
```

### JSON output (for CI)

```bash
slopcheck requirements.txt --json
```

## What it detects

- **Non-existent packages** -- the #1 signal. If it's not on the registry, your AI made it up.
- **Brand new packages** -- created in the last 7 days? Probably registered to trap you.
- **Low downloads** -- under 100 downloads means nobody uses it.
- **Hallucination patterns** -- LLMs love naming packages `{popular-lib}-{ai|gpt|helper|utils}`. We check for these patterns.
- **Typosquats** -- Levenshtein distance check against popular packages with "did you mean?" suggestions.
- **Missing repo links** -- legitimate packages almost always link to source code.

### Allowlist (skip packages during scans)

```bash
# Your team has internal packages that aren't on public registries?
slopcheck allow my-internal-lib

# Remove from allowlist
slopcheck allow my-internal-lib --remove

# See what's allowlisted
slopcheck allow --list
```

Allowlisted packages are stored in `.slopcheck` (one per line). slopcheck walks up from the current directory to find it, so drop one in your repo root and your whole team shares it.

## Supported ecosystems

| Ecosystem | Dependency files | Registry |
|-----------|-----------------|----------|
| PyPI | `requirements.txt`, `pyproject.toml`, `Pipfile`, `Pipfile.lock` | pypi.org |
| npm | `package.json` | npmjs.org |
| crates.io | `Cargo.toml` | crates.io |
| Go | `go.mod` | proxy.golang.org |
| RubyGems | `Gemfile` | rubygems.org |
| Maven | `pom.xml`, `build.gradle` | search.maven.org |
| Packagist | `composer.json` | packagist.org |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Clean -- all packages check out |
| 1 | Suspicious -- some packages deserve a second look |
| 2 | Slop detected -- hallucinated or dangerously new packages found |
| 3 | Registry error -- couldn't reach one or more registries to verify |

## Options

```
slopcheck [target] [options]

target          Directory, file, or package name (default: .)
--pkg ECOSYSTEM Check single package (pypi, npm, crates.io, go, rubygems, maven, packagist)
--workers N     Parallel registry checks (default: 10)
--json          JSON output for CI pipelines
--fix           Auto-remove SLOP packages from dependency files
```

## GitHub Action

Add this to your repo at `.github/workflows/slopcheck.yml` and every PR that touches dependency files gets scanned automatically:

```yaml
name: slopcheck

on:
  pull_request:
    paths:
      - 'requirements*.txt'
      - 'pyproject.toml'
      - 'Pipfile'
      - 'package.json'
      - 'Cargo.toml'
      - 'go.mod'
      - 'Gemfile'
      - 'pom.xml'
      - 'build.gradle'
      - 'composer.json'

jobs:
  slopcheck:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: 0xToxSec/slopcheck@main
        with:
          path: '.'
          fail-on: 'slop'
```

If slop is found, the action fails the check and drops a comment on the PR with the full report. Set `fail-on: 'sus'` to be stricter.

## License

MIT
