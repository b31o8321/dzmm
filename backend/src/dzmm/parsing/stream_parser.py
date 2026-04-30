import re
from difflib import SequenceMatcher

from dzmm.parsing.events import NarrativeDelta, ParseError, ParseEvent, TagComplete

KNOWN_TAGS: set[str] = {
    "narrative",
    "dice",
    "state_change",
    "npc_update",
    "plot_event",
    "choices",
    "character_xp",
    "recall",
    "era_begin",
    "pc_goal",
    "pc_mood",
    "npc_relation",
    "hidden_event",
    "say",
    "pc_action",
    "scene_shift",
    # v0.1.0 — screenplay-driven tags
    "chapter_advance",
    "event_complete",
    "plot_turn",
    "ending",
}
STREAMING_TAGS: set[str] = {"narrative"}

_OPEN_TAG_RE = re.compile(r"<(\w+)((?:\s+\w+=\"[^\"]*\")*)\s*(/?)>")
_CLOSE_TAG_RE = re.compile(r"</(\w+)\s*>")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two short strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,        # insertion
                prev[j] + 1,            # deletion
                prev[j - 1] + cost,     # substitution
            )
        prev = curr
    return prev[-1]


def _is_typo_close(opened: str, found: str) -> bool:
    """Heuristic: would `</found>` reasonably be intended as `</opened>`?

    Triggers when both:
      - SequenceMatcher ratio >= 0.7 (~70% common-character similarity)
      - Levenshtein distance <= 2

    Pure equality is handled by the caller; we only run when opened != found.
    """
    if not opened or not found:
        return False
    if opened == found:
        return False
    # Cheap length-gap rejection: if a typo fix is more than 2 edits away by
    # length alone, no chance.
    if abs(len(opened) - len(found)) > 2:
        return False
    ratio = SequenceMatcher(None, opened, found).ratio()
    if ratio < 0.7:
        return False
    return _edit_distance(opened, found) <= 2


class StreamingTagParser:
    """Incrementally parses a flat sequence of <tag>...</tag> blocks from an
    LLM stream. Emits NarrativeDelta live for narrative content; buffers other
    known tags until close. Unknown tags and inter-tag text are dropped."""

    def __init__(self) -> None:
        self._buf: str = ""
        self._state: str = "OUTSIDE"
        self._current_tag: str | None = None
        self._current_attrs: dict[str, str] = {}
        self._tag_buf: str = ""

    def feed(self, chunk: str) -> list[ParseEvent]:
        self._buf += chunk
        events: list[ParseEvent] = []
        while True:
            consumed = False
            if self._state == "OUTSIDE":
                m = _OPEN_TAG_RE.search(self._buf)
                if not m:
                    if "<" not in self._buf:
                        self._buf = ""
                    break
                tag = m.group(1).lower()
                attrs_str = m.group(2) or ""
                self_close = m.group(3) == "/"
                self._current_tag = tag
                self._current_attrs = dict(_ATTR_RE.findall(attrs_str))
                self._tag_buf = ""
                self._buf = self._buf[m.end():]

                if self_close:
                    if tag in KNOWN_TAGS:
                        events.append(TagComplete(
                            name=tag,
                            attrs=self._current_attrs,
                            content="",
                        ))
                    self._state = "OUTSIDE"
                    self._current_tag = None
                    self._current_attrs = {}
                elif tag in STREAMING_TAGS:
                    self._state = "IN_STREAMING"
                elif tag in KNOWN_TAGS:
                    self._state = "IN_BUFFERED"
                else:
                    self._state = "IN_UNKNOWN"
                consumed = True

            elif self._state in ("IN_STREAMING", "IN_BUFFERED", "IN_UNKNOWN"):
                # Find the next close tag of *any* name, so we can detect
                # typo close tags like `</narriative>` matching an opened
                # `<narrative>`. We restrict typo recovery to the IN_STREAMING
                # and IN_BUFFERED states (known tags); IN_UNKNOWN keeps the
                # original strict semantics.
                exact_close = f"</{self._current_tag}>"
                exact_idx = self._buf.find(exact_close)

                typo_idx = -1
                typo_close: str = ""
                typo_found_name: str = ""
                if self._state in ("IN_STREAMING", "IN_BUFFERED"):
                    for cm in _CLOSE_TAG_RE.finditer(self._buf):
                        found = cm.group(1).lower()
                        # Skip the exact match (already handled above) and
                        # any other open-known-tag's close (it's not ours).
                        if found == self._current_tag:
                            continue
                        if _is_typo_close(self._current_tag or "", found):
                            typo_idx = cm.start()
                            typo_close = cm.group(0)
                            typo_found_name = found
                            break

                # Pick whichever close comes first.
                if exact_idx == -1 and typo_idx == -1:
                    # No close found yet. Hold back enough buffer to avoid
                    # splitting either an exact close or a plausible typo
                    # close across feed boundaries (typo closes can be up to
                    # 2 chars longer than the exact close).
                    hold = len(exact_close) + 2
                    safe_len = max(0, len(self._buf) - hold)
                    if safe_len > 0:
                        safe = self._buf[:safe_len]
                        if self._state == "IN_STREAMING":
                            events.append(NarrativeDelta(safe))
                            self._tag_buf += safe
                        elif self._state == "IN_BUFFERED":
                            self._tag_buf += safe
                        # IN_UNKNOWN: drop silently (preserves prior behavior).
                        self._buf = self._buf[safe_len:]
                    break

                use_typo = (
                    typo_idx != -1
                    and (exact_idx == -1 or typo_idx < exact_idx)
                )
                if use_typo:
                    idx = typo_idx
                    close_len = len(typo_close)
                else:
                    idx = exact_idx
                    close_len = len(exact_close)

                inner = self._buf[:idx]
                if self._state == "IN_STREAMING" and inner:
                    events.append(NarrativeDelta(inner))
                elif self._state == "IN_BUFFERED":
                    self._tag_buf += inner
                    events.append(TagComplete(
                        name=self._current_tag or "",
                        attrs=self._current_attrs,
                        content=self._tag_buf.strip(),
                    ))
                if use_typo:
                    events.append(ParseError(
                        message=(
                            f"close-tag typo: </{typo_found_name}> "
                            f"matched as </{self._current_tag}>"
                        ),
                        raw=typo_close,
                    ))
                self._buf = self._buf[idx + close_len:]
                self._state = "OUTSIDE"
                self._current_tag = None
                self._current_attrs = {}
                self._tag_buf = ""
                consumed = True

            if not consumed:
                break
        return events

    def finish(self) -> list[ParseEvent]:
        events: list[ParseEvent] = []
        if self._state == "IN_STREAMING":
            residual = self._tag_buf + self._buf
            if residual:
                events.append(NarrativeDelta(residual))
        elif self._state == "IN_BUFFERED":
            events.append(ParseError(
                message=f"Unclosed tag <{self._current_tag}>",
                raw=self._tag_buf + self._buf,
            ))
        self._buf = ""
        self._state = "OUTSIDE"
        self._current_tag = None
        self._current_attrs = {}
        self._tag_buf = ""
        return events
