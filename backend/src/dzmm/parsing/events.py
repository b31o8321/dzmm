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


ParseEvent = NarrativeDelta | TagComplete | ParseError
