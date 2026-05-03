from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError as error:
    print("Pillow is required. Install it with: pip install Pillow")
    raise SystemExit(1) from error


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "data" / "vocab_seed.csv"
IMAGE_WORDS_PATH = REPO_ROOT / "data" / "image_words.json"
REPORT_PATH = REPO_ROOT / "download_report.json"
RAW_ROOT = REPO_ROOT / "images" / "raw"
APPROVED_ROOT = REPO_ROOT / "images" / "approved"
SUPPORTED_PROVIDERS = ("pexels", "pixabay")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

PROVIDER_LABELS = {
    "pexels": "Pexels",
    "pixabay": "Pixabay",
}

PROVIDER_LICENSES = {
    "pexels": "Pexels License",
    "pixabay": "Pixabay Content License",
}

CATEGORY_HINTS = {
    "airport": "This is related to airport travel.",
    "hotel": "This is related to staying at a hotel.",
    "office": "This is related to office work.",
    "retail": "This is related to shopping or store operations.",
    "warehouse": "This is related to warehouse or shipping work.",
}


@dataclass(frozen=True)
class SeedRecord:
    word: str
    category: str
    query: str
    level: int


@dataclass
class CandidateRecord:
    word: str
    category: str
    query: str
    provider: str
    provider_id: str
    source: str
    sourceUrl: str
    photographer: str
    license: str
    downloadUrl: str
    imagePath: str = ""
    sidecarPath: str = ""
    sha256: str = ""
    width: int | None = None
    height: int | None = None


@dataclass
class ApprovedAsset:
    image_path: Path
    sidecar_path: Path
    metadata: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download licensed images from official APIs and sync approved assets into image_words.json."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download candidate images into images/raw/.")
    download_parser.add_argument("--seed-file", default=str(SEED_PATH), help="Path to vocab_seed.csv")
    download_parser.add_argument("--providers", default="pexels,pixabay", help="Comma-separated provider priority list")
    download_parser.add_argument("--per-seed", type=int, default=3, help="Number of candidate images to save per seed word")
    download_parser.add_argument("--delay", type=float, default=0.4, help="Delay between seed queries in seconds")
    download_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing raw candidates with the same provider id")
    download_parser.add_argument("--max-seeds", type=int, default=0, help="Optional limit for testing smaller batches")

    sync_parser = subparsers.add_parser("sync", help="Rename approved assets and generate data/image_words.json.")
    sync_parser.add_argument("--seed-file", default=str(SEED_PATH), help="Path to vocab_seed.csv")
    sync_parser.add_argument("--dry-run", action="store_true", help="Preview sync actions without writing files")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.command == "download":
        return run_download(args)

    if args.command == "sync":
        return run_sync(args)

    print(f"Unsupported command: {args.command}")
    return 1


