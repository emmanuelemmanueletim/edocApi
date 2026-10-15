"""Built-in document processors.

Importing this package registers all processors with the global registry.
"""

from edocapi.processors import pdf, docx, html, markdown, txt, image, simple_pdf  # noqa: F401

__all__ = [
    "pdf",
    "docx",
    "html",
    "markdown",
    "txt",
    "image",
    "simple_pdf",
]
