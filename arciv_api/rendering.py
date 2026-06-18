"""HTML rendering: the Jinja2 environment and safe markdown conversion."""

from typing import Any

import markdown as markdown_lib
import nh3
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config

_env = Environment(
    loader=FileSystemLoader(str(config.TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Archived markdown is derived from arbitrary scraped pages, so it is
# untrusted: render it, then sanitize. Keep the tags real articles use; drop
# scripts, event handlers, and unsafe URL schemes (nh3 does the latter).
_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "em", "h1", "h2",
    "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "li", "ol", "p", "pre",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead",
    "tr", "ul",
}  # fmt: skip
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "code": {"class"},
    "span": {"class"},
}


def render(template_name: str, **context: Any) -> str:
    """Render a Jinja template to an HTML string."""
    return _env.get_template(template_name).render(**context)


def alert_patch(target: str, message: str, kind: str) -> DatastarResponse:
    """Patch an inline validation alert into the ``target`` slot (by element id).

    The archive, source, and rule forms each keep an empty result ``<div>``; a
    failed submission patches this alert in so the entered values are not lost,
    while a successful one redirects instead.
    """
    fragment = render("partials/_alert.html", target=target, message=message, kind=kind)
    return DatastarResponse(ServerSentEventGenerator.patch_elements(fragment))


def render_markdown(text: str) -> str:
    """Convert archived markdown to sanitized HTML safe to embed."""
    html = markdown_lib.markdown(
        text, extensions=["fenced_code", "tables", "sane_lists"]
    )
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        link_rel="noopener noreferrer",
    )
