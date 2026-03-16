"""Rule-based scene detector for screenplays."""
from ..parsers.base import ParseResult
from .models import Scene, SceneList
from .patterns import PatternMatch, match_all_patterns, parse_heading_fields


class SceneDetector:
    """Detects scene boundaries in screenplay text using regex patterns."""

    def detect(self, parse_result: ParseResult) -> SceneList:
        """Detect scenes from parsed script text.

        Args:
            parse_result: ParseResult from any parser.

        Returns:
            SceneList containing detected scenes.
        """
        lines = parse_result.lines

        # First try FDX metadata if available
        matches = self._detect_from_fdx_metadata(lines, parse_result.line_metadata)

        # If no FDX metadata matches, fall back to pattern matching
        if not matches:
            matches = self._detect_from_patterns(lines)

        return self._build_scene_list(matches, lines)

    def _detect_from_fdx_metadata(
        self, lines: list[str], line_metadata: dict[int, dict[str, str]]
    ) -> list[PatternMatch]:
        """Detect scenes using FDX paragraph type metadata."""
        if not line_metadata:
            return []

        matches = []
        for line_idx, meta in sorted(line_metadata.items()):
            if meta.get("type") == "Scene Heading":
                heading = lines[line_idx] if line_idx < len(lines) else ""
                # If LLM-extracted fields are already stored in metadata, use them directly
                stored_int_ext = meta.get("int_ext", "")
                stored_location = meta.get("location", "")
                stored_time_of_day = meta.get("time_of_day", "")
                if stored_int_ext or stored_location or stored_time_of_day:
                    matches.append(PatternMatch(
                        line_index=line_idx,
                        heading=heading.strip(),
                        int_ext=stored_int_ext,
                        location=stored_location,
                        time_of_day=stored_time_of_day,
                        confidence=1.0,
                        pattern_name="PDF_LLM_METADATA",
                    ))
                else:
                    # Try to parse the heading for structured info (FDX format)
                    pattern_match = match_all_patterns(heading, line_idx)
                    if pattern_match:
                        pattern_match.confidence = 1.0
                        pattern_match.pattern_name = "FDX_METADATA"
                        matches.append(pattern_match)
                    else:
                        matches.append(PatternMatch(
                            line_index=line_idx,
                            heading=heading.strip(),
                            int_ext="", location=heading.strip(), time_of_day="",
                            confidence=1.0, pattern_name="FDX_METADATA",
                        ))
        return matches

    def _detect_from_patterns(self, lines: list[str]) -> list[PatternMatch]:
        """Detect scenes using regex pattern matching with false-positive filtering."""
        raw_matches = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # Skip lines that are too long to be scene headings (> 100 chars)
            if len(stripped) > 100:
                continue
            m = match_all_patterns(line, i)
            if m:
                # Reject if parsed location is implausibly long
                if m.location and len(m.location) > 40:
                    continue
                # When a scene heading has no int_ext, the location/time info is
                # likely on the very next line.  This is a common Chinese TV-script
                # convention, e.g.:
                #   "2-10."          → next line "高龙城银行外日"
                #   "2-8.高龙城"     → next line "外日"   (int_ext+time only)
                #   "2-10" (bare)    → next line "内景，医院，日"
                if not m.int_ext:
                    next_idx = i + 1
                    while next_idx < len(lines) and not lines[next_idx].strip():
                        next_idx += 1
                    if next_idx < len(lines):
                        next_line = lines[next_idx].strip()
                        if next_line and len(next_line) <= 40:
                            fields = parse_heading_fields(next_line)
                            # Accept if the next line yields int_ext or time_of_day —
                            # those are reliable signals it is a location line, not
                            # dialogue.  Merge: next-line fields win; fall back to
                            # whatever the heading line already had.
                            if fields["int_ext"] or fields["time_of_day"]:
                                m = PatternMatch(
                                    line_index=m.line_index,
                                    heading=m.heading,
                                    int_ext=fields["int_ext"] or m.int_ext,
                                    location=fields["location"] or m.location,
                                    time_of_day=fields["time_of_day"] or m.time_of_day,
                                    confidence=m.confidence,
                                    pattern_name=m.pattern_name,
                                )
                raw_matches.append(m)

        return self._filter_false_positives(raw_matches, lines)

    def _filter_false_positives(
        self, matches: list[PatternMatch], lines: list[str]
    ) -> list[PatternMatch]:
        """Remove likely false-positive scene headings.

        Heuristics applied:
        1. If >30 % of non-empty lines match, keep only high-confidence (≥ 0.85) ones
           (protects against numbered-paragraph scripts).
        2. Remove matches where fewer than 3 lines separate them from the next match
           AND both are low-confidence — densely packed "headings" are usually not headings.
        """
        if not matches:
            return matches

        non_empty = sum(1 for l in lines if l.strip())
        ratio = len(matches) / max(1, non_empty)

        if ratio > 0.30:
            # Too many hits — raise the bar
            matches = [m for m in matches if m.confidence >= 0.85]

        if len(matches) < 2:
            return matches

        # Filter densely-packed low-confidence pairs
        filtered: list[PatternMatch] = [matches[0]]
        for i in range(1, len(matches)):
            prev = filtered[-1]
            cur = matches[i]
            gap = cur.line_index - prev.line_index
            # If both are low-confidence and extremely close, drop the current one
            if gap < 3 and cur.confidence < 0.85 and prev.confidence < 0.85:
                continue
            filtered.append(cur)

        return filtered

    def _build_scene_list(
        self, matches: list[PatternMatch], lines: list[str]
    ) -> SceneList:
        """Build a SceneList from detected pattern matches."""
        if not matches:
            # No scenes detected — treat entire text as one scene
            if lines:
                scene = Scene(
                    scene_number=1,
                    heading="(Undetected)",
                    start_line=0,
                    end_line=len(lines),
                    content="\n".join(lines),
                    confidence=0.0,
                )
                return SceneList([scene])
            return SceneList()

        scenes: list[Scene] = []
        total_lines = len(lines)

        for i, m in enumerate(matches):
            end_line = matches[i + 1].line_index if i + 1 < len(matches) else total_lines
            content = "\n".join(lines[m.line_index:end_line])

            scene = Scene(
                scene_number=i + 1,
                heading=m.heading,
                location=m.location,
                time_of_day=m.time_of_day,
                int_ext=m.int_ext,
                start_line=m.line_index,
                end_line=end_line,
                content=content,
                confidence=m.confidence,
            )
            scenes.append(scene)

        # If first scene doesn't start at line 0, prepend a preamble scene
        if scenes and scenes[0].start_line > 0:
            preamble = Scene(
                scene_number=0,
                heading="(Preamble)",
                start_line=0,
                end_line=scenes[0].start_line,
                content="\n".join(lines[0:scenes[0].start_line]),
                confidence=0.5,
            )
            scenes.insert(0, preamble)

        scene_list = SceneList(scenes)
        scene_list._renumber()
        return scene_list
