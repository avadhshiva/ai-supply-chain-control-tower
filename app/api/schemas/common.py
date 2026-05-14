from __future__ import annotations

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def page_to_offset(page: int, page_size: int) -> int:
    return max(0, (page - 1) * page_size)


class PageParams:
    """Resolved pagination for list endpoints."""

    __slots__ = ("page", "page_size", "offset")

    def __init__(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        self.page = page
        self.page_size = page_size
        self.offset = page_to_offset(page, page_size)
