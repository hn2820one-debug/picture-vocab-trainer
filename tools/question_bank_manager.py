from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from download_licensed_images import (
    APPROVED_ROOT,
    REPO_ROOT,
    SEED_PATH,
    RAW_ROOT,
    build_category_indexes,
    convert_to_jpeg,
    discover_approved_assets,
    find_matching_image,
    iso_now,
    load_seed_records,
    run_sync,
    slugify,
    to_repo_relative,
    write_json,
)


MANAGER_MANIFEST_PATH = REPO_ROOT / "data" / "manager_candidates.json"
DEFAULT_MAX_OPTIONS = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build manager manifests and apply image selections back into the approved bank."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest_parser = subparsers.add_parser("manifest", help="Generate data/manager_candidates.json from raw candidates.")
    manifest_parser.add_argument("--seed-file", default=str(SEED_PATH), help="Path to vocab_seed.csv")
    manifest_parser.add_argument("--output", default=str(MANAGER_MANIFEST_PATH), help="Output manifest path")
    manifest_parser.add_argument("--max-options", type=int, default=DEFAULT_MAX_OPTIONS, help="Maximum options to expose per word")

    apply_parser = subparsers.add_parser("apply", help="Apply an exported manager selection JSON into the approved bank.")
    apply_parser.add_argument("--seed-file", default=str(SEED_PATH), help="Path to vocab_seed.csv")
    apply_parser.add_argument("--selection-file", required=True, help="Path to the JSON exported by manager.html")
    apply_parser.add_argument("--dry-run", action="store_true", help="Preview which selections would be applied")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "manifest":
        return run_manifest(args)
    if args.command == "apply":
        return run_apply(args)
    print(f"Unsupported command: {args.command}")
    return 1


def run_manifest(args: argparse.Namespace) -> int:
    seed_records = load_seed_records(Path(args.seed_file))
    approved_assets, failures = discover_approved_assets()
    max_options = max(1, args.max_options)
    existing_entries = load_existing_entries()

    entries: list[dict[str, Any]] = []
    option_totals = 0

    for seed in seed_records:
        key = (seed.category, seed.word)
        approved_asset = approved_assets.get(key)
        existing_entry = existing_entries.get(key, {})
        options = collect_options(seed, approved_asset, max_options)
        option_totals += len(options)
        entries.append(
            {
                "id": existing_entry.get("id", f"{seed.category}:{slugify(seed.word)}"),
                "word": seed.word,
                "category": seed.category,
                "query": seed.query,
                "level": seed.level,
                "zh": str(existing_entry.get("zh", "") or metadata_value(approved_asset, "zh") or seed.zh),
                "options": options,
            }
        )

    payload = {
        "generatedAt": iso_now(),
        "maxOptions": max_options,
        "summary": {
            "entries": len(entries),
            "entriesWithFullOptions": sum(1 for entry in entries if len(entry["options"]) >= max_options),
            "averageOptions": round(option_totals / len(entries), 2) if entries else 0,
            "failures": len(failures),
        },
        "failures": failures,
        "entries": entries,
    }
    write_json(Path(args.output), payload)
    print(f"Generated manager manifest with {len(entries)} entries at {Path(args.output).as_posix()}.")
    return 0


