"""Media library: uploaded images and GIFs stored under data/media."""

from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 12 * 1024 * 1024
ALLOWED = {"PNG": "png", "GIF": "gif", "JPEG": "jpg", "WEBP": "webp", "BMP": "bmp"}


class MediaLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = root / "index.json"
        self.items: dict[str, dict[str, Any]] = {}
        if self._index_path.exists():
            try:
                self.items = json.loads(self._index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.items = {}

    def _save(self) -> None:
        self._index_path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")

    def add(self, name: str, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_BYTES:
            raise ValueError(f"file too large (max {MAX_BYTES // 1024 // 1024} MB)")
        try:
            img = Image.open(io.BytesIO(data))
            img.verify()
            img = Image.open(io.BytesIO(data))
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError("not a supported image") from e
        ext = ALLOWED.get(img.format or "")
        if ext is None:
            raise ValueError(f"unsupported format {img.format}")
        mid = uuid.uuid4().hex[:10]
        (self.root / f"{mid}.{ext}").write_bytes(data)
        item = {
            "id": mid,
            "name": Path(name).stem[:60] or mid,
            "ext": ext,
            "width": img.width,
            "height": img.height,
            "frames": getattr(img, "n_frames", 1),
            "created": time.time(),
            "bytes": len(data),
        }
        self.items[mid] = item
        self._save()
        return item

    def path(self, mid: str) -> Path:
        item = self.items.get(mid)
        if not item:
            raise KeyError(mid)
        return self.root / f"{mid}.{item['ext']}"

    def read(self, mid: str) -> bytes:
        return self.path(mid).read_bytes()

    def delete(self, mid: str) -> None:
        p = self.path(mid)
        p.unlink(missing_ok=True)
        self.items.pop(mid, None)
        self._save()

    def list(self) -> list[dict[str, Any]]:
        return sorted(self.items.values(), key=lambda i: -i["created"])
