from .base import BaseParser, ParseResult


class FdxParser(BaseParser):
    """Final Draft XML (.fdx) script parser."""

    def parse(self, file_path: str) -> ParseResult:
        try:
            from lxml import etree
        except ImportError:
            raise ImportError("lxml is required for .fdx parsing. Install with: pip install lxml")

        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        tree = etree.parse(file_path, parser=parser)
        root = tree.getroot()

        lines = []
        line_metadata: dict[int, dict[str, str]] = {}

        # FDX uses <Content><Paragraph> structure
        for para in root.iter("Paragraph"):
            para_type = para.get("Type", "")
            # Extract all text from child <Text> elements
            texts = []
            for text_elem in para.iter("Text"):
                if text_elem.text:
                    texts.append(text_elem.text)
            line_text = "".join(texts).strip()

            line_idx = len(lines)
            lines.append(line_text)

            if para_type:
                line_metadata[line_idx] = {"type": para_type}

        metadata = {}
        # Extract document-level metadata if available
        title_page = root.find(".//TitlePage")
        if title_page is not None:
            for content in title_page.iter("Content"):
                for para in content.iter("Paragraph"):
                    texts = []
                    for t in para.iter("Text"):
                        if t.text:
                            texts.append(t.text)
                    text = "".join(texts).strip()
                    if text:
                        metadata.setdefault("title_page", "")
                        metadata["title_page"] += text + "\n"

        return ParseResult(lines=lines, metadata=metadata, line_metadata=line_metadata)

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".fdx"]
