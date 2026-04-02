#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

ASSET_REPO = Path("/Users/dm/Documents/Projects/goodcigars-assets")
APP_REPO = Path("/Users/dm/Documents/Projects/GoodCigars")
FIXTURE_PATH = APP_REPO / "GoodCigarsApp/Resources/CatalogFixtures/goodcigarscatalog.json"
PRIVATE_MAP_PATH = APP_REPO / "GoodCigarsApp/Resources/CatalogFixtures/catalog-image-token-map.json"
PUBLIC_TOKEN_INDEX_PATH = ASSET_REPO / "catalog-token-index.json"
FAILURE_PATH = ASSET_REPO / "tokenize-failures.json"
CATALOG_DIR = ASSET_REPO / "catalog"
BASE_URL = "https://integrationuser92.github.io/goodcigars-assets/catalog"
USER_AGENT = "Mozilla/5.0"

DIRECT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def run_curl(args: list[str], text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--retry",
            "2",
            "--retry-all-errors",
            "--retry-delay",
            "1",
            "--max-time",
            "30",
            "--user-agent",
            USER_AGENT,
            *args,
        ],
        capture_output=True,
        text=text,
        check=False,
    )


def parse_catalog_id(catalog_id: str) -> tuple[str, str]:
    parts = catalog_id.split("-")
    if len(parts) < 3:
        raise ValueError(f"Unexpected catalog_id format: {catalog_id}")
    return parts[-2], parts[-1]


def sort_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)


def extension_from_url(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in DIRECT_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def find_existing_asset(catalog_id: str) -> Path | None:
    for ext in DIRECT_EXTENSIONS:
        candidate = CATALOG_DIR / f"{catalog_id}{'.jpg' if ext == '.jpeg' else ext}"
        if candidate.exists():
            return candidate
    return None


def fetch_source_html(source_url: str) -> str:
    last_html = ""
    for _ in range(3):
        result = run_curl([source_url])
        if result.returncode == 0 and result.stdout:
            return result.stdout
        last_html = result.stdout
        time.sleep(1)
    return last_html


def extract_fallback_image_url(source_url: str) -> str | None:
    html = fetch_source_html(source_url)
    og_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if og_match:
        return og_match.group(1)

    ld_match = re.search(r'"image"\s*:\s*"([^"]+)"', html)
    if ld_match:
        return ld_match.group(1)

    path_match = re.search(r'(/bilder/detail/(?:big2048|big)/[^"\']+)', html)
    if path_match:
        return urllib.parse.urljoin(source_url, path_match.group(1))
    return None


def download_image(url: str, destination: Path) -> bool:
    result = run_curl(["--fail", "--output", str(destination), url], text=True)
    return result.returncode == 0 and destination.exists() and destination.stat().st_size > 0


def ensure_asset(row: dict, temp_dir: Path, final_path: Path) -> tuple[Path, str]:
    if final_path.exists():
        return final_path, row["catalog_image_url"]

    existing = find_existing_asset(row["catalog_id"])
    if existing:
        return existing, row["catalog_image_url"]

    direct_url = row["catalog_image_url"]
    temp_path = temp_dir / f"{row['catalog_id']}{extension_from_url(direct_url)}"
    if download_image(direct_url, temp_path):
        return temp_path, direct_url

    fallback_url = extract_fallback_image_url(row["source_url"])
    if fallback_url is None:
        raise RuntimeError(f"No fallback image found for {row['catalog_id']}")

    fallback_path = temp_dir / f"{row['catalog_id']}{extension_from_url(fallback_url)}"
    if download_image(fallback_url, fallback_path):
        return fallback_path, fallback_url

    raise RuntimeError(f"Failed to download fallback image for {row['catalog_id']}")


def load_rows() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())["cigars"]


