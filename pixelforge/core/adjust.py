"""Tone, colour and detail adjustments applied after upscaling."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .models import Adjustments

_SEPIA_MATRIX = (
    0.393, 0.769, 0.189, 0,
    0.349, 0.686, 0.168, 0,
    0.272, 0.534, 0.131, 0,
)


def apply(image: Image.Image, adj: Adjustments) -> Image.Image:
    """Run the full adjustment chain. Order matters and is fixed here."""
    if adj.is_identity():
        return image

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB")

    if adj.auto_contrast:
        rgb = ImageOps.autocontrast(rgb, cutoff=0.5)
    if adj.equalize:
        rgb = ImageOps.equalize(rgb)
    if adj.gamma != 1.0:
        rgb = _gamma(rgb, adj.gamma)
    if adj.temperature or adj.tint:
        rgb = _white_balance(rgb, adj.temperature, adj.tint)
    if adj.brightness != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(adj.brightness)
    if adj.contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(adj.contrast)
    if adj.saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(adj.saturation)
    if adj.denoise > 0:
        rgb = _denoise(rgb, adj.denoise)
    if adj.blur > 0:
        rgb = rgb.filter(ImageFilter.GaussianBlur(radius=adj.blur))
    if adj.sharpness != 1.0:
        rgb = ImageEnhance.Sharpness(rgb).enhance(adj.sharpness)
    if adj.unsharp_amount > 0:
        rgb = rgb.filter(
            ImageFilter.UnsharpMask(
                radius=max(0.1, adj.unsharp_radius),
                percent=int(adj.unsharp_amount),
                threshold=3,
            )
        )
    if adj.grayscale:
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    if adj.sepia:
        rgb = rgb.convert("RGB", _SEPIA_MATRIX)
    if adj.invert:
        rgb = ImageOps.invert(rgb)
    if adj.vignette > 0:
        rgb = _vignette(rgb, adj.vignette)

    if alpha is not None:
        rgb = rgb.convert("RGBA")
        rgb.putalpha(alpha)
    return rgb


def _gamma(image: Image.Image, gamma: float) -> Image.Image:
    inv = 1.0 / max(0.01, gamma)
    table = [min(255, int((i / 255.0) ** inv * 255 + 0.5)) for i in range(256)]
    return image.point(table * len(image.getbands()))


def _white_balance(image: Image.Image, temperature: float, tint: float) -> Image.Image:
    """Cheap but predictable RGB gain balance.

    ``temperature`` +100 pushes warm (more red, less blue); ``tint`` +100 pushes
    magenta (less green).
    """
    warm = temperature / 100.0
    magenta = tint / 100.0
    gains = (
        1.0 + 0.30 * warm,
        1.0 - 0.18 * magenta,
        1.0 - 0.30 * warm + 0.10 * magenta,
    )
    channels = []
    for channel, gain in zip(image.split(), gains, strict=False):
        table = [min(255, max(0, int(i * gain))) for i in range(256)]
        channels.append(channel.point(table))
    return Image.merge("RGB", channels)


def _denoise(image: Image.Image, strength: float) -> Image.Image:
    """Edge-preserving smoothing: blend a median-filtered copy back in."""
    radius = 1 if strength < 50 else 2
    smoothed = image.filter(ImageFilter.MedianFilter(size=radius * 2 + 1))
    return Image.blend(image, smoothed, min(1.0, strength / 100.0))


def _vignette(image: Image.Image, strength: float) -> Image.Image:
    width, height = image.size
    yy, xx = np.mgrid[0:height, 0:width]
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    radius = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    amount = min(1.0, strength / 100.0)
    mask = np.clip(1.0 - amount * np.clip(radius - 0.45, 0, None) / 0.85, 0.0, 1.0)
    data = np.asarray(image, dtype=np.float32)
    data *= mask[..., None]
    return Image.fromarray(np.clip(data, 0, 255).astype(np.uint8), "RGB")
