"""Read-only smoke checks for an already running SecureRAG deployment."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path.rstrip("/")
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        parser.error("--base-url must be an HTTP(S) origin without credentials, query or path")
    base = args.base_url.rstrip("/")
    result = {}
    for path, expected in [
        ("/", 200),
        ("/api/v1/health", 200),
        ("/api/v1/health/ready", 200),
        ("/api/v1/auth/me", 401),
        ("/api/v1/admin/options", 401),
        ("/api/v1/documents", 401),
        ("/api/v1/conversations", 401),
    ]:
        try:
            try:
                response = urlopen(base + path, timeout=20)
            except HTTPError as error:
                response = error
            with response:
                status = response.status
                headers = response.headers
                checks = {
                    "status": status,
                    "expected_status": expected,
                    "passed": status == expected,
                }
                if path == "/":
                    checks["security_headers"] = (
                        headers.get("X-Content-Type-Options") == "nosniff"
                        and headers.get("X-Frame-Options") == "DENY"
                        and not headers.get("X-Powered-By")
                    )
                    checks["passed"] = checks["passed"] and checks["security_headers"]
                else:
                    checks["no_store"] = headers.get("Cache-Control") == "no-store"
                    checks["passed"] = checks["passed"] and checks["no_store"]
                result[path] = checks
        except (URLError, TimeoutError, OSError) as error:
            result[path] = {"passed": False, "error_type": type(error).__name__}
    payload = {
        "base_url": base,
        "passed": all(item["passed"] for item in result.values()),
        "checks": result,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
