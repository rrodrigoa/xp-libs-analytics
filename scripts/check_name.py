"""Check index presence; this does not reserve names or assert ownership."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def main():
    results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "distribution": "xp-libs-analytics",
        "indexes": {},
    }
    for host in ("pypi.org", "test.pypi.org"):
        try:
            with urlopen(f"https://{host}/pypi/xp-libs-analytics/json", timeout=20) as response:  # noqa: S310 -- fixed HTTPS index hosts
                status = response.status
        except HTTPError as exc:
            status = exc.code
        except URLError:
            status = "unreachable"
        results["indexes"][host] = status
    path = Path("docs/evidence/index-presence.json")
    path.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
