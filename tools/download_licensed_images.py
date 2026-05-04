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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
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

SCRAPER_LABEL = "Web Scraper (DuckDuckGo)"
SCRAPER_LICENSE = "Personal Use Only"

CATEGORY_HINTS = {
    "airport": "This is related to airport travel.",
    "hotel": "This is related to staying at a hotel.",
    "office": "This is related to office work.",
    "retail": "This is related to shopping or store operations.",
    "warehouse": "This is related to warehouse or shipping work.",
    "meeting": "This is related to business meetings or presentations.",
    "business_contract": "This is related to business documents, contracts, or legal agreements.",
}

CATEGORY_SLUG_ALIASES = {
    "airport": "airport",
    "機場": "airport",
    "机场": "airport",
    "hotel": "hotel",
    "飯店": "hotel",
    "饭店": "hotel",
    "酒店": "hotel",
    "office": "office",
    "辦公室": "office",
    "办公室": "office",
    "retail": "retail",
    "零售": "retail",
    "商店": "retail",
    "warehouse": "warehouse",
    "倉庫": "warehouse",
    "仓库": "warehouse",
    "meeting": "meeting",
    "會議": "meeting",
    "会议": "meeting",
    "business_contract": "business_contract",
    "商業/合約": "business_contract",
    "商业/合约": "business_contract",
    # Categories 04-25
    "財務/會計": "financial_accounting",
    "财务/会计": "financial_accounting",
    "行銷/廣告": "marketing_advertising",
    "行销/广告": "marketing_advertising",
    "銷售/服務": "sales_service",
    "销售/服务": "sales_service",
    "旅遊/差旅": "travel_business",
    "旅游/差旅": "travel_business",
    "餐飲": "food_beverage",
    "餐饮": "food_beverage",
    "房地產/建築": "real_estate",
    "房地产/建筑": "real_estate",
    "運輸/物流": "logistics",
    "运输/物流": "logistics",
    "製造/生產": "manufacturing",
    "制造/生产": "manufacturing",
    "科技/IT": "technology",
    "招聘/人事": "hr_recruitment",
    "醫療/健康": "healthcare",
    "医疗/健康": "healthcare",
    "教育/學術": "education",
    "教育/学术": "education",
    "環境/能源": "environment_energy",
    "环境/能源": "environment_energy",
    "銀行/金融服務": "banking_finance",
    "银行/金融服务": "banking_finance",
    "法律/法規": "legal",
    "法律/法规": "legal",
    "公告/通知": "announcement",
    "公益慈善": "charity",
    "社會經濟": "social_economy",
    "社会经济": "social_economy",
    "媒體/出版": "media_publishing",
    "媒体/出版": "media_publishing",
    "健身/運動": "fitness_sports",
    "健身/运动": "fitness_sports",
    "藝術/娛樂": "arts_entertainment",
    "艺术/娱乐": "arts_entertainment",
    "環境/天氣": "environment_weather",
    "环境/天气": "environment_weather",
}

CSV_FIELD_ALIASES = {
    "word": ("word", "單字", "单字"),
    "category": ("category", "主題", "主题"),
    "zh": ("zh", "中文", "中文名稱", "中文名称"),
    "query": ("query", "搜尋字串", "搜索字串", "搜尋詞", "搜索词"),
    "level": ("level", "難度", "难度"),
}


@dataclass(frozen=True)
class SeedRecord:
    word: str
    category: str
    query: str
    level: int
    zh: str = ""


