"""Stage 1 (PDF): text layer extraction + page rasterization."""
from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass, field

from pypdf import PdfReader

from ..config import settings

# PDF text layers are full of typographic ligatures. Our own fixture contains
# '30% - ﬁnal' (U+FB01), which a naive /final/ regex misses completely.
# NFKC expands those; the explicit map covers a few NFKC leaves alone.
_EXTRA_LIGATURES = {
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
}


def normalize_text(text: str) -> str:
    """Expand ligatures and smart punctuation so downstream regexes can be plain."""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _EXTRA_LIGATURES.items():
        text = text.replace(src, dst)
    return text


@dataclass
class Page:
    number: int          # 1-indexed
    text: str


@dataclass
class PdfDocument:
    pages: list[Page] = field(default_factory=list)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def total_chars(self) -> int:
        return len(self.text)

    @property
    def chars_per_page(self) -> float:
        return self.total_chars / self.n_pages if self.n_pages else 0.0


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def extract_pdf(data: bytes) -> PdfDocument:
    """Pull the text layer. Returns empty-text pages for scanned PDFs, which is
    exactly what the router needs to send them down the vision path."""
    reader = PdfReader(io.BytesIO(data))
    pages = [
        Page(number=i + 1, text=normalize_text(page.extract_text() or ""))
        for i, page in enumerate(reader.pages)
    ]
    return PdfDocument(pages=pages)


def render_pages(data: bytes, dpi: int | None = None, max_pages: int = 12) -> list[bytes]:
    """Rasterize PDF pages to PNG bytes for the vision path.

    Imported lazily: a text-layer PDF never needs PyMuPDF, and keeping the
    import here means the native path doesn't pay for it.
    """
    import pymupdf

    dpi = dpi or settings.render_dpi
    out: list[bytes] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc[:max_pages]:
            pix = page.get_pixmap(dpi=dpi)
            out.append(pix.tobytes("png"))
    return out