def run_apply(args: argparse.Namespace) -> int:
    seed_records = load_seed_records(Path(args.seed_file))
    seed_map = {(seed.category, seed.word): seed for seed in seed_records}
    category_indexes = build_category_indexes(seed_records)

    selection_path = Path(args.selection_file)
    if not selection_path.exists():
        print(f"Selection file not found: {selection_path}")
        return 1

    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    selections = payload.get("selections", [])
    if not isinstance(selections, list) or not selections:
        print("Selection file does not contain any selections.")
        return 1

    changes: list[dict[str, str]] = []
    problems: list[str] = []

    for item in selections:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip()
        category = str(item.get("category", "")).strip()
        zh = str(item.get("zh", "")).strip()
        selected_option = item.get("selectedOption")
        if not isinstance(selected_option, dict):
            continue

        seed = seed_map.get((category, word))
        if seed is None:
            problems.append(f"Unknown seed entry: {category} / {word}")
            continue

        image_path = resolve_repo_path(str(selected_option.get("image", "")).strip())
        sidecar_path = resolve_repo_path(str(selected_option.get("sidecar", "")).strip())
        if image_path is None or not image_path.exists():
            problems.append(f"Missing selected image for {category} / {word}")
            continue
        if sidecar_path is None or not sidecar_path.exists():
            problems.append(f"Missing selected sidecar for {category} / {word}")
            continue

        try:
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            problems.append(f"Invalid JSON sidecar for {category} / {word}: {error}")
            continue

        ordinal = category_indexes[(seed.category, seed.word)]
        target_stem = f"{seed.category}_{ordinal:03d}_{slugify(seed.word)}"
        target_image = APPROVED_ROOT / seed.category / f"{target_stem}.jpg"
        target_sidecar = APPROVED_ROOT / seed.category / f"{target_stem}.json"

        metadata["word"] = seed.word
        metadata["category"] = seed.category
        metadata["zh"] = zh
        metadata["approvedId"] = target_stem
        metadata["approvedImagePath"] = f"images/approved/{seed.category}/{target_stem}.jpg"

        if not args.dry_run:
            convert_to_jpeg(image_path, target_image)
            write_json(target_sidecar, metadata)

        changes.append(
            {
                "word": seed.word,
                "category": seed.category,
                "zh": zh,
                "image": to_repo_relative(image_path),
                "target": to_repo_relative(target_image),
            }
        )

    if problems:
        for problem in problems:
            print(problem)
        return 1

    if not changes:
        print("No valid selections were found in the selection file.")
        return 1

    if args.dry_run:
        print(f"Would apply {len(changes)} selection(s):")
        for change in changes:
            print(f"- {change['category']} / {change['word']} -> {change['image']}")
        return 0

    sync_status = run_sync(argparse.Namespace(seed_file=args.seed_file, dry_run=False))
    if sync_status != 0:
        return sync_status

    print(f"Applied {len(changes)} selection(s) from {selection_path.as_posix()}.")
    return 0


def collect_options(seed, approved_asset, max_options: int) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    if approved_asset is not None:
        option = build_option(
            sidecar_path=approved_asset.sidecar_path,
            image_path=approved_asset.image_path,
            metadata=approved_asset.metadata,
            label="目前題庫版本",
            is_current_approved=True,
        )
        options.append(option)
        digest = str(approved_asset.metadata.get("sha256", "")).strip()
        if digest:
            seen_hashes.add(digest)

    raw_dir = RAW_ROOT / seed.category / slugify(seed.word)
    if raw_dir.exists():
        raw_sidecars = sorted(raw_dir.glob("*.json"), key=lambda path: path.name)
        for sidecar_path in raw_sidecars:
            if len(options) >= max_options:
                break
            image_path = find_matching_image(sidecar_path)
            if image_path is None:
                continue
            try:
                metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue

            digest = str(metadata.get("sha256", "")).strip()
            if digest and digest in seen_hashes:
                continue

            options.append(
                build_option(
                    sidecar_path=sidecar_path,
                    image_path=image_path,
                    metadata=metadata,
                    label=f"候選圖 {len(options) + 1}",
                    is_current_approved=False,
                )
            )
            if digest:
                seen_hashes.add(digest)

    return options[:max_options]


def build_option(
    sidecar_path: Path,
    image_path: Path,
    metadata: dict[str, Any],
    label: str,
    is_current_approved: bool,
) -> dict[str, Any]:
    return {
        "optionId": f"{sidecar_path.parent.name}:{sidecar_path.stem}",
        "label": label,
        "image": to_repo_relative(image_path),
        "sidecar": to_repo_relative(sidecar_path),
        "source": str(metadata.get("source", metadata.get("provider", ""))),
        "sourceUrl": str(metadata.get("sourceUrl", "")),
        "photographer": str(metadata.get("photographer", "")),
        "license": str(metadata.get("license", "")),
        "provider": str(metadata.get("provider", "approved" if is_current_approved else "")),
        "sha256": str(metadata.get("sha256", "")),
        "isCurrentApproved": is_current_approved,
    }


def load_existing_entries() -> dict[tuple[str, str], dict[str, Any]]:
    image_words_path = REPO_ROOT / "data" / "image_words.json"
    if not image_words_path.exists():
        return {}
    try:
        payload = json.loads(image_words_path.read_text(encoding="utf-8"))
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
        if category and answer:
            entries[(category, answer)] = item
    return entries


def metadata_value(approved_asset, key: str) -> str:
    if approved_asset is None:
        return ""
    return str(approved_asset.metadata.get(key, ""))


def resolve_repo_path(relative_path: str) -> Path | None:
    if not relative_path:
        return None
    return REPO_ROOT / Path(relative_path)


if __name__ == "__main__":
    sys.exit(main())