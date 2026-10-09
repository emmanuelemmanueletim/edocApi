"""Example developer application showing eDocAPI's built-in API explorer."""

from edocapi import App, Document, __version__

app = App()


@app.get("/health")
def health():
    """Check the service and list supported document types."""
    return {
        "message": f"eDocAPI v{__version__}",
        "supported_types": Document.supported_types(),
    }


@app.post("/convert")
def convert(file):
    """Convert an uploaded supported document to PDF."""
    return Document(file).to_pdf()


@app.post("/compress")
def compress(file):
    """Compress an uploaded PDF."""
    return Document(file).compress()


@app.post("/extract")
def extract(file):
    """Extract text from an uploaded document."""
    return {"text": Document(file).extract_text()}


@app.post("/info")
def info(file):
    """Read metadata from an uploaded document."""
    return Document(file).info()


@app.post("/merge")
def merge(files):
    """Merge uploaded PDF files into one PDF."""
    return Document.merge(files)