def run_download(args: argparse.Namespace) -> int:
    seed_records = load_seed_records(Path(args.seed_file))
    if args.max_seeds > 0:
        seed_records = seed_records[: args.max_seeds]

    env_values = load_env_file(REPO_ROOT / ".env")
    api_keys = {
        "pexels": os.environ.get("PEXELS_API_KEY") or env_values.get("PEXELS_API_KEY", ""),
        "pixabay": os.environ.get("PIXABAY_API_KEY") or env_values.get("PIXABAY_API_KEY", ""),
    }
    provider_order = normalize_provider_list(args.providers)
    active_providers = [provider for provider in provider_order if api_keys.get(provider)]
    report = load_report()

    if not active_providers:
        reason = "No API keys found. Set PEXELS_API_KEY or PIXABAY_API_KEY in the environment or .env."
        report["generatedAt"] = iso_now()
        report["failures"] = [{"type": "configuration", "message": reason}]
        report["missing"] = []
        report["duplicates"] = []
        report["downloads"] = []
        report["summary"] = build_summary(report)
        write_json(REPORT_PATH, report)
        print(reason)
        return 1

    seen_hashes = collect_known_hashes(report)
    downloads: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    for index, seed in enumerate(seed_records, start=1):
        saved_count = 0
        print(f"[{index}/{len(seed_records)}] {seed.category} :: {seed.word}")

        for provider in active_providers:
            try:
                candidates = search_provider(provider, seed, api_keys[provider], args.per_seed)
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                failures.append(
                    {
                        "word": seed.word,
                        "category": seed.category,
                        "query": seed.query,
                        "provider": provider,
                        "message": str(error),
                    }
                )
                continue

            for candidate in candidates:
                try:
                    jpeg_bytes = fetch_as_jpeg(candidate.downloadUrl)
                except (HTTPError, URLError, TimeoutError, UnidentifiedImageError, OSError, ValueError) as error:
                    failures.append(
                        {
                            "word": seed.word,
                            "category": seed.category,
                            "query": seed.query,
                            "provider": provider,
                            "providerId": candidate.provider_id,
                            "message": str(error),
                        }
                    )
                    continue

                digest = hashlib.sha256(jpeg_bytes).hexdigest()
                if digest in seen_hashes:
                    duplicates.append(
                        {
                            "word": seed.word,
                            "category": seed.category,
                            "query": seed.query,
                            "provider": provider,
                            "providerId": candidate.provider_id,
                            "duplicateOf": seen_hashes[digest],
                        }
                    )
                    continue

                image_path, sidecar_path = persist_candidate(candidate, jpeg_bytes, digest, args.overwrite)
                seen_hashes[digest] = image_path.as_posix()
                downloads.append(
                    {
                        **asdict(candidate),
                        "imagePath": to_repo_relative(image_path),
                        "sidecarPath": to_repo_relative(sidecar_path),
                        "sha256": digest,
                    }
                )
                saved_count += 1

                if saved_count >= args.per_seed:
                    break

            if saved_count >= args.per_seed:
                break

        if saved_count == 0:
            missing.append(
                {
                    "word": seed.word,
                    "category": seed.category,
                    "query": seed.query,
                    "reason": "No downloadable results found from the configured providers.",
                }
            )

        if args.delay > 0 and index < len(seed_records):
            time.sleep(args.delay)

    report["generatedAt"] = iso_now()
    report["downloads"] = downloads
    report["failures"] = failures
    report["missing"] = missing
    report["duplicates"] = duplicates
    report["summary"] = build_summary(report)
    write_json(REPORT_PATH, report)

    print(
        "Downloaded {downloads_count} candidate images, {missing_count} missing queries, {failure_count} failures, {duplicate_count} duplicates.".format(
            downloads_count=len(downloads),
            missing_count=len(missing),
            failure_count=len(failures),
            duplicate_count=len(duplicates),
        )
    )
    return 0 if downloads else 1


def run_sync(args: argparse.Namespace) -> int:
    seed_records = load_seed_records(Path(args.seed_file))
    report = load_report()
    approved_assets, sync_failures = discover_approved_assets()

    if not approved_assets:
        print("No approved images with sidecar metadata were found under images/approved/. image_words.json was left unchanged.")
        report["generatedAt"] = iso_now()
        report["approved"] = []
        report["summary"] = build_summary(report)
        write_json(REPORT_PATH, report)
        return 1

    entries: list[dict[str, Any]] = []
    approved_records: list[dict[str, Any]] = []
    category_indexes = build_category_indexes(seed_records)

    for seed in seed_records:
        asset = approved_assets.get((seed.category, seed.word))
        if asset is None:
            continue

        ordinal = category_indexes[(seed.category, seed.word)]
        target_stem = f"{seed.category}_{ordinal:03d}_{slugify(seed.word)}"
        target_dir = APPROVED_ROOT / seed.category
        target_image = target_dir / f"{target_stem}.jpg"
        target_sidecar = target_dir / f"{target_stem}.json"

        metadata = dict(asset.metadata)
        metadata["approvedId"] = target_stem
        metadata["approvedImagePath"] = f"images/approved/{seed.category}/{target_stem}.jpg"

        if not args.dry_run:
            convert_to_jpeg(asset.image_path, target_image)
            if asset.image_path.resolve() != target_image.resolve() and asset.image_path.exists():
                asset.image_path.unlink()

            write_json(target_sidecar, metadata)
            if asset.sidecar_path.resolve() != target_sidecar.resolve() and asset.sidecar_path.exists():
                asset.sidecar_path.unlink()

        approved_records.append(
            {
                "word": seed.word,
                "category": seed.category,
                "id": target_stem,
                "image": f"images/approved/{seed.category}/{target_stem}.jpg",
                "source": metadata.get("source", ""),
                "sourceUrl": metadata.get("sourceUrl", ""),
                "photographer": metadata.get("photographer", ""),
                "license": metadata.get("license", ""),
            }
        )
        entries.append(build_image_word_entry(seed, target_stem, metadata, seed_records))

    if not entries:
        print("Approved assets exist, but none matched the words in vocab_seed.csv.")
        return 1

    if not args.dry_run:
        write_json(IMAGE_WORDS_PATH, entries)

    report["generatedAt"] = iso_now()
    report["approved"] = approved_records
    report["failures"] = report.get("failures", []) + sync_failures
    report["summary"] = build_summary(report, synced_entries=len(entries))
    write_json(REPORT_PATH, report)

    action = "Would sync" if args.dry_run else "Synced"
    print(f"{action} {len(entries)} approved images into data/image_words.json.")
    return 0