def assign_tokens(rows: list[dict]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    brand_codes = sorted({parse_catalog_id(row["catalog_id"])[0] for row in rows}, key=sort_key)
    brand_tokens = {brand_code: f"b{index:04d}" for index, brand_code in enumerate(brand_codes, start=1)}

    per_brand_sticks: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        brand_code, stick_code = parse_catalog_id(row["catalog_id"])
        per_brand_sticks[brand_code].append(stick_code)

    cigar_tokens: dict[str, tuple[str, str]] = {}
    for brand_code, stick_codes in per_brand_sticks.items():
        ordered = sorted(set(stick_codes), key=sort_key)
        for index, stick_code in enumerate(ordered, start=1):
            cigar_tokens[f"{brand_code}:{stick_code}"] = (brand_tokens[brand_code], f"s{index:04d}")

    return brand_tokens, cigar_tokens


def main() -> int:
    rows = load_rows()
    brand_tokens, cigar_tokens = assign_tokens(rows)
    temp_dir = ASSET_REPO / ".tmp-tokenize"
    temp_dir.mkdir(exist_ok=True)

    private_map: list[dict] = []
    public_index: list[dict] = []
    updated_rows: list[dict] = []
    failures: list[dict] = []
    final_paths: set[Path] = set()

    for position, row in enumerate(rows, start=1):
        brand_code, stick_code = parse_catalog_id(row["catalog_id"])
        brand_token, cigar_token = cigar_tokens[f"{brand_code}:{stick_code}"]
        final_filename = f"{brand_token}-{cigar_token}"

        try:
            existing_final = None
            for ext in DIRECT_EXTENSIONS:
                candidate = CATALOG_DIR / f"{final_filename}{'.jpg' if ext == '.jpeg' else ext}"
                if candidate.exists():
                    existing_final = candidate
                    break
            source_path, resolved_url = ensure_asset(
                row,
                temp_dir,
                existing_final or (CATALOG_DIR / f"{final_filename}{extension_from_url(row['catalog_image_url'])}")
            )
        except Exception as exc:
            failures.append({"catalog_id": row["catalog_id"], "error": str(exc)})
            continue

        ext = source_path.suffix.lower()
        filename = f"{final_filename}{ext}"
        final_path = CATALOG_DIR / filename
        final_paths.add(final_path)
        if source_path != final_path:
            if final_path.exists():
                final_path.unlink()
            shutil.move(str(source_path), str(final_path))

        hosted_url = f"{BASE_URL}/{filename}"
        updated_row = dict(row)
        updated_row["catalog_image_url"] = hosted_url
        updated_rows.append(updated_row)

        private_map.append({
            "catalog_id": row["catalog_id"],
            "brand": row["brand"],
            "name": row["name"],
            "brand_code": brand_code,
            "stick_code": stick_code,
            "brand_token": brand_token,
            "cigar_token": cigar_token,
            "asset_filename": filename,
            "hosted_url": hosted_url,
            "resolved_source_image_url": resolved_url,
        })
        public_index.append({
            "brand_token": brand_token,
            "cigar_token": cigar_token,
            "asset_filename": filename,
            "hosted_url": hosted_url,
        })

        if position % 250 == 0 or position == len(rows):
            print(f"processed={position}/{len(rows)} failures={len(failures)}", flush=True)

    if failures:
        FAILURE_PATH.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"failures": failures[:10], "failure_count": len(failures)}, indent=2))
        return 1

    for path in CATALOG_DIR.iterdir():
        if path.is_file() and path not in final_paths:
            path.unlink()

    FIXTURE_PATH.write_text(json.dumps({"cigars": updated_rows}, indent=2) + "\n", encoding="utf-8")
    PRIVATE_MAP_PATH.write_text(json.dumps({"base_url": BASE_URL, "images": private_map}, indent=2) + "\n", encoding="utf-8")
    PUBLIC_TOKEN_INDEX_PATH.write_text(json.dumps({"base_url": BASE_URL, "images": public_index}, indent=2) + "\n", encoding="utf-8")

    for public_artifact in ("catalog-index.json", "retry-failures.json", "download-report.json"):
        artifact_path = ASSET_REPO / public_artifact
        if artifact_path.exists():
            artifact_path.unlink()
    if FAILURE_PATH.exists():
        FAILURE_PATH.unlink()

    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    print(json.dumps({
        "rows": len(rows),
        "brand_tokens": len(brand_tokens),
        "tokenized_images": len(public_index),
        "fixture": str(FIXTURE_PATH),
        "private_map": str(PRIVATE_MAP_PATH),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
