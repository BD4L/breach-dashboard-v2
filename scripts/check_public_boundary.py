"""Fail the build on production coupling or obvious privileged/public-data leaks.

This enforces the pilot's narrow contract; it is not a general secret scanner or
an authorization test for a future backend.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "production database reference": re.compile(r"supabase\.co", re.I),
    "GitHub API in public app": re.compile(r"api\.github\.com", re.I),
    "public administrative token": re.compile(r"PUBLIC_GITHUB_TOKEN|SUPABASE_SERVICE|SERVICE_ROLE_KEY"),
    "credential literal": re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{20,})"),
    "original app reference": re.compile(r"HackerManMarlin|BD4L/Breaches\b|bd4l\.github\.io/Breaches\b|[\"']/Breaches/", re.I),
}
PRIVATE_KEYS = {"notes", "assigned_to", "assignedto", "user_id", "userid", "email", "subscribers", "access_token", "refresh_token"}


def main():
    errors = []
    for directory in [ROOT / "frontend/src", ROOT / "frontend/public", ROOT / "frontend/dist"]:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".ts", ".tsx", ".js", ".astro", ".html", ".json", ".css"}:
                continue
            text = path.read_text(errors="replace")
            for label, pattern in PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"{path.relative_to(ROOT)}: {label}")
    data_path = ROOT / "frontend/public/data/dashboard.json"
    if not data_path.exists():
        errors.append("Missing dashboard export")
    else:
        data = json.loads(data_path.read_text())
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in PRIVATE_KEYS:
                        errors.append(f"Private field in public export: {key}")
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(data)
        if data.get("schemaVersion") != 1 or data.get("mode") not in {"demo", "live"}:
            errors.append("Invalid dashboard schema/mode")
        for report in data.get("reports", []):
            for field in ["sourceUrl", "noticeUrl"]:
                value = report.get(field)
                if value:
                    parsed = urlsplit(value)
                    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                        errors.append(f"Unsafe {field} in public export")
        if data_path.stat().st_size > 30_000_000:
            errors.append("Public export exceeds its 30 MB budget")
    built = ROOT / "frontend/dist"
    if built.exists():
        total = sum(path.stat().st_size for path in built.rglob("*") if path.is_file())
        if total > 50_000_000:
            errors.append("Static site exceeds its 50 MB budget")
    if errors:
        print("Public boundary check failed:")
        print("\n".join(sorted(set(errors))))
        return 1
    print("Public boundary check passed: no production coupling or private fields; size budgets respected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
