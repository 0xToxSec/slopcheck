"""CLI entry point. Zero config, blunt output."""

import argparse
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from slopcheck import __version__
from slopcheck import allowlist
from slopcheck.registries import REGISTRY_CHECKERS, PackageInfo
from slopcheck.detect import analyze, Verdict
from slopcheck.parsers import auto_detect, FILE_PARSERS
from slopcheck.fixer import fix_directory, fix_file


def _info(msg: str) -> None:
    """Status messages go to stderr so JSON stdout stays clean."""
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Colors (ANSI) -- vibe coders deserve pretty output
# ---------------------------------------------------------------------------

class C:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _status_badge(status: str) -> str:
    if status == "SLOP":
        return f"{C.RED}{C.BOLD}[SLOP]{C.RESET}"
    elif status == "SUS":
        return f"{C.YELLOW}{C.BOLD}[SUS]{C.RESET}"
    elif status == "ERROR":
        return f"{C.YELLOW}[ERR]{C.RESET}"
    else:
        return f"{C.GREEN}[OK]{C.RESET}"


def _severity_color(severity: str) -> str:
    if severity == "critical":
        return C.RED
    elif severity in ("warning", "error"):
        return C.YELLOW
    return C.DIM


def print_verdict(v: Verdict) -> None:
    """Print one package's verdict. Blunt. Single print call for thread safety."""
    badge = _status_badge(v.status)
    lines = [f"\n  {badge} {C.BOLD}{v.package}{C.RESET} {C.DIM}({v.ecosystem}){C.RESET}"]

    for flag in v.flags:
        color = _severity_color(flag.severity)
        lines.append(f"    {color}> {flag.message}{C.RESET}")

    if v.suggestion:
        lines.append(f"    {C.CYAN}? Did you mean: {C.BOLD}{v.suggestion}{C.RESET}")

    print("\n".join(lines))


def print_summary(verdicts: List[Verdict]) -> None:
    """Print final tally."""
    slop = sum(1 for v in verdicts if v.status == "SLOP")
    sus = sum(1 for v in verdicts if v.status == "SUS")
    errors = sum(1 for v in verdicts if v.status == "ERROR")
    ok = sum(1 for v in verdicts if v.status == "OK")
    total = len(verdicts)

    print(f"\n{'='*50}")
    print(f"  scanned {total} packages")
    if slop:
        print(f"  {C.RED}{C.BOLD}{slop} SLOP{C.RESET} -- hallucinated or dangerously new")
    if sus:
        print(f"  {C.YELLOW}{C.BOLD}{sus} SUS{C.RESET} -- worth a second look")
    if errors:
        print(f"  {C.YELLOW}{errors} ERROR{C.RESET} -- registry unreachable, could not verify")
    if ok:
        print(f"  {C.GREEN}{ok} OK{C.RESET}")
    print()


def _check_one(ecosystem: str, name: str) -> Verdict:
    """Check a single package against its registry and return a verdict."""
    checker = REGISTRY_CHECKERS.get(ecosystem)
    if not checker:
        info = PackageInfo(name=name, ecosystem=ecosystem, exists=False, error="unknown registry")
        return analyze(info)
    info = checker(name)
    return analyze(info)


def _scan_directory(directory: Path) -> List[Tuple[str, str]]:
    """Find and parse all dependency files in a directory."""
    deps = auto_detect(directory)
    if not deps:
        _info(f"{C.YELLOW}No dependency files found in {directory}{C.RESET}")
        _info(f"Looking for: {', '.join(FILE_PARSERS.keys())}")
        sys.exit(1)
    return deps


def _scan_file(filepath: Path) -> List[Tuple[str, str]]:
    """Parse a specific dependency file."""
    name = filepath.name
    parser = FILE_PARSERS.get(name)
    if not parser:
        if "requirements" in name and name.endswith(".txt"):
            from slopcheck.parsers import parse_requirements_txt
            parser = parse_requirements_txt
        else:
            _info(f"{C.RED}Don't know how to parse: {name}{C.RESET}")
            _info(f"Supported: {', '.join(FILE_PARSERS.keys())}")
            sys.exit(1)
    return parser(filepath)


