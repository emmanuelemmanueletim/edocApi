"""Minimal pure-Python ASGI / HTTP primitives used by eDocAPI App."""

from edocapi.http.request import Request
from edocapi.http.multipart import parse_multipart

__all__ = ["Request", "parse_multipart"]
