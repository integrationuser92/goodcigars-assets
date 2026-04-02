#!/usr/bin/env python3
import concurrent.futures
import json
import re
import subprocess
import sys
import threading
import urllib.parse
from collections import Counter
from pathlib import Path

SOURCE_FIXTURE = Path("/Users/dm/Documents/Projects/GoodCigars/GoodCigarsApp/Resources/CatalogFixtures/goodcigarscatalog.json")
REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"
INDEX_PATH = REPO_ROOT / "catalog-index.json"
REPORT_PATH = REPO_ROOT / "download-report.json"

USER_AGENT = "GoodCigarsAssetsDownloader/1.0"
MAX_WORKERS = 12
TIMEOUT_SECONDS = 30

PRINT_LOCK = threading.Lock()


def safe_print(*parts):
    with PRINT_LOCK:
        print(*parts, flush=True)


def load_rows():
    with SOURCE_FIXTURE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["cigars"]


def extension_for(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "item"


def target_name(row: dict) -> str:
    ext = extension_for(row["catalog_image_url"])
    return f'{row["catalog_id"]}{ext}'


def download_row(row: dict) -> dict:
    url = row["catalog_image_url"]
    filename = target_name(row)
    target_path = CATALOG_DIR / filename
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--fail",
        "--location",
        "--max-time",
        str(TIMEOUT_SECONDS),
        "--user-agent",
        USER_AGENT,
        "--output",
        str(target_path),
        url,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return {"catalog_id": row["catalog_id"], "url": url, "status": "error", "error": result.stderr.strip() or f"curl_{result.returncode}"}

    return {
        "catalog_id": row["catalog_id"],
        "url": url,
        "status": "ok",
        "bytes": target_path.stat().st_size,
        "path": f"catalog/{filename}",
    }


def main() -> int:
    rows = load_rows()
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    safe_print(f"rows={len(rows)}")
    results = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(download_row, row): row for row in rows}
        for future in concurrent.futures.as_completed(future_map):
            result = future.result()
            results.append(result)
            completed += 1
            if completed % 250 == 0 or completed == len(rows):
                counts = Counter(item["status"] for item in results)
                safe_print(f"completed={completed}/{len(rows)} ok={counts.get('ok', 0)} error={counts.get('error', 0)}")

    results.sort(key=lambda item: str(item["catalog_id"]))
    INDEX_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary = {
        "rows": len(rows),
        "ok": sum(1 for item in results if item["status"] == "ok"),
        "error": sum(1 for item in results if item["status"] == "error"),
        "total_bytes": sum(item.get("bytes", 0) for item in results),
    }
    REPORT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    safe_print(json.dumps(summary, indent=2))
    return 0 if summary["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
