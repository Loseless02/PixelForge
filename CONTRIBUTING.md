# Contributing

## Setup

```bash
pip install -e ".[dev,formats]" && python scripts/fetch_models.py
```

## Before opening a pull request

```bash
ruff check . && pytest -m "not slow" -q
```

If you touched the upscaling path, run the full suite (`pytest -q`) — the
`slow` tests exercise the real Real-ESRGAN binary and need a Vulkan GPU.

## Ground rules

- **`pixelforge/core/` never imports Qt.** That boundary is what keeps the CLI
  and the test suite headless. If you need UI state in the core, you are
  probably solving it in the wrong layer.
- **Colours live in `gui/theme.py`.** No hard-coded hex in widgets; add a token
  to `Palette` instead, so both themes and every accent keep working.
- **Long work goes on a thread.** Anything that touches the pipeline runs in a
  `QRunnable` or a `QThread` and reports back through signals. Widgets are
  never touched off the GUI thread — emit a `QImage` and convert in the slot.
- **New settings go on `EditSettings`.** Add the field, add it to the panel,
  and add a round-trip assertion in `tests/test_settings.py`.
- **New adjustments** belong in `core/adjust.py`, in the fixed stage order, and
  need an entry in `Adjustments.is_identity()` so the no-op fast path stays
  correct.

## Adding a backend

Subclass `UpscaleBackend` in `core/backends/`, implement `is_available`,
`models` and `upscale`, and register it in `core/backends/__init__.py`. The
registry degrades to `classic` whenever a backend reports itself unavailable,
so a missing binary must never raise at import time.

## Commit messages

Short imperative subject line. Reference the issue number when there is one.
