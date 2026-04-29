import re

from dzmm.parsing.events import NarrativeDelta, ParseError, ParseEvent, TagComplete

KNOWN_TAGS: set[str] = {
    "narrative",
    "dice",
    "state_change",
    "npc_update",
    "plot_event",
    "choices",
    "recall",
}
STREAMING_TAGS: set[str] = {"narrative"}

_OPEN_TAG_RE = re.compile(r"<(\w+)((?:\s+\w+=\"[^\"]*\")*)\s*(/?)>")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


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
                close_tok = f"</{self._current_tag}>"
                idx = self._buf.find(close_tok)
                if idx == -1:
                    safe_len = max(0, len(self._buf) - len(close_tok))
                    safe = self._buf[:safe_len]
                    if safe:
                        if self._state == "IN_STREAMING":
                            events.append(NarrativeDelta(safe))
                            self._tag_buf += safe
                        elif self._state == "IN_BUFFERED":
                            self._tag_buf += safe
                        self._buf = self._buf[safe_len:]
                    break
                else:
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
                    self._buf = self._buf[idx + len(close_tok):]
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
