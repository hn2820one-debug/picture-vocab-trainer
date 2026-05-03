from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from PIL import Image, UnidentifiedImageError
except ImportError as error:
    print("Pillow is required. Install it with: pip install Pillow")
    raise SystemExit(1) from error


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    data_path = repo_root / "data" / "image_words.json"
    approved_root = repo_root / "images" / "approved"

    if not data_path.exists():
        print(f"Missing question bank: {data_path}")
        return 1

    if not approved_root.exists():
        print(f"Missing approved image root: {approved_root}")
        return 1

    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"Invalid JSON in {data_path}: {error}")
        return 1

    if not isinstance(payload, list):
        print("image_words.json must contain a JSON array.")
        return 1

    valid_categories = {child.name for child in approved_root.iterdir() if child.is_dir()}
    seen_ids: set[str] = set()
    errors: list[str] = []

    for index, item in enumerate(payload, start=1):
        prefix = f"Entry {index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: item must be an object")
            continue

        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            errors.append(f"{prefix}: missing id")
        elif item_id in seen_ids:
            errors.append(f"{prefix}: duplicate id {item_id}")
        else:
            seen_ids.add(item_id)

        image_rel = item.get("image")
        image_path: Path | None = None
        if not isinstance(image_rel, str) or not image_rel.strip():
            errors.append(f"{prefix}: missing image path")
        else:
            image_path = repo_root / image_rel
            if not image_path.exists():
                errors.append(f"{prefix}: image path not found {image_rel}")
            if not image_rel.startswith("images/approved/"):
                errors.append(f"{prefix}: image path must live under images/approved/")
            if image_path.suffix.lower() == ".svg":
                errors.append(f"{prefix}: SVG placeholders are not allowed in the formal image bank")

        choices = item.get("choices")
        if not isinstance(choices, list) or len(choices) != 4:
            errors.append(f"{prefix}: choices must contain exactly 4 items")

        answer = item.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            errors.append(f"{prefix}: answer must be a non-empty string")
        elif isinstance(choices, list) and answer not in choices:
            errors.append(f"{prefix}: answer must appear in choices")

        category = item.get("category")
        if not isinstance(category, str) or not category.strip():
            errors.append(f"{prefix}: missing category")
        elif category not in valid_categories:
            errors.append(f"{prefix}: category {category} does not exist under images/approved/")

        for field_name in ("source", "sourceUrl", "license"):
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}: {field_name} must be a non-empty string")

        for field_name in ("hint1", "hint2"):
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}: {field_name} must be a non-empty string")

        source = str(item.get("source", ""))
        license_name = str(item.get("license", ""))
        if "placeholder" in source.lower() or "placeholder" in license_name.lower():
            errors.append(f"{prefix}: placeholder attribution is not allowed in the formal image bank")

        if image_path is not None and image_path.exists() and image_path.is_file():
            try:
                with Image.open(image_path) as image:
                    image.verify()
            except (UnidentifiedImageError, OSError) as error:
                errors.append(f"{prefix}: image could not be loaded ({error})")

    if errors:
        print("Validation failed:")
        for message in errors:
            print(f"- {message}")
        return 1

    print(f"Validation passed: {len(payload)} entries, {len(valid_categories)} approved categories.")
    return 0


if __name__ == "__main__":
    sys.exit(main())