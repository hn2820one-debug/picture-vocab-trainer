"""download_hybrid.py – Hybrid image downloader for picture-vocab-trainer.

Parses a CSV with columns  主題, 單字, 中文  (Chinese topic/word/translation),
cleans topic prefixes and [cite: x] annotations, then collects up to
--per-seed images per word.

Download strategy (hybrid mode):
  1. Try Pexels API
  2. Try Pixabay API
  3. If still below target, scrape DuckDuckGo Images as supplement

Output mirrors the official raw directory structure:
  images/raw/<topic_slug>/<word_slug>/word_001.jpg  + word_001.json

Sidecar JSON fields: source, sourceUrl, license, word, zh
Scraper images are tagged with license = "Personal Use Only".

This script is STANDALONE and does NOT touch image_words.json, manager_candidates.json,
or any other official pipeline artefact.

Usage:
  python tools/download_hybrid.py --input data/new_words.csv
  python tools/download_hybrid.py --input data/new_words.csv --per-seed 5 --workers 6
  python tools/download_hybrid.py --input data/new_words.csv --max-seeds 3 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError as e:
    print("Pillow is required.  pip install Pillow", file=sys.stderr)
    raise SystemExit(1) from e

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "images" / "raw"

# ---------------------------------------------------------------------------
# Provider credentials / licences
# ---------------------------------------------------------------------------
PROVIDER_LICENSES = {
    "pexels": "Pexels License",
    "pixabay": "Pixabay Content License",
    "scraper": "Personal Use Only",
}

PROVIDER_LABELS = {
    "pexels": "Pexels",
    "pixabay": "Pixabay",
    "scraper": "Web Scraper (DuckDuckGo)",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env(path: Path) -> dict[str, str]:
    """Parse a .env file and return a key→value mapping."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug (lowercase, underscores)."""
    text = text.lower().strip()
    # Replace apostrophes / possessives directly
    text = text.replace("'s", "s").replace("'", "")
    # Replace any run of non-alphanumeric chars with underscore
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def clean_topic(raw: str) -> str:
    """
    Remove numeric prefix and trailing [cite: x] from a topic string.
    '01. 辦公室' → '辦公室'
    '03. 商業/合約 [cite: 3]' → '商業/合約'
    """
    # Strip [cite: ...] annotations first
    raw = re.sub(r"\s*\[cite:[^\]]*\]", "", raw).strip()
    # Strip leading "NN. " prefix
    raw = re.sub(r"^\d+\.\s*", "", raw).strip()
    return raw


def clean_zh(raw: str) -> str:
    """Remove [cite: x] annotation from translation field."""
    return re.sub(r"\s*\[cite:[^\]]*\]", "", raw).strip()