def _check_packages(packages: List[Tuple[str, str]], workers: int = 10, json_output: bool = False) -> List[Verdict]:
    """Check a list of (ecosystem, name) pairs in parallel. Returns verdicts."""
    # Filter out allowlisted packages
    allowed = allowlist.load()
    if allowed:
        before = len(packages)
        packages = [(eco, name) for eco, name in packages if name.lower() not in allowed]
        skipped = before - len(packages)
        if skipped and not json_output:
            _info(f"  {C.DIM}skipped {skipped} allowlisted package(s){C.RESET}")

    verdicts: List[Verdict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_check_one, eco, name): (eco, name)
            for eco, name in packages
        }
        for future in as_completed(futures):
            verdict = future.result()
            verdicts.append(verdict)
            if not json_output:
                print_verdict(verdict)

    order = {"SLOP": 0, "SUS": 1, "ERROR": 2, "OK": 3}
    verdicts.sort(key=lambda v: order.get(v.status, 4))
    return verdicts


def _print_json(verdicts: List[Verdict]) -> None:
    """JSON output for CI integration."""
    import json
    output = []
    for v in verdicts:
        output.append({
            "package": v.package,
            "ecosystem": v.ecosystem,
            "status": v.status,
            "flags": [{"signal": f.signal, "severity": f.severity, "message": f.message} for f in v.flags],
            "suggestion": v.suggestion,
        })
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Package manager detection + install passthrough
# ---------------------------------------------------------------------------

# Map ecosystem to install commands
INSTALL_COMMANDS = {
    "pypi": ["pip", "install"],
    "npm": ["npm", "install"],
    "crates.io": ["cargo", "add"],
    "go": ["go", "get"],
    "rubygems": ["gem", "install"],
    "packagist": ["composer", "require"],
}

def _detect_ecosystem_from_env() -> str:
    """Look at what's in the current directory to guess ecosystem."""
    cwd = Path(".")
    if (cwd / "package.json").exists():
        return "npm"
    if (cwd / "Cargo.toml").exists():
        return "crates.io"
    if (cwd / "go.mod").exists():
        return "go"
    if (cwd / "Gemfile").exists():
        return "rubygems"
    if (cwd / "pom.xml").exists() or (cwd / "build.gradle").exists():
        return "maven"
    if (cwd / "composer.json").exists():
        return "packagist"
    # Default
    return "pypi"


def cmd_install(args) -> None:
    """Check packages, then install the clean ones."""
    packages = args.packages
    ecosystem = args.ecosystem or _detect_ecosystem_from_env()
    force = args.force

    if not packages:
        _info(f"{C.RED}No packages specified.{C.RESET}")
        _info(f"Usage: slopcheck install flask requests numpy")
        sys.exit(1)

    _info(f"\n{C.BOLD}slopcheck{C.RESET} checking {len(packages)} package(s) on {ecosystem} before install...\n")

    # Check all packages
    deps = [(ecosystem, pkg) for pkg in packages]
    verdicts = _check_packages(deps, workers=args.workers)

    # Separate clean from dirty
    clean = [v.package for v in verdicts if v.status == "OK"]
    sus = [v for v in verdicts if v.status == "SUS"]
    slop = [v for v in verdicts if v.status == "SLOP"]

    print_summary(verdicts)

    # Block on slop, always
    if slop:
        _info(f"  {C.RED}{C.BOLD}BLOCKED:{C.RESET} {len(slop)} package(s) are hallucinated or dangerous.")
        _info(f"  Refusing to install: {', '.join(v.package for v in slop)}")
        _info("")
        if not clean and not (sus and force):
            sys.exit(2)

    # Warn on sus, let through with --force
    if sus and not force:
        _info(f"  {C.YELLOW}{C.BOLD}WARNING:{C.RESET} {len(sus)} suspicious package(s) found.")
        _info(f"  Skipping: {', '.join(v.package for v in sus)}")
        _info(f"  Use {C.BOLD}--force{C.RESET} to install suspicious packages anyway.")
        _info("")

    # Build install list
    to_install = list(clean)
    if sus and force:
        to_install.extend(v.package for v in sus)

    if not to_install:
        _info(f"  {C.RED}Nothing safe to install.{C.RESET}")
        sys.exit(2)

    # Run the actual package manager
    install_cmd = INSTALL_COMMANDS.get(ecosystem)
    if not install_cmd:
        _info(f"{C.RED}Don't know how to install for: {ecosystem}{C.RESET}")
        sys.exit(1)

    full_cmd = install_cmd + to_install
    _info(f"  {C.GREEN}{C.BOLD}Installing:{C.RESET} {' '.join(to_install)}")
    _info(f"  {C.DIM}Running: {' '.join(full_cmd)}{C.RESET}\n")

    # Flush stdout before handing off to subprocess so output ordering
    # stays sane in piped/CI environments where Python full-buffers stdout.
    sys.stdout.flush()
    sys.stderr.flush()

    result = subprocess.run(full_cmd)
    sys.exit(result.returncode)


