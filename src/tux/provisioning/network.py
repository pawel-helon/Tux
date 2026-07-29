"""Endpoint reachability checks."""

import urllib.error
import urllib.request

def endpoint_reachable(endpoint: str) -> bool:
    """Return whether the endpoint base URL answers an HTTP request.

    A network failure (``urllib.error.URLError`` / ``TimeoutError``, both
    ``OSError`` subclasses) means not reachable rather than an error, since this
    is only a post-pull readiness check.
    """
    try:
        with urllib.request.urlopen(f"{endpoint}/", timeout=5.0):
            return True
    except urllib.error.HTTPError:
        # An HTTP error response still proves the endpoint is answering.
        return True
    except OSError:
        return False