def topic_to_slug(topic: str) -> str:
    """
    Map Chinese/mixed topic names to ASCII slugs.
    '辦公室'    → 'office'
    '會議'      → 'meeting'
    '商業/合約' → 'business_contract'
    Falls back to slugify() for unknown topics.
    """
    _MAP = {
        "辦公室": "office",
        "office": "office",
        "會議": "meeting",
        "meeting": "meeting",
        "商業/合約": "business_contract",
        "商業": "business",
        "合約": "contract",
        "機場": "airport",
        "airport": "airport",
        "飯店": "hotel",
        "酒店": "hotel",
        "hotel": "hotel",
        "零售": "retail",
        "retail": "retail",
        "倉庫": "warehouse",
        "warehouse": "warehouse",
    }
    return _MAP.get(topic, slugify(topic))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_url(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    req_headers = {"User-Agent": "picture-vocab-trainer/1.0 (hybrid-downloader)"}
    if headers:
        req_headers.update(headers)
    request = Request(url, headers=req_headers)
    with urlopen(request, timeout=timeout) as resp:
        return resp.read()


def fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    raw = fetch_url(url, headers=headers)
    return json.loads(raw)


def to_jpeg(raw_bytes: bytes) -> bytes:
    """Decode any image format and re-encode as JPEG."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class WordRecord:
    __slots__ = ("word", "zh", "topic", "topic_slug", "word_slug")

    def __init__(self, word: str, zh: str, topic: str) -> None:
        self.word = word
        self.zh = zh
        self.topic = topic
        self.topic_slug = topic_to_slug(topic)
        self.word_slug = slugify(word)


class ImageCandidate:
    __slots__ = ("word_rec", "provider", "download_url", "source_url", "source_label")

    def __init__(
        self,
        word_rec: WordRecord,
        provider: str,
        download_url: str,
        source_url: str,
        source_label: str = "",
    ) -> None:
        self.word_rec = word_rec
        self.provider = provider
        self.download_url = download_url
        self.source_url = source_url
        self.source_label = source_label or PROVIDER_LABELS[provider]


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_csv(path: Path) -> list[WordRecord]:
    """
    Accept CSV with header row containing 主題/topic, 單字/word, 中文/zh columns.
    Also accepts inline CSV text piped through the script.
    """
    records: list[WordRecord] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return records
        # Normalise field names
        field_map: dict[str, str] = {}
        for col in reader.fieldnames:
            col_clean = col.strip()
            if col_clean in ("主題", "topic", "category", "主题"):
                field_map["topic"] = col
            elif col_clean in ("單字", "word", "单字"):
                field_map["word"] = col
            elif col_clean in ("中文", "zh", "中文名稱", "translation"):
                field_map["zh"] = col

        for row in reader:
            raw_topic = row.get(field_map.get("topic", ""), "").strip()
            raw_word = row.get(field_map.get("word", ""), "").strip()
            raw_zh = row.get(field_map.get("zh", ""), "").strip()
            if not raw_word:
                continue
            topic = clean_topic(raw_topic)
            zh = clean_zh(raw_zh)
            records.append(WordRecord(word=raw_word, zh=zh, topic=topic))
    return records


# ---------------------------------------------------------------------------
# Existing candidate inspection
# ---------------------------------------------------------------------------

def _count_existing(word_dir: Path) -> tuple[int, int]:
    """Return (count_of_existing_images, next_free_slot_index)."""
    if not word_dir.is_dir():
        return 0, 1
    existing = sorted(word_dir.glob("*.jpg"))
    return len(existing), len(existing) + 1


def _collect_existing_hashes(word_dir: Path) -> set[str]:
    hashes: set[str] = set()
    if not word_dir.is_dir():
        return hashes
    for jpg in word_dir.glob("*.jpg"):
        try:
            hashes.add(sha256_bytes(jpg.read_bytes()))
        except OSError:
            pass
    return hashes


# ---------------------------------------------------------------------------
# Pexels API
# ---------------------------------------------------------------------------

def search_pexels(rec: WordRecord, api_key: str, limit: int) -> list[ImageCandidate]:
    params = urlencode({
        "query": f"{rec.topic} {rec.word}",
        "per_page": min(limit * 2, 40),
        "orientation": "landscape",
    })
    url = f"https://api.pexels.com/v1/search?{params}"
    try:
        data = fetch_json(url, headers={"Authorization": api_key})
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"  [Pexels] {rec.word}: {exc}", file=sys.stderr)
        return []

    results: list[ImageCandidate] = []
    for photo in data.get("photos", []):
        src = photo.get("src", {})
        dl = src.get("large2x") or src.get("large") or src.get("original") or ""
        if not dl:
            continue
        results.append(ImageCandidate(
            word_rec=rec,
            provider="pexels",
            download_url=dl,
            source_url=str(photo.get("url", "")),
        ))
    return results


# ---------------------------------------------------------------------------
# Pixabay API
# ---------------------------------------------------------------------------

def search_pixabay(rec: WordRecord, api_key: str, limit: int) -> list[ImageCandidate]:
    params = urlencode({
        "key": api_key,
        "q": f"{rec.topic_slug.replace('_', ' ')} {rec.word}",
        "image_type": "photo",
        "orientation": "horizontal",
        "safesearch": "true",
        "per_page": min(limit * 2, 40),
    })
    url = f"https://pixabay.com/api/?{params}"
    try:
        data = fetch_json(url)
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"  [Pixabay] {rec.word}: {exc}", file=sys.stderr)
        return []

    results: list[ImageCandidate] = []
    for hit in data.get("hits", []):
        dl = hit.get("fullHDURL") or hit.get("largeImageURL") or hit.get("imageURL") or ""
        if not dl:
            continue
        results.append(ImageCandidate(
            word_rec=rec,
            provider="pixabay",
            download_url=dl,
            source_url=str(hit.get("pageURL", "")),
        ))
    return results


# ---------------------------------------------------------------------------
# Web Scraper – DuckDuckGo Images (supplement, "Personal Use Only")
# ---------------------------------------------------------------------------

def _ddg_image_urls(query: str, needed: int) -> list[str]:
    """
    Fetch image URLs from DuckDuckGo Images via their token endpoint.
    Returns a flat list of direct image URLs.
    """
    try:
        # Step 1 – obtain a vqd token
        search_url = (
            "https://duckduckgo.com/?q="
            + quote_plus(query)
            + "&iax=images&ia=images"
        )
        html = fetch_url(search_url, timeout=15).decode("utf-8", errors="replace")
        m = re.search(r'vqd=([\d-]+)', html)
        if not m:
            return []
        vqd = m.group(1)

        # Step 2 – fetch image results JSON
        params = urlencode({
            "l": "us-en",
            "o": "json",
            "q": query,
            "vqd": vqd,
            "f": ",,,,,",
            "p": "1",
        })
        api_url = f"https://duckduckgo.com/i.js?{params}"
        data = fetch_json(api_url, headers={"Referer": "https://duckduckgo.com/"})

        urls: list[str] = []
        for item in data.get("results", []):
            img = item.get("image", "")
            if img and img.startswith("http"):
                urls.append(img)
                if len(urls) >= needed * 3:
                    break
        return urls

    except Exception as exc:  # broad catch for scraper resilience
        print(f"  [Scraper] DDG query '{query}' failed: {exc}", file=sys.stderr)
        return []


def scrape_supplement(rec: WordRecord, needed: int) -> list[ImageCandidate]:
    """Return up to `needed` scraper candidates for the given word record."""
    query = f"{rec.word} {rec.topic_slug.replace('_', ' ')} photo"
    urls = _ddg_image_urls(query, needed)
    results: list[ImageCandidate] = []
    for url in urls:
        results.append(ImageCandidate(
            word_rec=rec,
            provider="scraper",
            download_url=url,
            source_url=url,
            source_label="Web Scraper (DuckDuckGo)",
        ))
    return results


# ---------------------------------------------------------------------------
# Saving one image + sidecar
# ---------------------------------------------------------------------------

def _next_slot(word_dir: Path) -> int:
    existing = sorted(word_dir.glob("*.jpg"))
    return len(existing) + 1


def save_candidate(
    jpeg_bytes: bytes,
    digest: str,
    candidate: ImageCandidate,
    word_dir: Path,
    slot: int,
    dry_run: bool,
) -> Path:
    """Write JPEG + sidecar JSON. Returns image path."""
    rec = candidate.word_rec
    slug = rec.word_slug
    stem = f"{slug}_{slot:03d}"
    img_path = word_dir / f"{stem}.jpg"
    sc_path = word_dir / f"{stem}.json"

    sidecar = {
        "source": candidate.source_label,
        "sourceUrl": candidate.source_url,
        "license": PROVIDER_LICENSES[candidate.provider],
        "word": rec.word,
        "zh": rec.zh,
        "sha256": digest,
    }

    if dry_run:
        print(f"    [dry-run] would write {img_path.relative_to(REPO_ROOT)}")
        return img_path

    word_dir.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(jpeg_bytes)
    sc_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    return img_path


# ---------------------------------------------------------------------------
# Per-word download worker
# ---------------------------------------------------------------------------

def _download_one(candidate: ImageCandidate) -> dict[str, Any]:
    """Download a single candidate image; return result dict."""
    try:
        raw = fetch_url(candidate.download_url, timeout=45)
        jpeg = to_jpeg(raw)
        digest = sha256_bytes(jpeg)
        return {"ok": True, "jpeg": jpeg, "digest": digest, "candidate": candidate}
    except (HTTPError, URLError, TimeoutError, UnidentifiedImageError, Exception) as exc:
        return {"ok": False, "error": str(exc), "candidate": candidate}


def process_word(
    rec: WordRecord,
    api_keys: dict[str, str],
    per_seed: int,
    workers: int,
    dry_run: bool,
    delay: float,
) -> dict[str, Any]:
    word_dir = RAW_ROOT / rec.topic_slug / rec.word_slug
    existing_count, next_idx = _count_existing(word_dir)
    existing_hashes = _collect_existing_hashes(word_dir)

    if existing_count >= per_seed:
        print(f"  ✓ already {existing_count} images, skipping")
        return {"saved": 0, "skipped": True}

    needed = per_seed - existing_count
    candidates: list[ImageCandidate] = []

    # 1. Pexels
    if api_keys.get("pexels"):
        candidates += search_pexels(rec, api_keys["pexels"], needed)

    # 2. Pixabay
    if api_keys.get("pixabay"):
        candidates += search_pixabay(rec, api_keys["pixabay"], needed)

    # 3. Scraper supplement if still not enough candidates
    if len(candidates) < needed:
        still_needed = needed - len(candidates)
        print(f"  [hybrid] API returned {len(candidates)} candidates, scraping {still_needed} more…")
        candidates += scrape_supplement(rec, still_needed)

    if not candidates:
        print(f"  ✗ no candidates found for '{rec.word}'")
        return {"saved": 0, "skipped": False}

    # Deduplicate by download URL (quick pre-filter)
    seen_urls: set[str] = set()
    unique_candidates: list[ImageCandidate] = []
    for c in candidates:
        if c.download_url not in seen_urls:
            seen_urls.add(c.download_url)
            unique_candidates.append(c)

    # Concurrent downloads
    saved = 0
    slot = next_idx

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_one, c): c for c in unique_candidates}
        for future in as_completed(futures):
            if saved >= needed:
                break
            result = future.result()
            if not result["ok"]:
                print(f"  ✗ download error: {result['error']}", file=sys.stderr)
                continue
            digest = result["digest"]
            if digest in existing_hashes:
                print(f"  ~ duplicate hash, skipping")
                continue
            existing_hashes.add(digest)
            path = save_candidate(result["jpeg"], digest, result["candidate"], word_dir, slot, dry_run)
            provider_label = PROVIDER_LABELS[result["candidate"].provider]
            print(f"  ✓ saved {path.name} [{provider_label}]")
            saved += 1
            slot += 1
            if delay > 0:
                time.sleep(delay)

    return {"saved": saved, "skipped": False}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Hybrid image downloader (Pexels + Pixabay + Web Scraper fallback)."
    )
    p.add_argument("--input", required=True, help="Path to input CSV (columns: 主題, 單字, 中文)")
    p.add_argument("--per-seed", type=int, default=5, help="Target images per word (default: 5)")
    p.add_argument("--workers", type=int, default=6, help="Concurrent download threads per word")
    p.add_argument("--delay", type=float, default=0.3, help="Pause between words (seconds)")
    p.add_argument("--max-seeds", type=int, default=0, help="Limit number of words processed (0 = all)")
    p.add_argument("--dry-run", action="store_true", help="Parse and plan without writing files")
    p.add_argument(
        "--no-scraper",
        action="store_true",
        help="Disable Web Scraper fallback (official APIs only)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.input).expanduser().resolve()
    if not csv_path.is_file():
        print(f"Input file not found: {csv_path}", file=sys.stderr)
        return 1

    records = parse_csv(csv_path)
    if not records:
        print("No word records found in CSV.", file=sys.stderr)
        return 1

    if args.max_seeds > 0:
        records = records[: args.max_seeds]

    # Load API keys from environment or .env
    env = _load_env(REPO_ROOT / ".env")
    api_keys = {
        "pexels": os.environ.get("PEXELS_API_KEY") or env.get("PEXELS_API_KEY", ""),
        "pixabay": os.environ.get("PIXABAY_API_KEY") or env.get("PIXABAY_API_KEY", ""),
    }
    active = [k for k, v in api_keys.items() if v]
    if not active:
        print(
            "WARNING: No API keys found.  Set PEXELS_API_KEY / PIXABAY_API_KEY in .env or environment.\n"
            "         Proceeding with Web Scraper only.",
            file=sys.stderr,
        )

    # Monkey-patch scraper if disabled
    if args.no_scraper:
        global scrape_supplement  # noqa: PLW0603
        scrape_supplement = lambda *_a, **_kw: []  # type: ignore[assignment]

    total_saved = 0
    total_skipped = 0
    total_words = len(records)

    for idx, rec in enumerate(records, start=1):
        print(f"[{idx}/{total_words}] {rec.topic_slug} :: {rec.word}  ({rec.zh})")
        outcome = process_word(
            rec,
            api_keys=api_keys,
            per_seed=args.per_seed,
            workers=args.workers,
            dry_run=args.dry_run,
            delay=args.delay,
        )
        total_saved += outcome["saved"]
        if outcome["skipped"]:
            total_skipped += 1

    print(
        f"\nDone. {total_saved} images saved, {total_skipped} words already complete "
        f"({total_words} words total)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