def cmd_scan(args) -> None:
    """Scan a directory or file for dependency issues."""
    # Single package check
    if args.pkg:
        _info(f"\n{C.BOLD}slopcheck{C.RESET} checking {args.target} on {args.pkg}...")
        verdict = _check_one(args.pkg, args.target)
        if args.json_output:
            _print_json([verdict])
        else:
            print_verdict(verdict)
            print()
        if verdict.status == "ERROR":
            _info(f"  {C.YELLOW}Could not reach registry. Verify your network connection.{C.RESET}")
            sys.exit(3)
        sys.exit(2 if verdict.status == "SLOP" else 1 if verdict.status == "SUS" else 0)

    # Scan file or directory
    target = Path(args.target)
    if target.is_file():
        deps = _scan_file(target)
        _info(f"\n{C.BOLD}slopcheck{C.RESET} scanning {target.name}...")
    else:
        deps = _scan_directory(target)
        _info(f"\n{C.BOLD}slopcheck{C.RESET} scanning {target.resolve()}...")

    deps = list(dict.fromkeys(deps))
    _info(f"  found {len(deps)} dependencies\n")

    verdicts = _check_packages(deps, workers=args.workers, json_output=args.json_output)

    if args.json_output:
        _print_json(verdicts)
    else:
        print_summary(verdicts)

    # --fix: remove SLOP packages from dependency files
    fix = getattr(args, "fix", False)
    if fix:
        slop_names = [v.package for v in verdicts if v.status == "SLOP"]
        if slop_names:
            if target.is_file():
                count = fix_file(target, slop_names)
                if count:
                    _info(f"  {C.GREEN}{C.BOLD}FIXED:{C.RESET} commented out {count} package(s) in {target.name}")
            else:
                fixed = fix_directory(target, slop_names)
                total = sum(fixed.values())
                if total:
                    for fname, count in fixed.items():
                        _info(f"  {C.GREEN}{C.BOLD}FIXED:{C.RESET} commented out {count} package(s) in {fname}")
                else:
                    _info(f"  {C.DIM}No files to fix (packages may be in lock files or JSON).{C.RESET}")
            _info("")

    has_errors = any(v.status == "ERROR" for v in verdicts)
    if has_errors:
        _info(f"  {C.YELLOW}Some packages could not be verified (registry unreachable).{C.RESET}")
        _info(f"  {C.DIM}Check your network connection and retry.{C.RESET}\n")

    if any(v.status == "SLOP" for v in verdicts):
        sys.exit(2)
    elif any(v.status == "SUS" for v in verdicts):
        sys.exit(1)
    elif has_errors:
        sys.exit(3)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Init: git pre-commit hook
# ---------------------------------------------------------------------------

HOOK_SCRIPT = """\
#!/bin/sh
# slopcheck pre-commit hook -- block commits that add hallucinated packages
# Installed by: slopcheck init

slopcheck .
STATUS=$?

if [ $STATUS -eq 2 ]; then
    echo ""
    echo "slopcheck: SLOP detected. Commit blocked."
    echo "Run 'slopcheck . --fix' to auto-remove bad packages, then try again."
    exit 1
fi

exit 0
"""


def cmd_init() -> None:
    """Drop a pre-commit hook into .git/hooks/."""
    git_dir = Path(".git")
    if not git_dir.is_dir():
        _info(f"{C.RED}Not a git repository. Run this from your project root.{C.RESET}")
        sys.exit(1)

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        existing = hook_path.read_text()
        if "slopcheck" in existing:
            _info(f"{C.GREEN}slopcheck hook already installed.{C.RESET}")
            sys.exit(0)
        # There's an existing hook that isn't ours. Append to it.
        _info(f"{C.YELLOW}Existing pre-commit hook found. Appending slopcheck check.{C.RESET}")
        with open(hook_path, "a") as f:
            f.write("\n\n# --- slopcheck (appended) ---\n")
            # Write just the check part, not the shebang
            f.write("\n".join(HOOK_SCRIPT.splitlines()[1:]) + "\n")
    else:
        hook_path.write_text(HOOK_SCRIPT)

    # Make it executable (no-op on Windows, needed on Unix)
    try:
        import stat
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
    except (OSError, AttributeError):
        pass

    _info(f"\n  {C.GREEN}{C.BOLD}Done.{C.RESET} slopcheck will run before every commit.")
    _info(f"  If slop is found, the commit is blocked.")
    _info(f"  Run {C.BOLD}slopcheck . --fix{C.RESET} to auto-clean your dependency files.\n")

    # Run an initial scan so the user sees their current state immediately
    _info(f"  {C.BOLD}Running initial scan...{C.RESET}\n")
    from slopcheck.parsers import auto_detect
    deps = auto_detect(Path("."))
    if deps:
        deps = list(set(deps))
        verdicts = _check_packages(deps)
        print_summary(verdicts)
    else:
        _info(f"  {C.DIM}No dependency files found yet. Hook is ready for when you add them.{C.RESET}\n")


