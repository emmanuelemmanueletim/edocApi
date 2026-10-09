"""Default eDocAPI application: the user-facing landing page and tools."""

# Keep ``edocapi run`` pointed at the first app users should see.
from webapp.main import app

__all__ = ["app"]
