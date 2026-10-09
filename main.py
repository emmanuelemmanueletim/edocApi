"""Example eDocAPI application."""

from edocapi import App, Document

app = App()

@app.get("/")
def home():
    return {
        "message": "eDocAPI v0.0.2",
        "supported_types": Document.supported_types(),
    }

@app.post("/convert")
def convert(file):
    return Document(file).to_pdf()

@app.post("/compress")
def compress(file):
    return Document(file).compress()

@app.post("/extract")
def extract(file):
    return {"text": Document(file).extract_text()}

@app.post("/info")
def info(file):
    return Document(file).info()

@app.post("/merge")
def merge(files):
    return Document.merge(files)
