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