def search_provider(provider: str, seed: SeedRecord, api_key: str, per_seed: int) -> list[CandidateRecord]:
    if provider == "pexels":
        return search_pexels(seed, api_key, per_seed)
    if provider == "pixabay":
        return search_pixabay(seed, api_key, per_seed)
    raise ValueError(f"Unsupported provider: {provider}")


def search_pexels(seed: SeedRecord, api_key: str, per_seed: int) -> list[CandidateRecord]:
    params = urlencode(
        {
            "query": seed.query,
            "per_page": max(per_seed * 2, 5),
            "orientation": "landscape",
            "size": "large",
        }
    )
    request = Request(
        f"https://api.pexels.com/v1/search?{params}",
        headers={"Authorization": api_key, "User-Agent": "picture-vocab-trainer/1.0"},
    )
    payload = read_json_response(request)
    photos = payload.get("photos", [])
    results: list[CandidateRecord] = []

    for photo in photos:
        src = photo.get("src", {})
        download_url = src.get("large2x") or src.get("large") or src.get("original")
        if not download_url:
            continue

        results.append(
            CandidateRecord(
                word=seed.word,
                category=seed.category,
                query=seed.query,
                provider="pexels",
                provider_id=str(photo.get("id", "")),
                source=PROVIDER_LABELS["pexels"],
                sourceUrl=str(photo.get("url", "")),
                photographer=str(photo.get("photographer", "")),
                license=PROVIDER_LICENSES["pexels"],
                downloadUrl=str(download_url),
                width=coerce_int(photo.get("width")),
                height=coerce_int(photo.get("height")),
            )
        )

    return results


def search_pixabay(seed: SeedRecord, api_key: str, per_seed: int) -> list[CandidateRecord]:
    params = urlencode(
        {
            "key": api_key,
            "q": seed.query,
            "image_type": "photo",
            "orientation": "horizontal",
            "safesearch": "true",
            "per_page": max(per_seed * 2, 5),
        }
    )
    request = Request(
        f"https://pixabay.com/api/?{params}",
        headers={"User-Agent": "picture-vocab-trainer/1.0"},
    )
    payload = read_json_response(request)
    photos = payload.get("hits", [])
    results: list[CandidateRecord] = []

    for photo in photos:
        download_url = photo.get("fullHDURL") or photo.get("largeImageURL") or photo.get("imageURL")
        if not download_url:
            continue

        results.append(
            CandidateRecord(
                word=seed.word,
                category=seed.category,
                query=seed.query,
                provider="pixabay",
                provider_id=str(photo.get("id", "")),
                source=PROVIDER_LABELS["pixabay"],
                sourceUrl=str(photo.get("pageURL", "")),
                photographer=str(photo.get("user", "")),
                license=PROVIDER_LICENSES["pixabay"],
                downloadUrl=str(download_url),
                width=coerce_int(photo.get("imageWidth")),
                height=coerce_int(photo.get("imageHeight")),
            )
        )

    return results


