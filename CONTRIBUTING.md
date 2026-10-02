# Contributing

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Model files are downloaded locally and should not be committed to the repository. The default cache root is `~/.cache/imgtagplus`, with a repo-local fallback at `.cache/imgtagplus` when the home cache is unavailable. The repository ignores `.cache/` so those downloads stay local.

If you want to pre-download the CLIP model during setup, run:

```bash
python -m imgtagplus -i ./test_image.jpg --model-id clip --silent --output-dir /tmp/imgtagplus-model-warmup
```

If you also develop against Florence, repeat that command with `--model-id florence-2-base`.

If you change frontend styles, also run:

```bash
npm install
npm run build:css
```

## Validation

Run the local checks before opening a PR:

```bash
ruff check .
pytest
```

## Scope

- Prefer small, reviewable pull requests.
- Keep local-only safety behavior (CSRF origin checks, rate limits) intact; path-based sandbox restrictions are intentionally removed.
- Add tests for behavior changes, especially around metadata writing, server validation, and model-selection logic.

## Pull requests

- Describe the user-visible impact.
- Note any dependency or model-cache changes.
- Update `README.md`, `SPEC.md`, or `CHANGELOG.md` when behavior or developer workflow changes.
