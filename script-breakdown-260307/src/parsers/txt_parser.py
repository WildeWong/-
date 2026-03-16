from .base import BaseParser, ParseResult


class TxtParser(BaseParser):
    """Plain text script parser with automatic encoding detection."""

    ENCODINGS = ["utf-8", "gbk", "gb2312", "gb18030", "big5", "latin-1"]

    def parse(self, file_path: str) -> ParseResult:
        text = self._read_with_fallback(file_path)
        lines = text.splitlines()
        return ParseResult(lines=lines)

    def _read_with_fallback(self, file_path: str) -> str:
        for encoding in self.ENCODINGS:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, LookupError):
                continue
        # Last resort: read as bytes and decode with replacement
        with open(file_path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".txt", ".text"]