@dataclass
class CandidateRecord:
    word: str
    category: str
    query: str
    zh: str
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
    download_parser.add_argument("--per-seed", type=int, default=5, help="Number of candidate images to save per seed word")
    download_parser.add_argument("--delay", type=float, default=0.4, help="Delay between seed queries in seconds")
    download_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing raw candidates with the same provider id")
    download_parser.add_argument("--max-seeds", type=int, default=0, help="Optional limit for testing smaller batches")
    download_parser.add_argument("--workers", type=int, default=6, help="Number of concurrent image downloads per seed")
    download_parser.add_argument("--scraper", action="store_true", help="Enable Web Scraper fallback (DuckDuckGo) when API results are insufficient. Scraper images are tagged 'Personal Use Only'.")

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
        report["failures"] = merge_records(
            report.get("failures", []),
            [{"type": "configuration", "message": reason}],
            ("type", "message"),
        )
        report["summary"] = build_summary(report)
        write_json(REPORT_PATH, report)
        print(reason)
        return 1

    seen_hashes = collect_known_hashes(report)
    downloads = list(report.get("downloads", []))
    failures = list(report.get("failures", []))
    missing = list(report.get("missing", []))
    duplicates = list(report.get("duplicates", []))

    for index, seed in enumerate(seed_records, start=1):
        existing_count, next_index, existing_provider_paths, existing_hashes = inspect_existing_raw_candidates(seed)
        for digest, existing_path in existing_hashes.items():
            seen_hashes.setdefault(digest, existing_path)

        saved_count = existing_count
        print(f"[{index}/{len(seed_records)}] {seed.category} :: {seed.word}")

        if saved_count >= args.per_seed and not args.overwrite:
            print(f"  already have {saved_count} candidate images, skipping")
            missing = [
                item
                for item in missing
                if not (
                    item.get("word") == seed.word
                    and item.get("category") == seed.category
                )
            ]
            if args.delay > 0 and index < len(seed_records):
                time.sleep(args.delay)
            continue

        candidate_queue: list[CandidateRecord] = []
        queued_provider_keys: set[tuple[str, str]] = set()

        for provider in active_providers:
            try:
                candidates = search_provider(provider, seed, api_keys[provider], args.per_seed)
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                failures = merge_records(
                    failures,
                    [
                        {
                            "word": seed.word,
                            "category": seed.category,
                            "query": seed.query,
                            "provider": provider,
                            "message": str(error),
                        }
                    ],
                    ("word", "category", "query", "provider", "message"),
                )
                continue

            for candidate in candidates:
                provider_key = (candidate.provider, candidate.provider_id)
                if provider_key in queued_provider_keys:
                    continue
                if provider_key in existing_provider_paths and not args.overwrite:
                    continue
                candidate_queue.append(candidate)
                queued_provider_keys.add(provider_key)

        outcome_by_provider_key = download_candidates_concurrently(candidate_queue, max_workers=args.workers)

        for candidate in candidate_queue:
            if saved_count >= args.per_seed:
                break

            provider_key = (candidate.provider, candidate.provider_id)
            outcome = outcome_by_provider_key.get(provider_key)
            if not outcome:
                continue
            if outcome.get("error"):
                failures = merge_records(
                    failures,
                    [
                        {
                            "word": seed.word,
                            "category": seed.category,
                            "query": candidate.query,
                            "provider": candidate.provider,
                            "providerId": candidate.provider_id,
                            "message": str(outcome["error"]),
                        }
                    ],
                    ("word", "category", "query", "provider", "providerId", "message"),
                )
                continue

            digest = str(outcome["digest"])
            existing_paths = existing_provider_paths.get(provider_key)
            existing_target = to_repo_relative(existing_paths[0]) if existing_paths else ""
            duplicate_of = seen_hashes.get(digest, "")
            if duplicate_of and duplicate_of != existing_target:
                duplicates = merge_records(
                    duplicates,
                    [
                        {
                            "word": seed.word,
                            "category": seed.category,
                            "query": candidate.query,
                            "provider": candidate.provider,
                            "providerId": candidate.provider_id,
                            "duplicateOf": duplicate_of,
                        }
                    ],
                    ("word", "category", "query", "provider", "providerId", "duplicateOf"),
                )
                continue

            image_path, sidecar_path = persist_candidate(
                candidate,
                outcome["jpeg_bytes"],
                digest,
                args.overwrite,
                slot_index=None if existing_paths else next_index,
                existing_paths=existing_paths,
            )
            seen_hashes[digest] = to_repo_relative(image_path)
            existing_provider_paths[provider_key] = (image_path, sidecar_path)
            downloads = merge_records(
                downloads,
                [
                    {
                        **asdict(candidate),
                        "imagePath": to_repo_relative(image_path),
                        "sidecarPath": to_repo_relative(sidecar_path),
                        "sha256": digest,
                    }
                ],
                ("imagePath",),
            )

            if not existing_paths:
                saved_count += 1
                next_index += 1

        # Scraper fallback: supplement if API results were insufficient
        if saved_count < args.per_seed and getattr(args, "scraper", False):
            shortfall = args.per_seed - saved_count
            print(f"  [hybrid] {saved_count}/{args.per_seed} from APIs, scraping {shortfall} more\u2026")
            scraper_candidates = search_scraper(seed, shortfall)
            scraper_outcomes = download_candidates_concurrently(scraper_candidates, max_workers=args.workers)
            for candidate in scraper_candidates:
                if saved_count >= args.per_seed:
                    break
                provider_key = (candidate.provider, candidate.provider_id)
                outcome = scraper_outcomes.get(provider_key)
                if not outcome:
                    continue
                if outcome.get("error"):
                    failures = merge_records(
                        failures,
                        [
                            {
                                "word": seed.word,
                                "category": seed.category,
                                "query": seed.query,
                                "provider": candidate.provider,
                                "providerId": candidate.provider_id,
                                "message": str(outcome["error"]),
                            }
                        ],
                        ("word", "category", "query", "provider", "providerId", "message"),
                    )
                    continue
                digest = str(outcome["digest"])
                duplicate_of = seen_hashes.get(digest, "")
                if duplicate_of:
                    duplicates = merge_records(
                        duplicates,
                        [
                            {
                                "word": seed.word,
                                "category": seed.category,
                                "provider": candidate.provider,
                                "providerId": candidate.provider_id,
                                "duplicateOf": duplicate_of,
                            }
                        ],
                        ("word", "category", "provider", "providerId", "duplicateOf"),
                    )
                    continue
                image_path, sidecar_path = persist_candidate(
                    candidate,
                    outcome["jpeg_bytes"],
                    digest,
                    args.overwrite,
                    slot_index=next_index,
                    existing_paths=None,
                )
                seen_hashes[digest] = to_repo_relative(image_path)
                downloads = merge_records(
                    downloads,
                    [
                        {
                            **asdict(candidate),
                            "imagePath": to_repo_relative(image_path),
                            "sidecarPath": to_repo_relative(sidecar_path),
                            "sha256": digest,
                        }
                    ],
                    ("imagePath",),
                )
                saved_count += 1
                next_index += 1

        if saved_count < args.per_seed:
            missing = merge_records(
                missing,
                [
                    {
                        "word": seed.word,
                        "category": seed.category,
                        "query": seed.query,
                        "reason": f"Collected {saved_count} of requested {args.per_seed} candidates.",
                    }
                ],
                ("word", "category", "query", "reason"),
            )
        else:
            missing = [
                item
                for item in missing
                if not (
                    item.get("word") == seed.word
                    and item.get("category") == seed.category
                )
            ]

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
    existing_entries = load_existing_entry_map()

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
        entries.append(
            build_image_word_entry(
                seed,
                target_stem,
                metadata,
                seed_records,
                existing_entry=existing_entries.get((seed.category, seed.word)),
            )
        )

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
    search_limit = max(per_seed * 3, per_seed + 4, 8)
    query_variants = build_query_variants(seed)
    seen_provider_ids: set[str] = set()
    results: list[CandidateRecord] = []

    for query in query_variants:
        query_seed = SeedRecord(
            word=seed.word,
            category=seed.category,
            query=query,
            level=seed.level,
            zh=seed.zh,
        )
        if provider == "pexels":
            provider_results = search_pexels(query_seed, api_key, search_limit)
        elif provider == "pixabay":
            provider_results = search_pixabay(query_seed, api_key, search_limit)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        for candidate in provider_results:
            if candidate.provider_id in seen_provider_ids:
                continue
            seen_provider_ids.add(candidate.provider_id)
            results.append(candidate)
            if len(results) >= search_limit:
                return results

    return results


