class ReferenceSourceError(Exception):
    """Base error for external reference sources."""


class SourceUnavailable(ReferenceSourceError):
    """The site cannot be read (blocked, needs JavaScript, HTTP error)."""


class ParseError(ReferenceSourceError):
    """The response was readable but not in the expected structure; nothing is saved."""
