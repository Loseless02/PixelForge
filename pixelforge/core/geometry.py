"""Resolution math.

The AI models only know fixed integer factors (x2/x3/x4), but users want
arbitrary output sizes. The strategy is always the same:

1. work out the exact target box from the user's settings,
2. ask the AI backend for the *smallest* factor chain that reaches or exceeds
   that box,
3. resample down to the exact box with Lanczos.

Downscaling a super-resolved image is what keeps arbitrary targets sharp;
going the other way (AI-upscale then stretch up) would just blur.
"""

from __future__ import annotations

import math

from .models import EditSettings, FitMode, SizeMode

MAX_PIXELS = 120_000_000  # ~120 MP guard rail, keeps RAM sane
MAX_EDGE = 32_768


def source_after_transform(
    width: int, height: int, settings: EditSettings
) -> tuple[int, int]:
    """Size of the source after crop + rotation, before any scaling."""
    if not settings.crop.is_empty:
        crop = settings.crop.clamped(width, height)
        width, height = crop.width, crop.height
    if settings.rotation in (90, 270):
        width, height = height, width
    return width, height


def resolve_target(width: int, height: int, settings: EditSettings) -> tuple[int, int]:
    """Final output size in pixels for a source of ``width`` x ``height``.

    ``width``/``height`` must already account for crop and rotation.
    """
    mode = settings.size_mode
    if mode is SizeMode.SCALE:
        tw, th = round(width * settings.scale), round(height * settings.scale)
    elif mode is SizeMode.PERCENT:
        factor = settings.percent / 100.0
        tw, th = round(width * factor), round(height * factor)
    elif mode is SizeMode.LONG_EDGE:
        edge = max(1, settings.long_edge)
        if width >= height:
            tw = edge
            th = max(1, round(height * edge / width))
        else:
            th = edge
            tw = max(1, round(width * edge / height))
    else:  # EXACT
        tw, th = settings.target_width, settings.target_height
        if settings.fit_mode is FitMode.CONTAIN:
            tw, th = _contain(width, height, tw, th)
    return clamp_size(tw, th)


def clamp_size(width: int, height: int) -> tuple[int, int]:
    """Keep a requested size inside sane memory/edge limits, aspect preserved."""
    width = max(1, min(int(width), MAX_EDGE))
    height = max(1, min(int(height), MAX_EDGE))
    pixels = width * height
    if pixels > MAX_PIXELS:
        factor = math.sqrt(MAX_PIXELS / pixels)
        width = max(1, int(width * factor))
        height = max(1, int(height * factor))
    return width, height


def _contain(src_w: int, src_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    factor = min(box_w / src_w, box_h / src_h)
    return max(1, round(src_w * factor)), max(1, round(src_h * factor))


def _cover(src_w: int, src_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    factor = max(box_w / src_w, box_h / src_h)
    return max(1, round(src_w * factor)), max(1, round(src_h * factor))


def fit_plan(
    src_w: int, src_h: int, target_w: int, target_h: int, mode: FitMode
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Resolve a fit mode into concrete steps.

    Returns ``(resize_to, canvas, paste_offset)``:

    * ``resize_to``  — size to resample the image to
    * ``canvas``     — size of the final output image
    * ``paste_offset`` — where the resized image sits on the canvas. Negative
      values mean the image overflows and gets cropped (COVER).
    """
    if mode is FitMode.STRETCH:
        return (target_w, target_h), (target_w, target_h), (0, 0)

    if mode is FitMode.CONTAIN:
        resize_to = _contain(src_w, src_h, target_w, target_h)
        return resize_to, resize_to, (0, 0)

    if mode is FitMode.PAD:
        resize_to = _contain(src_w, src_h, target_w, target_h)
        offset = ((target_w - resize_to[0]) // 2, (target_h - resize_to[1]) // 2)
        return resize_to, (target_w, target_h), offset

    resize_to = _cover(src_w, src_h, target_w, target_h)
    offset = ((target_w - resize_to[0]) // 2, (target_h - resize_to[1]) // 2)
    return resize_to, (target_w, target_h), offset


def plan_ai_factor(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    available: tuple[int, ...] = (2, 3, 4),
    max_chain: int = 2,
    oversample: float = 1.0,
) -> list[int]:
    """Smallest chain of AI passes whose product covers the requested growth.

    ``[]`` means the target is not larger than the source, so no AI pass is
    worth running — plain resampling handles it.

    ``oversample`` deliberately overshoots: rendering above the target and
    resampling back down is supersampling, which averages away the model's
    per-pixel guesses and leaves cleaner edges. It costs a whole extra pass.

    >>> plan_ai_factor(400, 600, 1200, 720)
    [3]
    >>> plan_ai_factor(400, 600, 3840, 2160)
    [3, 4]
    >>> plan_ai_factor(200, 200, 3200, 3200)
    [4, 4]
    """
    needed = max(target_w / src_w, target_h / src_h) * max(1.0, oversample)
    if needed <= 1.0:
        return []

    best: list[int] | None = None
    options = sorted(set(available))

    def walk(chain: list[int], product: float) -> None:
        nonlocal best
        if product >= needed:
            if best is None or product < math.prod(best):
                best = list(chain)
            return
        if len(chain) >= max_chain:
            return
        for factor in options:
            walk([*chain, factor], product * factor)

    walk([], 1.0)
    if best is None:
        # Beyond what the chain can reach: use the largest factor repeatedly.
        top = options[-1]
        count = min(max_chain, max(1, math.ceil(math.log(needed, top))))
        best = [top] * count
    return best


def plan_pixels(src_w: int, src_h: int, factors: list[int]) -> int:
    """Peak pixel count the AI chain will hold in memory."""
    product = math.prod(factors) if factors else 1
    return src_w * product * src_h * product


def describe_plan(
    src_w: int, src_h: int, settings: EditSettings, ai_factors: list[int]
) -> str:
    """Human-readable one-liner for the status bar."""
    tw, th = resolve_target(src_w, src_h, settings)
    if not ai_factors:
        return f"{src_w}x{src_h} to {tw}x{th} (resample only)"
    chain = " to ".join(f"x{f}" for f in ai_factors)
    intermediate = math.prod(ai_factors)
    return (
        f"{src_w}x{src_h} to {tw}x{th} "
        f"(AI {chain} = {src_w * intermediate}x{src_h * intermediate}, then resample)"
    )
