"""Figure crop persistence (docs/parsing.md § Figure crops).

Crops are taken from the rendered page image at the one moment it exists — right after the
vision call, before retention deletes it — and written under the job's own directory in
`FIGURES_DIR`, named by the page and the cleaned bbox. That name is exactly what a
`sightread://` placeholder carries, so a crop is addressable without waiting for
document-wide figure ids, including from a partial result.

This is raster work on our own render (Pillow), not PDF work; the Poppler-only rule is
untouched. A crop that fails is logged and skipped — it must never fail the page.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from PIL import Image

from .markdown import BBOX_MAX, PLACEHOLDER_RE, clean_bbox

logger = logging.getLogger(__name__)

Bbox = tuple[int, int, int, int]

# Margin per side in bbox space: 2% of the page, the same margin the API docs tell
# self-cropping callers to add (docs/api.md).
CROP_MARGIN = 20

# A bbox as the figure routes receive it: `120,60,480,940`.
_BBOX_PATH_RE = re.compile(r"^(-?\d{1,5}),(-?\d{1,5}),(-?\d{1,5}),(-?\d{1,5})$")


def parse_bbox_path(raw: str) -> Bbox | None:
    """`"120,60,480,940"` → a cleaned bbox, or None when it is not one."""
    match = _BBOX_PATH_RE.match(raw)
    if match is None:
        return None
    return clean_bbox(tuple(int(group) for group in match.groups()))


def crop_path(figures_dir: Path, job_id: uuid.UUID, page: int, bbox: Bbox) -> Path:
    """Where one figure's crop lives. Deterministic from the placeholder alone."""
    y_min, x_min, y_max, x_max = bbox
    return figures_dir / str(job_id) / f"p{page}_{y_min}_{x_min}_{y_max}_{x_max}.png"


def save_page_figures(markdown: str, image_path: Path, page: int, job_dir: Path) -> int:
    """Crop every placeholder on one transcribed page from its rendered image.

    `page` is our page number, not the model's — the same renumbering `assemble` applies,
    so the stored name matches the placeholder the result will carry. Returns how many
    crops were written; failures are logged and never raised.
    """
    boxes: set[Bbox] = set()
    for match in PLACEHOLDER_RE.finditer(markdown):
        bbox = clean_bbox(
            (
                int(match.group("ymin")),
                int(match.group("xmin")),
                int(match.group("ymax")),
                int(match.group("xmax")),
            )
        )
        if bbox is not None:
            boxes.add(bbox)
    if not boxes:
        return 0

    saved = 0
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            job_dir.mkdir(parents=True, exist_ok=True)
            for bbox in boxes:
                y_min, x_min, y_max, x_max = bbox
                left = max(0, round((x_min - CROP_MARGIN) / BBOX_MAX * width))
                top = max(0, round((y_min - CROP_MARGIN) / BBOX_MAX * height))
                right = min(width, round((x_max + CROP_MARGIN) / BBOX_MAX * width))
                bottom = min(height, round((y_max + CROP_MARGIN) / BBOX_MAX * height))
                if right <= left or bottom <= top:
                    continue
                destination = job_dir / f"p{page}_{y_min}_{x_min}_{y_max}_{x_max}.png"
                image.crop((left, top, right, bottom)).save(destination, format="PNG")
                saved += 1
    except OSError:
        # Which figure failed is diagnostic; what the page shows is not logged.
        logger.warning("figure crops for page %d could not all be saved", page)
    return saved
