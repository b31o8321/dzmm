from dataclasses import dataclass, field


@dataclass
class NarrativeDelta:
    text: str


@dataclass
class TagComplete:
    name: str
    attrs: dict[str, str] = field(default_factory=dict)
    content: str = ""


@dataclass
class ParseError:
    message: str
    raw: str


@dataclass
class UsageSummary:
    """Yielded as the final event from run_turn_v10 to propagate token counts.
    Not part of ParseEvent — filtered out before SSE forwarding."""
    tokens_in: int = 0
    tokens_out: int = 0


ParseEvent = NarrativeDelta | TagComplete | ParseError
