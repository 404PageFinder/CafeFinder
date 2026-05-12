"""OCR service abstraction.

Phase 2: PaddleOCR is the only backend.
Future: Google Vision can be added as a fallback when PaddleOCR confidence
is below a threshold. The OCRService protocol is designed so backends are
swappable behind a single interface.

PaddleOCR is loaded lazily on first use because:
1. Cold-start cost (~3-5s) shouldn't block app startup
2. The model files (~300MB) only download on first invocation
3. Tests can mock the engine without triggering a real load
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class OCRResult:
    """Combined OCR output from one image."""
    text_lines: list[str] = field(default_factory=list)
    full_text: str = ""
    avg_confidence: float = 0.0
    backend: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_low_confidence(self) -> bool:
        """Threshold below which we'd want to fall back to a stronger OCR."""
        return self.avg_confidence < 0.6 or len(self.full_text.strip()) < 5


class OCRBackend(Protocol):
    """Pluggable OCR backend interface."""
    name: str

    async def extract(self, image_path: str) -> OCRResult: ...


class PaddleOCRBackend:
    """PaddleOCR backend.

    Loads the model lazily on first call. Subsequent calls reuse the
    cached engine instance.
    """
    name = "paddleocr"

    def __init__(self, lang: str = "en", use_angle_cls: bool = True):
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            try:
                # Heavy import — only on first use
                from paddleocr import PaddleOCR
            except ImportError as e:
                raise OCRError(
                    "paddleocr is not installed. Install with: "
                    "pip install paddleocr paddlepaddle"
                ) from e
            log.info("Loading PaddleOCR engine (lang=%s)", self.lang)
            self._engine = PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                show_log=False,
            )
        return self._engine

    async def extract(self, image_path: str) -> OCRResult:
        # PaddleOCR is sync and CPU-bound; run in a thread to avoid
        # blocking the event loop.
        import asyncio
        engine = self._get_engine()
        result = await asyncio.to_thread(engine.ocr, image_path, cls=self.use_angle_cls)
        return _parse_paddle_result(result, backend=self.name)


def _parse_paddle_result(raw, backend: str) -> OCRResult:
    """Normalize PaddleOCR's nested list output into our OCRResult schema.

    PaddleOCR output shape varies by version; this handles both:
    - v2.x: [[ [box, (text, conf)], ... ]]
    - v3.x: [[ [box, text, conf], ... ]]
    """
    text_lines: list[str] = []
    confidences: list[float] = []

    if not raw or not raw[0]:
        return OCRResult(backend=backend, raw={"empty": True})

    for line in raw[0]:
        try:
            # Expected shape: [box_coords, (text, conf)] or [box_coords, text, conf]
            payload = line[1]
            if isinstance(payload, (tuple, list)) and len(payload) == 2:
                text, conf = payload[0], payload[1]
            elif len(line) >= 3:
                text, conf = line[1], line[2]
            else:
                continue
            if text and isinstance(text, str):
                text_lines.append(text.strip())
                if isinstance(conf, (int, float)):
                    confidences.append(float(conf))
        except (IndexError, TypeError, ValueError):
            continue

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    full = "\n".join(text_lines)
    return OCRResult(
        text_lines=text_lines,
        full_text=full,
        avg_confidence=round(avg_conf, 3),
        backend=backend,
    )


class OCRError(Exception):
    pass


# Module-level singleton — created on first import, model loaded on first call
_default_backend: OCRBackend | None = None


def get_default_backend() -> OCRBackend:
    global _default_backend
    if _default_backend is None:
        _default_backend = PaddleOCRBackend(lang="en")
    return _default_backend


async def extract_text(image_path: str, backend: OCRBackend | None = None) -> OCRResult:
    """Public entry point. Pass a custom backend in tests."""
    be = backend or get_default_backend()
    try:
        return await be.extract(image_path)
    except OCRError:
        raise
    except Exception as e:
        log.exception("OCR backend '%s' crashed", be.name)
        raise OCRError(f"OCR failed: {e}") from e
