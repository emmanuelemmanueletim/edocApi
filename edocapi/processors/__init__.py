"""Document processors  import side-effects register the processors."""

from edocapi.processors.base import (
    BaseProcessor,
    get_processor_class,
    list_supported_types,
    register_processor,
)
from edocapi.processors import pdf, docx, html, markdown, image, txt  # noqa: F401

__all__ = [
    "BaseProcessor",
    "get_processor_class",
    "list_supported_types",
    "register_processor",
]
