from edocapi.dashboard import render_dashboard


def test_dashboard_response_has_editable_document_toolbar():
    page = render_dashboard([], ["pdf"], 10_000_000)

    assert 'id="response-editor"' in page
    assert 'contenteditable="true"' in page
    assert 'id="editor-font"' in page
    assert 'id="editor-size"' in page
    assert 'data-command="justifyFull"' in page
    assert "Download formatted HTML" in page
    assert "function renderEditor" in page


def test_dashboard_displays_packaged_logo_and_favicon():
    page = render_dashboard([], ["pdf"], 10_000_000)

    assert '<img class="logo" src="data:image/png;base64,' in page
    assert 'alt="eDocAPI logo"' in page
    assert '<link rel="icon" type="image/png" href="data:image/png;base64,' in page


def test_dashboard_displays_rate_limit_metadata():
    page = render_dashboard(
        [{
            "path": "/ocr",
            "methods": ["POST"],
            "name": "ocr",
            "description": "Run OCR",
            "rate_limit": "3/minute",
            "parameters": [],
        }],
        ["pdf"],
        10_000_000,
    )
    assert "3/minute per client" in page