def fetch_as_jpeg(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "picture-vocab-trainer/1.0"})
    with urlopen(request, timeout=60) as response:
        raw_bytes = response.read()

    with Image.open(BytesIO(raw_bytes)) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        buffer = BytesIO()
        normalized.save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()


def persist_candidate(
    candidate: CandidateRecord,
    jpeg_bytes: bytes,
    digest: str,
    overwrite: bool,
) -> tuple[Path, Path]:
    category_dir = RAW_ROOT / candidate.category / slugify(candidate.word)
    category_dir.mkdir(parents=True, exist_ok=True)

    basename = f"{candidate.provider}_{candidate.provider_id}"
    image_path = category_dir / f"{basename}.jpg"
    sidecar_path = category_dir / f"{basename}.json"

    if image_path.exists() and not overwrite:
        raise ValueError(f"Candidate already exists: {image_path}")

    image_path.write_bytes(jpeg_bytes)
    sidecar_payload = {
        **asdict(candidate),
        "imagePath": to_repo_relative(image_path),
        "sha256": digest,
    }
    write_json(sidecar_path, sidecar_payload)
    return image_path, sidecar_path


def discover_approved_assets() -> tuple[dict[tuple[str, str], ApprovedAsset], list[dict[str, Any]]]:
    assets: dict[tuple[str, str], ApprovedAsset] = {}
    failures: list[dict[str, Any]] = []

    for sidecar_path in APPROVED_ROOT.rglob("*.json"):
        try:
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            failures.append({"type": "approvedMetadata", "path": to_repo_relative(sidecar_path), "message": str(error)})
            continue

        word = str(metadata.get("word", "")).strip()
        category = str(metadata.get("category", "")).strip()
        if not word or not category:
            failures.append(
                {
                    "type": "approvedMetadata",
                    "path": to_repo_relative(sidecar_path),
                    "message": "Approved sidecar must include word and category.",
                }
            )
            continue

        image_path = find_matching_image(sidecar_path)
        if image_path is None:
            failures.append(
                {
                    "type": "approvedMetadata",
                    "path": to_repo_relative(sidecar_path),
                    "message": "Matching image file was not found for the sidecar.",
                }
            )
            continue

        key = (category, word)
        if key in assets:
            failures.append(
                {
                    "type": "approvedDuplicate",
                    "word": word,
                    "category": category,
                    "message": "More than one approved asset was found for this word.",
                }
            )
            continue

        assets[key] = ApprovedAsset(image_path=image_path, sidecar_path=sidecar_path, metadata=metadata)

    return assets, failures


def build_image_word_entry(
    seed: SeedRecord,
    target_stem: str,
    metadata: dict[str, Any],
    seed_records: list[SeedRecord],
) -> dict[str, Any]:
    return {
        "id": target_stem,
        "image": f"images/approved/{seed.category}/{target_stem}.jpg",
        "answer": seed.word,
        "choices": build_choices(seed, seed_records),
        "category": seed.category,
        "level": seed.level,
        "partOfSpeech": "noun",
        "definition": "",
        "zh": "",
        "hint1": CATEGORY_HINTS.get(seed.category, f"This is related to {seed.category}."),
        "hint2": build_hint2(seed.word, seed.category),
        "source": str(metadata.get("source", "")),
        "sourceUrl": str(metadata.get("sourceUrl", "")),
        "photographer": str(metadata.get("photographer", "")),
        "license": str(metadata.get("license", "")),
    }


def build_choices(seed: SeedRecord, seed_records: list[SeedRecord]) -> list[str]:
    same_category_words = [record.word for record in seed_records if record.category == seed.category]
    if seed.word not in same_category_words:
        same_category_words.insert(0, seed.word)

    answer_index = same_category_words.index(seed.word)
    distractors: list[str] = []
    offset = 1

    while len(distractors) < 3 and offset < len(same_category_words) + 5:
        candidate = same_category_words[(answer_index + offset) % len(same_category_words)]
        if candidate != seed.word and candidate not in distractors:
            distractors.append(candidate)
        offset += 1

    if len(distractors) < 3:
        for record in seed_records:
            if record.word != seed.word and record.word not in distractors:
                distractors.append(record.word)
            if len(distractors) == 3:
                break

    choices = [seed.word, *distractors[:3]]
    randomizer = random.Random(f"{seed.category}:{seed.word}")
    randomizer.shuffle(choices)
    return choices


