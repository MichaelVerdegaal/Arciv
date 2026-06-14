"""Pydantic response models for the API.

The API returns data, not presentation: a page body is the raw markdown the
frontend renders to HTML. ``state`` is the derived done/failed/pending triad
(see ``arciv`` ``Page.state``), never a stored column.
"""

from typing import Self

from pydantic import BaseModel

from arciv.db import Page


class PageSummary(BaseModel):
    """One row in the browse list."""

    slug: str
    url: str
    title: str | None
    domain: str
    word_count: int
    fetched_at: str | None
    state: str

    @classmethod
    def from_page(cls, page: Page) -> Self:
        return cls(
            slug=page.slug,
            url=page.url,
            title=page.title,
            domain=page.domain,
            word_count=page.word_count,
            fetched_at=page.fetched_at,
            state=page.state,
        )


class PageList(BaseModel):
    """A page of browse results plus the cursor that produced it."""

    items: list[PageSummary]
    limit: int
    offset: int
    has_more: bool


class PageDetail(BaseModel):
    """A single page: durable metadata, the markdown body, and provenance."""

    slug: str
    url: str
    original_url: str
    domain: str
    title: str | None
    author: str | None
    content_type: str | None
    word_count: int
    state: str
    fail_reason: str | None
    added_at: str | None
    fetched_at: str | None
    parsed_at: str | None
    markdown: str | None
    sources: list[str]

    @classmethod
    def from_page(cls, page: Page, markdown: str | None, sources: list[str]) -> Self:
        return cls(
            slug=page.slug,
            url=page.url,
            original_url=page.original_url,
            domain=page.domain,
            title=page.title,
            author=page.author,
            content_type=page.content_type,
            word_count=page.word_count,
            state=page.state,
            fail_reason=page.fail_reason,
            added_at=page.added_at,
            fetched_at=page.fetched_at,
            parsed_at=page.parsed_at,
            markdown=markdown,
            sources=sources,
        )


class DomainCount(BaseModel):
    """A domain and how many archived pages it has."""

    domain: str
    count: int


class DomainList(BaseModel):
    domains: list[DomainCount]
