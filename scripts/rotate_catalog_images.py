#!/usr/bin/env python3
import concurrent.futures
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"
SUPPORTED_EXTENSIONS = {".jpg", ".png"}
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))


def list_images() -> list[Path]:
    return sorted(
        path for path in CATALOG_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def dimensions_for(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"sips query failed for {path.name}")

    width = None
    height = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            width = int(line.split(":", maxsplit=1)[1].strip())
        elif line.startswith("pixelHeight:"):
            height = int(line.split(":", maxsplit=1)[1].strip())

    if width is None or height is None:
        raise RuntimeError(f"missing dimensions for {path.name}")
    return width, height


def classify(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if width < height:
        return "portrait"
    return "square"


def rotate_clockwise(path: Path) -> None:
    result = subprocess.run(
        ["sips", "-r", "90", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"sips rotate failed for {path.name}")


def process_image(path: Path) -> dict[str, str]:
    width, height = dimensions_for(path)
    before = classify(width, height)

    if before == "landscape":
        rotate_clockwise(path)
        width, height = dimensions_for(path)

    after = classify(width, height)
    if after == "landscape":
        raise RuntimeError(f"{path.name} is still landscape after rotation")

    return {
        "file": path.name,
        "before": before,
        "after": after,
    }


def main() -> int:
    images = list_images()
    if not images:
        print("No catalog images found.", file=sys.stderr)
        return 1

    before_counts: Counter[str] = Counter()
    after_counts: Counter[str] = Counter()
    failures: list[dict[str, str]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(process_image, path): path for path in images}
        completed = 0
        for future in concurrent.futures.as_completed(future_map):
            completed += 1
            path = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                failures.append({"file": path.name, "error": str(exc)})
            else:
                before_counts[result["before"]] += 1
                after_counts[result["after"]] += 1

            if completed % 250 == 0 or completed == len(images):
                print(
                    f"processed={completed}/{len(images)} failures={len(failures)}",
                    flush=True,
                )

    summary = {
        "images": len(images),
        "before": dict(sorted(before_counts.items())),
        "after": dict(sorted(after_counts.items())),
        "failures": failures[:10],
        "failure_count": len(failures),
    }
    print(json.dumps(summary, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
