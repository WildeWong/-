from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    """Result of parsing a script file."""
    lines: list[str]                          # text lines
    metadata: dict[str, str] = field(default_factory=dict)
    # Per-line metadata (e.g. FDX paragraph types). Key = line index.
    line_metadata: dict[int, dict[str, str]] = field(default_factory=dict)


class BaseParser(ABC):
    """Abstract base class for script file parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """Parse a script file and return structured text lines.

        Args:
            file_path: Path to the script file.

        Returns:
            ParseResult with lines and optional metadata.
        """
        ...

    @staticmethod
    def supported_extensions() -> list[str]:
        """Return list of supported file extensions (e.g. ['.txt'])."""
        return []
