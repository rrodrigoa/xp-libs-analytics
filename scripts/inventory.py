"""Record resolved versions, license metadata, dependency constraints and a CycloneDX BOM."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from uuid import uuid4


def main() -> None:
    inventory = []
    constraints = []
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name, version = dist.metadata["Name"], dist.version
        if name == "xp-libs-analytics":
            continue
        license_name = dist.metadata.get("License-Expression", "")
        if not license_name:
            classifiers = dist.metadata.get_all("Classifier", [])
            license_name = next(
                (s.split(" :: ")[-1] for s in classifiers if s.startswith("License ::")), ""
            )
        if not license_name:
            license_name = dist.metadata.get("License", "Unspecified in metadata").splitlines()[0][
                :200
            ]
        inventory.append({"name": name, "version": version, "license_metadata": license_name})
        marker = (
            "; sys_platform == 'win32'"
            if name.lower() in {"pywin32", "pywin32-ctypes", "tzdata"}
            else ""
        )
        constraints.append(f"{name}=={version}{marker}")
    Path("requirements-lock.txt").write_text(
        "# Resolved development + MCP constraints; Windows-only dependencies are marked.\n"
        + "\n".join(constraints)
        + "\n"
    )
    evidence = Path("docs/evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "dependencies.json").write_text(json.dumps(inventory, indent=2) + "\n")
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:" + str(uuid4()),
        "version": 1,
        "metadata": {"timestamp": datetime.now(UTC).isoformat()},
        "components": [
            {
                "type": "library",
                "name": row["name"],
                "version": row["version"],
                "purl": f"pkg:pypi/{row['name'].lower()}@{row['version']}",
            }
            for row in inventory
        ],
    }
    (evidence / "sbom.json").write_text(json.dumps(bom, indent=2) + "\n")
    notice = (
        "# Third-party notices\n\nOriginal project code and documentation are MIT licensed "
        "(see LICENSE). Dependencies retain their own licenses. This inventory covers the "
        "complete local development/MCP environment, including optional and test tools; "
        "a core-only install has fewer dependencies. "
        "License values below are installed distribution metadata, not legal conclusions. "
        "Dependency license texts remain in the distributions' `.dist-info/licenses` "
        "or upstream source distributions. Vendored code is not copied into this product.\n\n"
        "Polars, Pydantic and RapidFuzz use MIT; PyYAML uses MIT; FastMCP uses Apache-2.0. "
        "Preserve the relevant license and NOTICE files if redistributing those dependencies. "
        "RapidFuzz attribution: Max Bachmann and Adam Cohen; its full MIT license remains "
        "in the dependency distribution. The CycloneDX BOM and version inventory are "
        "under docs/evidence.\n\n"
        "| Distribution | Version | License metadata |\n|---|---|---|\n"
    )
    notice += "".join(
        f"| {r['name']} | {r['version']} | {r['license_metadata'].replace('|', '/')} |\n"
        for r in inventory
    )
    Path("THIRD_PARTY_NOTICES.md").write_text(notice, encoding="utf-8")


if __name__ == "__main__":
    main()