def build_query_variants(seed: SeedRecord) -> list[str]:
    raw_variants = [
        seed.query.strip(),
        f"{seed.category.replace('_', ' ')} {seed.word}".strip(),
        seed.word.replace("-", " ").strip(),
        seed.word.strip(),
    ]
    seen: set[str] = set()
    variants: list[str] = []

    for variant in raw_variants:
        lowered = variant.lower()
        if not variant or lowered in seen:
            continue
        seen.add(lowered)
        variants.append(variant)

    return variants


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
                zh=seed.zh,
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
                zh=seed.zh,
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


def _ddg_image_urls(query: str, needed: int) -> list[str]:
    """Fetch image direct-link URLs from DuckDuckGo Images via their token endpoint."""
    try:
        search_url = "https://duckduckgo.com/?q=" + quote_plus(query) + "&iax=images&ia=images"
        req = Request(search_url, headers={"User-Agent": "picture-vocab-trainer/1.0"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(r"vqd=([\d-]+)", html)
        if not m:
            return []
        vqd = m.group(1)
        params = urlencode({"l": "us-en", "o": "json", "q": query, "vqd": vqd, "f": ",,,,,", "p": "1"})
        api_req = Request(
            f"https://duckduckgo.com/i.js?{params}",
            headers={"User-Agent": "picture-vocab-trainer/1.0", "Referer": "https://duckduckgo.com/"},
        )
        with urlopen(api_req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        urls: list[str] = []
        for item in data.get("results", []):
            img = item.get("image", "")
            if img and img.startswith("http"):
                urls.append(img)
                if len(urls) >= needed * 3:
                    break
        return urls
    except Exception as exc:
        print(f"  [scraper] DuckDuckGo query '{query}' failed: {exc}", file=sys.stderr)
        return []


def search_scraper(seed: SeedRecord, needed: int) -> list[CandidateRecord]:
    """Supplement missing candidates via DuckDuckGo Images.

    Returned images carry license = SCRAPER_LICENSE ('Personal Use Only').
    """
    query = f"{seed.word} {seed.category.replace('_', ' ')} photo"
    urls = _ddg_image_urls(query, needed)
    results: list[CandidateRecord] = []
    for url in urls:
        provider_id = hashlib.sha256(url.encode()).hexdigest()[:16]
        results.append(
            CandidateRecord(
                word=seed.word,
                category=seed.category,
                query=seed.query,
                zh=seed.zh,
                provider="scraper",
                provider_id=provider_id,
                source=SCRAPER_LABEL,
                sourceUrl=url,
                photographer="",
                license=SCRAPER_LICENSE,
                downloadUrl=url,
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
    slot_index: int | None = None,
    existing_paths: tuple[Path, Path] | None = None,
) -> tuple[Path, Path]:
    category_dir = RAW_ROOT / slugify(candidate.category) / slugify(candidate.word)
    category_dir.mkdir(parents=True, exist_ok=True)

    if existing_paths is not None:
        image_path, sidecar_path = existing_paths
    else:
        if slot_index is None:
            raise ValueError("slot_index is required when writing a new raw candidate")
        basename = f"{slugify(candidate.word)}_{slot_index:03d}"
        image_path = category_dir / f"{basename}.jpg"
        sidecar_path = category_dir / f"{basename}.json"

    if existing_paths is None and image_path.exists() and not overwrite:
        raise ValueError(f"Candidate already exists: {image_path}")

    image_path.write_bytes(jpeg_bytes)
    sidecar_payload = {
        **asdict(candidate),
        "imagePath": to_repo_relative(image_path),
        "sidecarPath": to_repo_relative(sidecar_path),
        "sha256": digest,
    }
    write_json(sidecar_path, sidecar_payload)
    return image_path, sidecar_path


def download_candidates_concurrently(candidates: list[CandidateRecord], max_workers: int) -> dict[tuple[str, str], dict[str, Any]]:
    if not candidates:
        return {}

    outcome_by_provider_key: dict[tuple[str, str], dict[str, Any]] = {}
    worker_count = min(max(1, max_workers), len(candidates))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_candidate = {
            executor.submit(fetch_as_jpeg, candidate.downloadUrl): candidate
            for candidate in candidates
        }
        for future in as_completed(future_to_candidate):
            candidate = future_to_candidate[future]
            provider_key = (candidate.provider, candidate.provider_id)
            try:
                jpeg_bytes = future.result()
                outcome_by_provider_key[provider_key] = {
                    "jpeg_bytes": jpeg_bytes,
                    "digest": hashlib.sha256(jpeg_bytes).hexdigest(),
                }
            except (HTTPError, URLError, TimeoutError, UnidentifiedImageError, OSError, ValueError) as error:
                outcome_by_provider_key[provider_key] = {"error": str(error)}

    return outcome_by_provider_key


def inspect_existing_raw_candidates(seed: SeedRecord) -> tuple[int, int, dict[tuple[str, str], tuple[Path, Path]], dict[str, str]]:
    raw_dir = RAW_ROOT / slugify(seed.category) / slugify(seed.word)
    if not raw_dir.exists():
        return 0, 1, {}, {}

    sidecars = sorted(raw_dir.glob("*.json"), key=lambda path: path.name)
    next_index = 1
    provider_paths: dict[tuple[str, str], tuple[Path, Path]] = {}
    hash_paths: dict[str, str] = {}
    basename_pattern = re.compile(rf"^{re.escape(slugify(seed.word))}_(\d{{3}})$")

    for sidecar_path in sidecars:
        match = basename_pattern.match(sidecar_path.stem)
        if match:
            next_index = max(next_index, int(match.group(1)) + 1)

        image_path = find_matching_image(sidecar_path)
        if image_path is None:
            continue

        try:
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        provider = str(metadata.get("provider", "")).strip().lower()
        provider_id = str(metadata.get("provider_id") or metadata.get("providerId") or "").strip()
        digest = str(metadata.get("sha256", "")).strip()
        if provider and provider_id:
            provider_paths[(provider, provider_id)] = (image_path, sidecar_path)
        if digest:
            hash_paths[digest] = to_repo_relative(image_path)

    if next_index == 1 and sidecars:
        next_index = len(sidecars) + 1

    return len(sidecars), next_index, provider_paths, hash_paths


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
    existing_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_entry = existing_entry or {}
    return {
        "id": target_stem,
        "image": f"images/approved/{seed.category}/{target_stem}.jpg",
        "answer": seed.word,
        "choices": build_choices(seed, seed_records),
        "category": seed.category,
        "level": seed.level,
        "partOfSpeech": str(metadata.get("partOfSpeech") or existing_entry.get("partOfSpeech", "noun")),
        "definition": str(metadata.get("definition") or existing_entry.get("definition", "")),
        "zh": str(metadata.get("zh") or existing_entry.get("zh", "")),
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
        if reader.fieldnames is None:
            raise ValueError("Seed CSV must include a header row.")

        rows: list[SeedRecord] = []
        for row in reader:
            word = get_csv_value(row, "word")
            raw_category = get_csv_value(row, "category")
            zh = get_csv_value(row, "zh")
            category = normalize_category_slug(raw_category)
            query = get_csv_value(row, "query") or build_default_query(category, word)
            level_text = get_csv_value(row, "level") or "1"
            if not word or not category:
                raise ValueError(f"Invalid seed row: {row}")
            rows.append(SeedRecord(word=word, category=category, query=query, level=int(level_text), zh=zh))

    return rows


def _strip_cite(value: str) -> str:
    """Remove [cite: x] annotations from a CSV field value."""
    return re.sub(r"\s*\[cite:[^\]]*\]", "", value).strip()


def _strip_topic_prefix(value: str) -> str:
    """Remove leading numeric prefix like '01. ' from a topic/category value."""
    return re.sub(r"^\d+\.\s*", "", value).strip()


def get_csv_value(row: dict[str, Any], field_name: str) -> str:
    for alias in CSV_FIELD_ALIASES[field_name]:
        value = str(row.get(alias, "")).strip()
        if value:
            value = _strip_cite(value)
            if field_name == "category":
                value = _strip_topic_prefix(value)
            return value
    return ""


def normalize_category_slug(raw_category: str) -> str:
    cleaned = raw_category.strip()
    if not cleaned:
        return ""

    alias_key = cleaned.lower()
    mapped = CATEGORY_SLUG_ALIASES.get(alias_key) or CATEGORY_SLUG_ALIASES.get(cleaned)
    if mapped:
        return mapped

    slug = slugify(cleaned)
    if not slug:
        raise ValueError(f"Could not derive a safe ASCII slug for category: {raw_category}")
    return slug


def build_default_query(category: str, word: str) -> str:
    return f"{category.replace('_', ' ')} {word}".strip()


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


def load_existing_entry_map() -> dict[tuple[str, str], dict[str, Any]]:
    if not IMAGE_WORDS_PATH.exists():
        return {}

    try:
        payload = json.loads(IMAGE_WORDS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, list):
        return {}

    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not category or not answer:
            continue
        entries[(category, answer)] = item

    return entries


def collect_known_hashes(report: dict[str, Any]) -> dict[str, str]:
    known: dict[str, str] = {}

    for section in ("downloads", "approved"):
        for item in report.get(section, []):
            digest = str(item.get("sha256", "")).strip()
            path = str(item.get("imagePath", item.get("image", ""))).strip()
            if digest and path:
                known[digest] = path

    return known


def merge_records(existing: list[dict[str, Any]], new_items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}

    for item in existing + new_items:
        key = tuple(str(item.get(field, "")).strip() for field in key_fields)
        merged[key] = item

    return list(merged.values())


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