# ---------------------------------------------------------------------------
# Allow: manage the .slopcheck allowlist
# ---------------------------------------------------------------------------

def cmd_allow(args) -> None:
    """Add or remove packages from the allowlist."""
    if args.remove:
        if not args.package:
            _info(f"{C.RED}Specify a package name to remove.{C.RESET}")
            _info(f"Usage: slopcheck allow my-pkg --remove")
            sys.exit(1)
        removed = allowlist.remove(args.package)
        if removed:
            _info(f"  {C.GREEN}Removed '{args.package}' from allowlist.{C.RESET}")
        else:
            _info(f"  {C.YELLOW}'{args.package}' not found in allowlist.{C.RESET}")
        return

    if args.list_all:
        allowed = allowlist.load()
        if not allowed:
            _info(f"  {C.DIM}Allowlist is empty.{C.RESET}")
            return
        _info(f"  {C.BOLD}Allowlisted packages:{C.RESET}")
        for name in sorted(allowed):
            _info(f"    {name}")
        return

    if not args.package:
        _info(f"{C.RED}Specify a package name.{C.RESET}")
        _info(f"Usage: slopcheck allow flask-internal")
        sys.exit(1)

    path = allowlist.add(args.package)
    _info(f"  {C.GREEN}Added '{args.package}' to {path}{C.RESET}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="slopcheck",
        description="Detect AI-hallucinated packages before you install them.",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"slopcheck {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- slopcheck install <packages> ---
    install_parser = subparsers.add_parser(
        "install",
        help="Check packages, then install the clean ones",
        description="Check packages against their registry, block slop, then install what's clean.",
    )
    install_parser.add_argument(
        "packages",
        nargs="*",
        help="Package names to check and install",
    )
    install_parser.add_argument(
        "--ecosystem", "-e",
        choices=["pypi", "npm", "crates.io", "go", "rubygems", "maven", "packagist"],
        default=None,
        help="Force ecosystem (auto-detected from project files by default)",
    )
    install_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Install suspicious packages anyway (slop is always blocked)",
    )
    install_parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Parallel workers (default: 10)",
    )

    # --- slopcheck scan (or just slopcheck .) ---
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan dependency files for hallucinated packages",
    )
    scan_parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Directory, file, or package name",
    )
    scan_parser.add_argument(
        "--pkg",
        metavar="ECOSYSTEM",
        choices=["pypi", "npm", "crates.io", "go", "rubygems", "maven", "packagist"],
        help="Check a single package",
    )
    scan_parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Parallel workers (default: 10)",
    )
    scan_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON output",
    )
    scan_parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-remove SLOP packages from dependency files",
    )

    # --- slopcheck init ---
    subparsers.add_parser(
        "init",
        help="Set up a git pre-commit hook that runs slopcheck before every commit",
        description="Drop a git pre-commit hook into .git/hooks/ so slopcheck runs automatically.",
    )

    # --- slopcheck allow <package> ---
    allow_parser = subparsers.add_parser(
        "allow",
        help="Add a package to the .slopcheck allowlist (skip it during scans)",
        description="Manage the .slopcheck allowlist. Allowlisted packages are skipped during scans.",
    )
    allow_parser.add_argument(
        "package",
        nargs="?",
        default=None,
        help="Package name to allowlist",
    )
    allow_parser.add_argument(
        "--remove", "-r",
        action="store_true",
        help="Remove a package from the allowlist",
    )
    allow_parser.add_argument(
        "--list", "-l",
        action="store_true",
        dest="list_all",
        help="List all allowlisted packages",
    )

    # Backwards compat: if first arg isn't a known subcommand, treat as scan
    known_commands = {"install", "scan", "init", "allow", "-h", "--help", "--version"}
    if len(sys.argv) > 1 and sys.argv[1] not in known_commands:
        # Inject "scan" so argparse routes correctly
        # slopcheck . -> slopcheck scan .
        # slopcheck requirements.txt -> slopcheck scan requirements.txt
        # slopcheck flask --pkg pypi -> slopcheck scan flask --pkg pypi
        # slopcheck --json . -> slopcheck scan --json .
        sys.argv.insert(1, "scan")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "init":
        cmd_init()
    elif args.command == "allow":
        cmd_allow(args)
    else:
        # No args at all = scan current dir
        scan_args = scan_parser.parse_args(["."])
        cmd_scan(scan_args)


if __name__ == "__main__":
    main()
