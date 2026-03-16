import re
from .base import BaseParser, ParseResult


class PdfParser(BaseParser):
    """PDF script parser using PyMuPDF with layout-aware cleaning."""

    # Maximum consecutive blank lines kept
    MAX_BLANK_RUN = 1

    def parse(self, file_path: str) -> ParseResult:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for .pdf parsing. Install with: pip install PyMuPDF"
            )

        doc = fitz.open(file_path)
        num_pages = doc.page_count

        # First pass: collect per-page lines (stripped)
        pages_lines: list[list[str]] = []
        for page in doc:
            text = page.get_text("text")
            page_lines = [ln.rstrip() for ln in text.splitlines()]
            pages_lines.append(page_lines)
        doc.close()

        # Detect repeated headers / footers across pages
        noise = self._detect_noise(pages_lines, num_pages)

        # Second pass: clean and flatten
        all_lines: list[str] = []
        blank_run = 0
        for page_lines in pages_lines:
            for raw_line in page_lines:
                stripped = raw_line.strip()

                # Drop confirmed noise (headers/footers)
                if stripped in noise:
                    continue

                # Drop isolated page numbers
                if self._is_page_number(stripped, num_pages):
                    continue

                is_blank = not stripped
                if is_blank:
                    blank_run += 1
                    if blank_run > self.MAX_BLANK_RUN:
                        continue  # collapse excess blank lines
                else:
                    blank_run = 0

                # Preserve the stripped line (keeps leading indent for indented scripts)
                all_lines.append(stripped if stripped else "")

        # Trim leading / trailing blank lines
        while all_lines and not all_lines[0]:
            all_lines.pop(0)
        while all_lines and not all_lines[-1]:
            all_lines.pop()

        return ParseResult(lines=all_lines)

    # ── Helpers ──────────────────────────────────────────────────

    def _detect_noise(self, pages_lines: list[list[str]], num_pages: int) -> set[str]:
        """Return a set of lines that appear repeatedly at page tops/bottoms.

        We look at the first 2 and last 2 non-empty lines of each page.
        Lines that appear on ≥ 40 % of pages (at least 2) are classified as
        headers or footers.
        """
        if num_pages < 3:
            return set()

        candidate_count: dict[str, int] = {}
        for page_lines in pages_lines:
            non_empty = [ln.strip() for ln in page_lines if ln.strip()]
            candidates = set(non_empty[:2] + non_empty[-2:])
            for cand in candidates:
                candidate_count[cand] = candidate_count.get(cand, 0) + 1

        threshold = max(2, num_pages * 0.40)
        return {ln for ln, cnt in candidate_count.items() if cnt >= threshold}

    _PAGE_NUM_RE = re.compile(r'^[-–—\s]*(\d+)[-–—\s]*$')

    def _is_page_number(self, stripped: str, num_pages: int) -> bool:
        """Return True if the line looks like a standalone page number."""
        if not stripped:
            return False
        m = self._PAGE_NUM_RE.match(stripped)
        if m:
            val = int(m.group(1))
            return 1 <= val <= num_pages * 2
        return False

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".pdf"]
