"""Loading, saving and format capability discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

# Large panoramas are legitimate input; Pillow's bomb guard is too eager for a
# tool whose whole job is big images. The real guard is geometry.MAX_PIXELS.
Image.MAX_IMAGE_PIXELS = None

_HEIF_OK = False
_AVIF_OK = False

try:  # optional: HEIC/HEIF support
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_OK = True
except Exception:  # pragma: no cover - depends on optional wheel
    pass

try:  # optional: AVIF support (Pillow >= 11.3 has it built in)
    import pillow_avif  # noqa: F401

    _AVIF_OK = True
except Exception:  # pragma: no cover
    _AVIF_OK = "AVIF" in Image.registered_extensions().values()


@dataclass(frozen=True)
class FormatSpec:
    key: str
    label: str
    extension: str
    supports_alpha: bool
    lossy: bool
    available: bool = True


def output_formats() -> tuple[FormatSpec, ...]:
    specs = [
        FormatSpec("PNG", "PNG — lossless, alpha", ".png", True, False),
        FormatSpec("JPEG", "JPEG — small, no alpha", ".jpg", False, True),
        FormatSpec("WEBP", "WebP — small, alpha", ".webp", True, True),
        FormatSpec("TIFF", "TIFF — archival", ".tiff", True, False),
        FormatSpec("BMP", "BMP — uncompressed", ".bmp", False, False),
        FormatSpec("ICO", "ICO — icon", ".ico", True, False),
        FormatSpec("AVIF", "AVIF — modern, small", ".avif", True, True, _AVIF_OK),
        FormatSpec("HEIF", "HEIF / HEIC", ".heic", True, True, _HEIF_OK),
    ]
    return tuple(specs)


READ_EXTENSIONS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".jpe", ".webp", ".bmp", ".tif", ".tiff",
    ".gif", ".ppm", ".pgm", ".tga", ".ico", ".jfif",
) + ((".heic", ".heif") if _HEIF_OK else ()) + ((".avif",) if _AVIF_OK else ())


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in READ_EXTENSIONS


def file_filter() -> str:
    """Qt file-dialog filter string for every readable format."""
    patterns = " ".join(f"*{ext}" for ext in READ_EXTENSIONS)
    return f"Images ({patterns});;All files (*)"


@dataclass
class LoadedImage:
    image: Image.Image
    path: Path
    exif: bytes | None
    icc_profile: bytes | None
    original_mode: str

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


def load(path: Path | str) -> LoadedImage:
    """Open a file, honour its EXIF orientation, and normalise the mode."""
    path = Path(path)
    with Image.open(path) as handle:
        handle.load()
        original_mode = handle.mode
        exif = handle.info.get("exif")
        icc = handle.info.get("icc_profile")
        image = ImageOps.exif_transpose(handle)
        if image is None:  # exif_transpose returns None for some inputs
            image = handle
        image = image.copy()

    if icc:
        image = _to_srgb(image, icc)
        icc = None

    if image.mode in ("P", "LA", "PA"):
        image = image.convert("RGBA" if _has_alpha(image) else "RGB")
    elif image.mode in ("I", "I;16", "F", "L") or image.mode == "CMYK":
        image = image.convert("RGB")

    return LoadedImage(image, path, exif, icc, original_mode)


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _to_srgb(image: Image.Image, icc: bytes) -> Image.Image:
    """Convert an embedded profile to sRGB so previews and output agree."""
    try:
        from io import BytesIO

        source = ImageCms.getOpenProfile(BytesIO(icc))
        target = ImageCms.createProfile("sRGB")
        mode = "RGBA" if _has_alpha(image) else "RGB"
        return ImageCms.profileToProfile(image, source, target, outputMode=mode)
    except Exception:
        return image


def flatten(image: Image.Image, background: str = "#000000") -> Image.Image:
    """Composite an alpha image onto a solid colour."""
    if image.mode not in ("RGBA", "LA"):
        return image.convert("RGB")
    base = Image.new("RGB", image.size, background)
    rgba = image.convert("RGBA")
    base.paste(rgba, mask=rgba.split()[-1])
    return base


def _strip_gps(exif: bytes) -> bytes | None:
    """Drop GPS IFD from an EXIF blob; return None if it cannot be parsed."""
    try:
        from PIL import Image as _Image

        parsed = _Image.Exif()
        parsed.load(exif)
        parsed.pop(0x8825, None)  # GPSInfo
        return parsed.tobytes()
    except Exception:
        return None


def resolve_output_path(
    source: Path, out_dir: Path | None, extension: str, suffix: str, policy: str
) -> Path:
    """Build the destination path, applying the overwrite policy."""
    directory = out_dir or source.parent
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{source.stem}{suffix}{extension}"

    if policy == "overwrite" or not candidate.exists():
        return candidate
    if policy == "skip":
        return candidate  # caller checks existence and skips

    index = 2
    while candidate.exists():
        candidate = directory / f"{source.stem}{suffix}_{index}{extension}"
        index += 1
    return candidate


def save(
    image: Image.Image,
    path: Path,
    fmt: str,
    *,
    jpeg_quality: int = 92,
    webp_quality: int = 90,
    webp_lossless: bool = False,
    png_compression: int = 6,
    exif: bytes | None = None,
    icc_profile: bytes | None = None,
    keep_metadata: bool = True,
    strip_gps: bool = False,
    background: str = "#000000",
) -> Path:
    """Write ``image`` to ``path`` with format-appropriate options."""
    fmt = fmt.upper()
    params: dict[str, object] = {}

    if keep_metadata and exif:
        blob = _strip_gps(exif) if strip_gps else exif
        if blob and fmt in ("JPEG", "TIFF", "WEBP", "PNG", "HEIF", "AVIF"):
            params["exif"] = blob
    if keep_metadata and icc_profile:
        params["icc_profile"] = icc_profile

    if fmt == "JPEG":
        image = flatten(image, background)
        params.update(quality=int(jpeg_quality), subsampling=0, optimize=True,
                      progressive=True)
    elif fmt == "WEBP":
        if webp_lossless:
            params.update(lossless=True, quality=100, method=6)
        else:
            params.update(quality=int(webp_quality), method=6)
    elif fmt == "PNG":
        params.update(compress_level=int(png_compression), optimize=png_compression >= 7)
    elif fmt == "TIFF":
        params.update(compression="tiff_lzw")
    elif fmt == "BMP":
        image = flatten(image, background)
    elif fmt == "ICO":
        image = image.convert("RGBA")
        edge = min(256, max(image.size))
        image = image.resize((edge, edge), Image.Resampling.LANCZOS)
    elif fmt == "AVIF":
        params.update(quality=int(webp_quality))
    elif fmt == "HEIF":
        params.update(quality=int(jpeg_quality))

    if fmt in ("JPEG", "BMP") and image.mode != "RGB":
        image = image.convert("RGB")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format=fmt, **params)
    return path
