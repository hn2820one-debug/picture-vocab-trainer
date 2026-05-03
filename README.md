# Picture Vocab Trainer

Picture Vocab Trainer is a static HTML, CSS, and Vanilla JavaScript project for image-based vocabulary practice. Each round shows one image, four English choices, a hint after 2 seconds, and the answer after 5 seconds.

The repository now includes an official-API image pipeline for Pexels and Pixabay. It downloads licensed candidates into images/raw/, lets you manually approve them into images/approved/, and then syncs metadata into data/image_words.json.

## MVP scope

- Load data/image_words.json
- Show a picture and four choices
- Reveal hint1 at 2 seconds
- Reveal the answer at 5 seconds
- Record result type, response time, hint level, and category in localStorage
- Review items from the mistake bank
- Show lightweight progress snapshots
- Fall back to a placeholder if an image path is missing

## Project structure

picture-vocab-trainer/
|- index.html
|- style.css
|- app.js
|- data/
|  |- image_words.json
|  |- vocab_seed.csv
|- images/
|  |- airport/
|  |- approved/
|  |- hotel/
|  |- office/
|  |- raw/
|  |- retail/
|  |- warehouse/
|- tools/
|  |- download_licensed_images.py
|  |- validate_image_bank.py
|- README.md
|- .nojekyll

## Local storage keys

- picture_vocab_prefs
- picture_vocab_attempt_history
- picture_vocab_word_stats
- picture_vocab_mistake_bank

This project does not touch any deepsea_word_aquarium_* keys.

## Result types

- correctBeforeReveal
- correctAfterHint
- correctAfterReveal
- wrongBeforeReveal
- wrongAfterReveal

## Run locally

Because the app fetches JSON, open it through a static server instead of double-clicking index.html.

Example with Python:

```bash
python -m http.server 8000
```

Then open http://localhost:8000.

## Validate the question bank

Run the validator from the project root:

```bash
python tools/validate_image_bank.py
```

The validator checks:

- image_words.json is valid JSON
- duplicate ids
- missing image paths
- images live under images/approved/
- choices length is exactly 4
- answer exists in choices
- source exists
- sourceUrl exists
- license exists
- image file can actually be opened
- SVG placeholders are rejected from the formal bank
- category folder exists under images/approved/
- hint1 and hint2 exist

## Official image workflow

The project uses official APIs only. No scraping is used.

Priority order:

- Pexels API
- Pixabay API

Create a local .env file from .env.example and add at least one API key:

```bash
PEXELS_API_KEY=your_key_here
PIXABAY_API_KEY=your_key_here
```

### 1. Download raw candidate images

```bash
python tools/download_licensed_images.py download
```

This command:

- reads data/vocab_seed.csv
- searches the official APIs in priority order
- downloads JPEG candidates into images/raw/<category>/<word_slug>/
- writes a JSON sidecar beside every image so source metadata is preserved
- updates download_report.json with downloaded items, failures, missing hits, and duplicates

### 2. Manually approve images

After reviewing the raw images, copy the chosen .jpg file and its matching .json sidecar into:

- images/approved/airport/
- images/approved/hotel/
- images/approved/office/
- images/approved/retail/
- images/approved/warehouse/

### 3. Rename and sync into the formal bank

```bash
python tools/download_licensed_images.py sync
```

This command:

- renames approved files to category_###_answer.jpg
- keeps the source metadata in a matching JSON sidecar
- rebuilds data/image_words.json using approved image paths
- preserves source, sourceUrl, photographer, and license fields

Use dry-run if you want to preview sync actions first:

```bash
python tools/download_licensed_images.py sync --dry-run
```

## Seed coverage

The starter seed file contains 50 target words:

- airport: 10
- hotel: 10
- office: 10
- retail: 10
- warehouse: 10

## Updating the image bank

1. Add the image under images/category/.
2. Use a filename like category_001_answer.jpg.
3. Keep the matching .json sidecar so the source metadata survives approval.
4. Run python tools/download_licensed_images.py sync.
5. Ensure choices contains the answer.
6. Run the validator.
7. Test locally before pushing.

The sample assets in this repository are SVG placeholders so the starter project works without external downloads. Replace them with real images when you expand the bank.

The strict validator will fail until the formal bank is rebuilt to use approved non-SVG images.

## Deployment

Push the repository to GitHub and enable GitHub Pages. The .nojekyll file is already included for static hosting compatibility.