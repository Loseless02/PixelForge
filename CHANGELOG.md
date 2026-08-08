# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] — 2026-08-09

### Added

- **Result comparison.** When a render finishes the canvas shows the finished
  image with the before/after slider already up, the "before" side being the
  source scaled to matching dimensions with Lanczos. Results are cached per
  file, so switching away and back keeps the comparison.
- **Automatic model selection**, and it is now the default. `core.analyze`
  scores flat-area share, colour variety and edge density on a 256 px proxy to
  tell photographs from illustrations, and routes to the photo or anime weights
  per file. The Enhance tab shows the verdict, the confidence and the reasoning
  for whichever image is selected, with a one-click override.
- CLI: `-m auto`.

### Changed

- The model, output format, suffix, metadata and overwrite choices now persist
  between sessions. Previously only the first-ever values were kept.

### Fixed

- A cancelled AI preview still reported back under its original token, so its
  empty result could overwrite whatever had replaced it on the canvas.

## [1.1.0] — 2026-08-09

### Added

- **Real AI preview.** The "after" side of the split view now runs the actual
  model on a size-capped proxy instead of a Lanczos stand-in, so the comparison
  reflects what you will get. Debounced, cancellable, and it stands aside while
  a batch run owns the GPU. Toggle with `A`.
- **Strength presets** — Fast, Balanced and Maximum — plus individual controls
  for oversampling, test-time augmentation and how many AI passes may stack.
- **Detail** and **Clarity** adjustments: multi-scale micro-contrast and masked
  large-radius local contrast, applied after the upscale.
- New "Crisp" look preset; "Restore" now includes detail recovery.
- Output defaults to `Pictures/upscaled`, created on demand, with a
  "Save next to the original" toggle and an "Open output folder" button. The
  choice is remembered between runs.
- CLI: `--quality`, `--oversample`, `--tta`, `--max-chain`, `--detail`,
  `--clarity`, `--next-to-source`.

### Fixed

- Filter output was cast to 8-bit with truncation, which silently discarded
  every sub-unit change a gentle adjustment made. It now rounds.

## [1.0.0] — 2026-08-08

First release.

### Added

- Real-ESRGAN upscaling through the bundled ncnn/Vulkan runtime, fully offline,
  with `x4plus`, `x4plus-anime` and `animevideov3` models.
- Classic resampling backend (Lanczos, bicubic, bilinear, hamming, box,
  nearest) that is always available.
- Arbitrary target resolutions: scale factor, exact width/height, long edge,
  percentage, and fourteen named presets.
- Cover, contain, pad and stretch fit modes with a configurable background
  colour.
- Interactive crop with aspect-ratio lock, plus rotate and flip.
- Adjustments: brightness, contrast, saturation, gamma, temperature, tint,
  sharpness, unsharp mask, denoise, blur, vignette, mono, sepia, invert,
  auto-contrast and equalize, with ten one-click looks.
- Export to PNG, JPEG, WebP, TIFF, BMP, ICO, AVIF and HEIC, with quality,
  compression, metadata retention and GPS stripping.
- Batch queue with per-file progress, cancellation and an overwrite policy.
- Live preview with a before/after split handle, zoom and pan.
- Dark and light themes, seven accent colours, frameless window.
- Command line interface (`python -m pixelforge --cli`) over the same pipeline.
- `scripts/fetch_models.py` with SHA-256 verification of every downloaded file.