def build_hint2(word: str, category: str) -> str:
    category_phrases = {
        "airport": "Passengers or airport staff use this during a trip.",
        "hotel": "Guests or hotel staff deal with this during a stay.",
        "office": "Workers often see this during a normal workday.",
        "retail": "Customers or store staff interact with this while shopping.",
        "warehouse": "Warehouse staff use this while storing or moving goods.",
    }
    fallback = category_phrases.get(category, f"This image is connected to {category}.")
    return f"Look for {word} in the scene. {fallback}"


def build_category_indexes(seed_records: list[SeedRecord]) -> dict[tuple[str, str], int]:
    indexes: dict[tuple[str, str], int] = {}
    counters: dict[str, int] = {}

    for seed in seed_records:
        counters[seed.category] = counters.get(seed.category, 0) + 1
        indexes[(seed.category, seed.word)] = counters[seed.category]

    return indexes


def convert_to_jpeg(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_suffix(".tmp.jpg")

    with Image.open(source_path) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        normalized.save(temporary_path, format="JPEG", quality=92)

    temporary_path.replace(target_path)


def find_matching_image(sidecar_path: Path) -> Path | None:
    for extension in IMAGE_EXTENSIONS:
        candidate = sidecar_path.with_suffix(extension)
        if candidate.exists():
            return candidate
    return None


def load_seed_records(seed_path: Path) -> list[SeedRecord]:
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_path}")

    with seed_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"word", "category", "query", "level"}
        if reader.fieldnames is None or not required_columns.issubset(set(reader.fieldnames)):
            raise ValueError("vocab_seed.csv must contain word, category, query, level columns")

        rows: list[SeedRecord] = []
        for row in reader:
            word = str(row.get("word", "")).strip()
            category = str(row.get("category", "")).strip()
            query = str(row.get("query", "")).strip()
            level_text = str(row.get("level", "1")).strip()
            if not word or not category or not query:
                raise ValueError(f"Invalid seed row: {row}")
            rows.append(SeedRecord(word=word, category=category, query=query, level=int(level_text)))

    return rows


def normalize_provider_list(raw_value: str) -> list[str]:
    providers = [token.strip().lower() for token in raw_value.split(",") if token.strip()]
    if not providers:
        raise ValueError("At least one provider must be configured.")
    unsupported = [provider for provider in providers if provider not in SUPPORTED_PROVIDERS]
    if unsupported:
        raise ValueError(f"Unsupported providers: {', '.join(unsupported)}")
    return providers


def load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_report() -> dict[str, Any]:
    if not REPORT_PATH.exists():
        return {
            "generatedAt": None,
            "summary": {
                "downloadedCandidates": 0,
                "approvedImages": 0,
                "syncedEntries": 0,
                "failures": 0,
                "missing": 0,
                "duplicates": 0,
            },
            "downloads": [],
            "approved": [],
            "failures": [],
            "missing": [],
            "duplicates": [],
        }

    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def collect_known_hashes(report: dict[str, Any]) -> dict[str, str]:
    known: dict[str, str] = {}

    for section in ("downloads", "approved"):
        for item in report.get(section, []):
            digest = str(item.get("sha256", "")).strip()
            path = str(item.get("imagePath", item.get("image", ""))).strip()
            if digest and path:
                known[digest] = path

    return known


def build_summary(report: dict[str, Any], synced_entries: int | None = None) -> dict[str, int]:
    return {
        "downloadedCandidates": len(report.get("downloads", [])),
        "approvedImages": len(report.get("approved", [])),
        "syncedEntries": synced_entries if synced_entries is not None else len(report.get("approved", [])),
        "failures": len(report.get("failures", [])),
        "missing": len(report.get("missing", [])),
        "duplicates": len(report.get("duplicates", [])),
    }


def read_json_response(request: Request) -> dict[str, Any]:
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return slug.strip("_")


def to_repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    sys.exit(main())