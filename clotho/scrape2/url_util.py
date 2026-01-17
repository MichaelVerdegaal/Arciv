from urllib.parse import urlparse


def split_url(url: str) -> tuple[str, str]:
    """Split the domain and the path from a URL.

    Args:
        url: The URL to extract from

    Returns:
        A tuple of (domain, path) where domain has 'www.' prefix removed
    """
    # url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    path = parsed.path
    return domain, path
