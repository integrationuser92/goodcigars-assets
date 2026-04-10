#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_REPO = Path("/Users/dm/Documents/Projects/GoodCigars")
FIXTURE_PATH = APP_REPO / "GoodCigarsApp/Resources/CatalogFixtures/goodcigarscatalog.json"
CATALOG_OUTPUT_PATH = REPO_ROOT / "catalog.json"
INDEX_OUTPUT_PATH = REPO_ROOT / "catalog-index.json"
CATALOG_URL = "https://integrationuser92.github.io/goodc-assets/catalog.json"
ASSET_BASE_URL = "https://integrationuser92.github.io/goodc-assets/catalog/"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def validate_fixture(payload: dict) -> None:
    cigars = payload.get("cigars")
    if not isinstance(cigars, list) or not cigars:
        raise ValueError("Fixture must contain a non-empty cigars array.")

    for cigar in cigars:
        image_url = cigar.get("catalog_image_url")
        if not isinstance(image_url, str) or not image_url.startswith(ASSET_BASE_URL):
            raise ValueError(f"Fixture contains a non-hosted catalog image URL: {image_url!r}")
        validate_asset(image_url)


def asset_path_for(image_url: str) -> Path:
    parsed = urlparse(image_url)
    asset_name = Path(parsed.path).name
    if not asset_name:
        raise ValueError(f"Fixture contains an invalid catalog image URL: {image_url!r}")
    return REPO_ROOT / "catalog" / asset_name


def dimensions_for(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"sips query failed for {path.name}")

    width = None
    height = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            width = int(line.split(":", maxsplit=1)[1].strip())
        elif line.startswith("pixelHeight:"):
            height = int(line.split(":", maxsplit=1)[1].strip())

    if width is None or height is None:
        raise ValueError(f"Missing dimensions for {path.name}")
    return width, height


def validate_asset(image_url: str) -> None:
    asset_path = asset_path_for(image_url)
    if not asset_path.is_file():
        raise ValueError(f"Missing catalog asset for fixture URL: {image_url}")

    width, height = dimensions_for(asset_path)
    if width > height:
        raise ValueError(f"Catalog asset is still landscape: {asset_path.name} ({width}x{height})")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    payload = load_fixture()
    validate_fixture(payload)
    write_json(CATALOG_OUTPUT_PATH, payload)

    catalog_bytes = CATALOG_OUTPUT_PATH.read_bytes()
    version = os.environ.get("CATALOG_VERSION") or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    index_payload = {
        "version": version,
        "catalog_url": CATALOG_URL,
        "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
    }
    write_json(INDEX_OUTPUT_PATH, index_payload)
    print(json.dumps(index_payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
