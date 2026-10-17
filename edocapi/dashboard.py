"""Interactive developer dashboard (pure HTML, real fonts, logo-based colors)."""

from __future__ import annotations

from typing import Any, Sequence
from html import escape


def render_dashboard(
    routes: Sequence[dict[str, Any]],
    supported_types: Sequence[str],
    max_file_size: int,
) -> str:
    """Return the interactive eDocAPI dashboard for exploring document routes."""
    max_mb = max_file_size / (1024 * 1024)
    type_list = escape(", ".join(supported_types) or "none")

    route_cards = []
    for idx, r in enumerate(routes):
        has_upload = any(p.get("kind") == "upload" for p in r.get("parameters", []))
        form_method = "POST" if has_upload else (
            "GET" if "GET" in r["methods"] else r["methods"][0]
        )
        methods = " ".join(
            f'<span class="method method-{escape(m.lower(), quote=True)}">{escape(m)}</span>' for m in r["methods"]
        )
        rate_limit = (
            f'<span class="rate-limit">{escape(str(r["rate_limit"]))} per client</span>'
            if r.get("rate_limit") else ""
        )
        params_html = ""
        for p in r.get("parameters", []):
            req = "required" if p["required"] else "optional"
            kind = p["kind"]
            safe_name = escape(str(p["name"]), quote=True)
            safe_kind = escape(str(kind))
            if kind == "upload":
                input_html = (
                    f'<input type="file" name="{safe_name}" '
                    f'{"multiple" if p.get("multiple") else ""} '
                    f'{"required" if p["required"] else ""}>'
                )
            elif p.get("choices"):
                options_html = []
                for option in p["choices"]:
                    value = escape(str(option["value"]), quote=True)
                    label = escape(str(option["label"]))
                    selected = "selected" if value == str(p.get("default")) else ""
                    disabled = "disabled" if option.get("disabled") else ""
                    options_html.append(
                        f'<option value="{value}" {selected} {disabled}>{label}</option>'
                    )
                input_html = (
                    f'<select class="param-control" name="{safe_name}">'
                    f'{"".join(options_html)}</select>'
                )
            else:
                default_value = escape(str(p.get("default") or ""), quote=True)
                input_html = (
                    f'<input type="text" name="{safe_name}" '
                    f'value="{default_value}" placeholder="{safe_name}" '
                    f'{"required" if p["required"] else ""}>'
                )
            help_html = (
                f'<p class="param-hint">{escape(str(p["help"]))}</p>'
                if p.get("help") else ""
            )
            params_html += f"""
            <div class="param">
              <label>
                <span class="param-name">{safe_name}</span>
                <span class="param-meta">{req} · {safe_kind}</span>
              </label>
              {input_html}
              {help_html}
            </div>"""

        route_cards.append(f"""
        <article class="card" style="--i: {idx}">
          <header class="card-header">
            <div class="methods">{methods}</div>
            <code class="path">{escape(str(r["path"]))}</code>
            <span class="endpoint-name">{escape(str(r["name"]))}</span>
            {rate_limit}
          </header>
          <p class="desc">{escape(str(r.get("description") or "No description provided."))}</p>
          <form class="try-form" method="{escape(form_method.lower(), quote=True)}" data-method="{escape(form_method, quote=True)}" action="{escape(str(r["path"]), quote=True)}" enctype="multipart/form-data">
            {params_html or '<p class="empty">No parameters</p>'}
            <button type="submit" class="btn-try">
              Try it
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14M12 5l7 7-7 7"/>
              </svg>
            </button>
          </form>
        </article>""")

    cards = "\n".join(route_cards) or '<p class="empty">No routes registered yet.</p>'

    dashboard_script = r"""
(() => {
  const backdrop = document.getElementById("response-modal");
  const title = document.getElementById("response-title");
  const summary = document.getElementById("response-summary");
  const status = document.getElementById("response-status");
  const text = document.getElementById("response-text");
  const editorWrap = document.getElementById("response-editor-wrap");
  const editor = document.getElementById("response-editor");
  const toolbar = document.getElementById("editor-toolbar");
  const preview = document.getElementById("response-preview");
  const closeButton = document.getElementById("response-close");
  let objectUrl = null;
  let savedRange = null;

  function rememberSelection() {
    const selection = window.getSelection();
    if (selection && selection.rangeCount && editor.contains(selection.anchorNode)) {
      savedRange = selection.getRangeAt(0).cloneRange();
    }
  }
  function restoreSelection() {
    if (!savedRange) return;
    editor.focus();
    const selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(savedRange);
  }
  document.addEventListener("selectionchange", rememberSelection);
  toolbar.addEventListener("mousedown", (event) => {
    if (event.target.closest("button")) event.preventDefault();
    rememberSelection();
  });

  function closeModal() {
    backdrop.hidden = true;
    document.body.classList.remove("modal-open");
    preview.replaceChildren();
    preview.hidden = true;
    text.hidden = false;
    editorWrap.hidden = true;
    toolbar.hidden = true;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  function showMessage(heading, message, isError) {
    title.textContent = heading;
    summary.textContent = message;
    status.textContent = isError ? "Request failed" : "Response";
    status.classList.toggle("status-error", Boolean(isError));
    text.hidden = true;
    editorWrap.hidden = true;
    toolbar.hidden = true;
    preview.hidden = true;
    backdrop.hidden = false;
    document.body.classList.add("modal-open");
    closeButton.focus();
  }

  function filenameFromResponse(response) {
    const header = response.headers.get("content-disposition") || "";
    const match = header.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    if (match) {
      try { return decodeURIComponent(match[1].replace(/"/g, "")); }
      catch (_) { return match[1].replace(/"/g, ""); }
    }
    return "response-file";
  }

  function renderEditor(source) {
    editor.replaceChildren();
    const lines = String(source).replace(/\r\n?/g, "\n").split("\n");
    let paragraph = [];
    let list = null;
    function flushParagraph() {
      if (!paragraph.length) return;
      const node = document.createElement("p");
      node.textContent = paragraph.join(" ").trim();
      editor.appendChild(node);
      paragraph = [];
    }
    function endList() { list = null; }
    for (let i = 0; i < lines.length;) {
      const line = lines[i].trim();
      if (!line) { flushParagraph(); endList(); i++; continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph(); endList();
        const node = document.createElement("h" + Math.min(heading[1].length, 3));
        node.textContent = heading[2]; editor.appendChild(node); i++; continue;
      }
      const bullet = line.match(/^[-*]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        if (!list) { list = document.createElement("ul"); editor.appendChild(list); }
        const item = document.createElement("li"); item.textContent = bullet[1]; list.appendChild(item);
        i++; continue;
      }
      if (/^\|.*\|$/.test(line)) {
        flushParagraph(); endList();
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          const cells = lines[i].trim().slice(1, -1).split("|").map(cell => cell.trim());
          if (!cells.every(cell => /^:?-{3,}:?$/.test(cell))) rows.push(cells);
          i++;
        }
        if (rows.length) {
          const table = document.createElement("table");
          rows.forEach((cells, rowIndex) => {
            const row = table.insertRow();
            cells.forEach(value => {
              const cell = rowIndex === 0 ? document.createElement("th") : document.createElement("td");
              cell.textContent = value; row.appendChild(cell);
            });
          });
          editor.appendChild(table);
        }
        continue;
      }
      endList(); paragraph.push(line); i++;
    }
    flushParagraph();
  }

  toolbar.addEventListener("click", (event) => {
    const button = event.target.closest("[data-command]");
    if (!button) return;
    restoreSelection();
    document.execCommand(button.dataset.command, false, button.dataset.value || null);
  });
  document.getElementById("editor-font").addEventListener("change", (event) => {
    restoreSelection(); document.execCommand("fontName", false, event.target.value);
  });
  document.getElementById("editor-size").addEventListener("change", (event) => {
    restoreSelection(); document.execCommand("fontSize", false, "7");
    editor.querySelectorAll('font[size="7"]').forEach((node) => {
      const span = document.createElement("span");
      span.style.fontSize = event.target.value + "pt";
      span.innerHTML = node.innerHTML; node.replaceWith(span);
    });
  });
  document.getElementById("editor-copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText(editor.innerText);
    summary.textContent = "Edited text copied to the clipboard.";
  });
  document.getElementById("editor-download").addEventListener("click", () => {
    const html = "<!doctype html><meta charset=\"utf-8\"><style>body{font:11pt Arial;max-width:8.5in;margin:1in auto;line-height:1.55}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:6px 10px}</style>" + editor.innerHTML;
    const url = URL.createObjectURL(new Blob([html], {type: "text/html"}));
    const link = document.createElement("a"); link.href = url; link.download = "edited-document.html"; link.click();
    URL.revokeObjectURL(url);
  });

  async function showResponse(response) {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    preview.replaceChildren();
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    const disposition = response.headers.get("content-disposition") || "";
    const isFile = disposition.toLowerCase().includes("attachment")
      || contentType.includes("application/pdf")
      || contentType.startsWith("image/");

    status.textContent = String(response.status) + " " + response.statusText;
    status.classList.toggle("status-error", !response.ok);
    title.textContent = response.ok ? "Request completed" : "Request failed";
    summary.textContent = response.ok
      ? "The endpoint returned a response."
      : "The endpoint returned an error. See the response details below.";

    if (isFile && response.ok) {
      text.hidden = true; editorWrap.hidden = true; toolbar.hidden = true;
      const blob = await response.blob();
      objectUrl = URL.createObjectURL(blob);
      const filename = filenameFromResponse(response);
      const download = document.createElement("a");
      download.className = "response-download";
      download.href = objectUrl;
      download.download = filename;
      download.textContent = "Download " + filename;
      preview.appendChild(download);
      if (contentType.includes("application/pdf")) {
        const frame = document.createElement("iframe");
        frame.className = "response-frame";
        frame.src = objectUrl;
        frame.title = "PDF response preview";
        preview.appendChild(frame);
      } else if (contentType.startsWith("image/")) {
        const image = document.createElement("img");
        image.className = "response-image";
        image.src = objectUrl;
        image.alt = filename;
        preview.appendChild(image);
      }
      text.hidden = true;
      preview.hidden = false;
    } else {
      let result;
      let documentText = null;
      if (contentType.includes("application/json")) {
        try { result = await response.json(); }
        catch (_) { result = {message: "The server returned invalid JSON."}; }
        if (result && typeof result.text === "string") documentText = result.text;
        else text.textContent = JSON.stringify(result, null, 2);
      } else {
        result = await response.text();
        documentText = result || "The server returned an empty response.";
      }
      if (documentText !== null) {
        renderEditor(documentText);
        editorWrap.hidden = false; toolbar.hidden = false; text.hidden = true;
      } else {
        editorWrap.hidden = true; toolbar.hidden = true; text.hidden = false;
      }
      preview.hidden = true;
    }

    backdrop.hidden = false;
    document.body.classList.add("modal-open");
    closeButton.focus();
  }

  document.querySelectorAll(".try-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector(".btn-try");
      const originalMarkup = button.innerHTML;
      button.disabled = true;
      const ocrEngine = form.querySelector('[name="engine"]')?.value;
      button.textContent = ocrEngine === "paddle" ? "Loading and running PaddleOCR..." : "Sending...";
      const method = (form.dataset.method || form.method || "POST").toUpperCase();
      let url = form.action;
      const options = {method: method, headers: {Accept: "application/json, application/pdf, image/*, text/plain"}};

      if (method === "GET" || method === "HEAD") {
        const params = new URLSearchParams();
        new FormData(form).forEach((value, key) => {
          if (typeof value === "string" && value !== "") params.append(key, value);
        });
        if (params.toString()) url += (url.includes("?") ? "&" : "?") + params.toString();
      } else {
        options.body = new FormData(form);
      }

      try {
        const response = await fetch(url, options);
        await showResponse(response);
      } catch (error) {
        showMessage("Could not reach the endpoint", error.message || "Check your connection and try again.", true);
      } finally {
        button.disabled = false;
        button.innerHTML = originalMarkup;
      }
    });
  });

  closeButton.addEventListener("click", closeModal);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !backdrop.hidden) closeModal();
  });
})();
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>eDocAPI · Developer Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    /* Colors from your glossy blue logo */
    --blue-900: #0B1F4A;
    --blue-800: #0F2C6B;
    --blue-700: #1A3A8F;
    --blue-600: #1E4ED8;
    --blue-500: #2563EB;
    --cyan-400: #22D3EE;
    --cyan-300: #67E8F9;
    --bg: #0A1224;
    --bg-card: #0F1B33;
    --bg-elevated: #132040;
    --border: rgba(56, 189, 248, 0.12);
    --border-hover: rgba(56, 189, 248, 0.28);
    --text: #E8F1FF;
    --text-muted: #94A3B8;
    --text-dim: #64748B;
    --radius: 12px;
    --shadow: 0 4px 24px -4px rgba(0, 0, 0, 0.4);
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: "Inter", system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
    padding: 2rem 1.25rem 4rem;
  }}

  /* subtle top glow matching logo */
  body::before {{
    content: "";
    position: fixed;
    top: -20%;
    left: 50%;
    transform: translateX(-50%);
    width: 120%;
    height: 50vh;
    background: radial-gradient(ellipse at center, rgba(37, 99, 235, 0.18) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
  }}

  .container {{
    position: relative;
    z-index: 1;
    max-width: 880px;
    margin: 0 auto;
  }}

  /* ── Header ── */
  .header {{
    display: flex;
    align-items: center;
    gap: 1.1rem;
    margin-bottom: 2rem;
    animation: fadeIn 0.5s ease both;
  }}

  .logo {{
    display: grid;
    place-items: center;
    width: 56px;
    height: 56px;
    border-radius: 14px;
    object-fit: contain;
    background: linear-gradient(145deg, var(--blue-700), var(--blue-900));
    color: white;
    font-size: 2rem;
    font-weight: 700;
    padding: 6px;
    box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.2), 0 8px 24px -6px rgba(37, 99, 235, 0.45);
  }}

  .brand h1 {{
    font-size: 1.65rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
    line-height: 1.2;
  }}

  .brand .tagline {{
    font-size: 0.9rem;
    color: var(--text-muted);
    margin-top: 0.15rem;
  }}

  .version {{
    display: inline-flex;
    align-items: center;
    margin-left: 0.4rem;
    padding: 0.15rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 600;
    border-radius: 999px;
    background: rgba(37, 99, 235, 0.15);
    color: var(--cyan-300);
    border: 1px solid rgba(56, 189, 248, 0.25);
  }}

  /* ── Info pills ── */
  .info-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 1.75rem;
    animation: fadeIn 0.5s 0.08s ease both;
  }}

  .pill {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.95rem;
    font-size: 0.82rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--text-muted);
  }}

  .pill strong {{
    color: var(--cyan-300);
    font-weight: 600;
  }}

  /* ── Release notes ── */
  .release {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.4rem;
    margin-bottom: 2rem;
    animation: fadeIn 0.5s 0.12s ease both;
  }}

  .release h2 {{
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--cyan-300);
    margin-bottom: 0.7rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }}

  .release h2::before {{
    content: "";
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--cyan-400);
    box-shadow: 0 0 8px var(--cyan-400);
  }}

  .release ul {{
    list-style: none;
  }}

  .release li {{
    position: relative;
    padding-left: 1.2rem;
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-bottom: 0.4rem;
  }}

  .release li::before {{
    content: "→";
    position: absolute;
    left: 0;
    color: var(--blue-500);
    font-weight: 600;
  }}

  /* ── Cards ── */
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.4rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s;
    animation: fadeIn 0.45s ease both;
    animation-delay: calc(0.15s + var(--i) * 0.06s);
  }}

  .card:hover {{
    border-color: var(--border-hover);
    transform: translateY(-2px);
    box-shadow: var(--shadow);
  }}

  .card-header {{
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 0.6rem;
  }}

  .methods {{
    display: flex;
    gap: 0.35rem;
  }}

  .method {{
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.68rem;
    font-weight: 500;
    letter-spacing: 0.03em;
    padding: 0.2rem 0.5rem;
    border-radius: 5px;
    text-transform: uppercase;
  }}

  .method-get    {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }}
  .method-post   {{ background: rgba(37, 99, 235, 0.18);  color: #60a5fa; border: 1px solid rgba(37, 99, 235, 0.35); }}
  .method-put    {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
  .method-patch  {{ background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); }}
  .method-delete {{ background: rgba(239, 68, 68, 0.15);  color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }}

  .path {{
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.88rem;
    color: var(--cyan-300);
    background: rgba(34, 211, 238, 0.08);
    padding: 0.18rem 0.5rem;
    border-radius: 5px;
  }}

  .endpoint-name {{
    margin-left: auto;
    font-size: 0.8rem;
    color: var(--text-dim);
    font-weight: 500;
  }}

  .rate-limit {{
    font-size: 0.68rem;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.18rem 0.5rem;
  }}

  .desc {{
    font-size: 0.9rem;
    color: var(--text-muted);
    margin-bottom: 1rem;
  }}

  /* ── Form ── */
  .param {{
    margin-bottom: 0.85rem;
  }}

  .param label {{
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    margin-bottom: 0.3rem;
  }}

  .param-name {{
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--text);
  }}

  .param-meta {{
    font-size: 0.72rem;
    color: var(--text-dim);
    background: rgba(148, 163, 184, 0.1);
    padding: 0.1rem 0.4rem;
    border-radius: 999px;
  }}

  input[type="text"],
  input[type="file"],
  select.param-control {{
    width: 100%;
    padding: 0.55rem 0.8rem;
    font-family: inherit;
    font-size: 0.9rem;
    color: var(--text);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    transition: border-color 0.2s, box-shadow 0.2s;
  }}

  input[type="text"]:focus,
  input[type="file"]:focus,
  select.param-control:focus {{
    outline: none;
    border-color: var(--blue-500);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25);
  }}

  input[type="file"] {{
    padding: 0.4rem 0.7rem;
    cursor: pointer;
  }}

  .param-hint {{
    margin-top: 0.35rem;
    color: var(--text-dim);
    font-size: 0.76rem;
    line-height: 1.45;
  }}

  input[type="file"]::file-selector-button {{
    font-family: inherit;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--cyan-300);
    background: rgba(34, 211, 238, 0.12);
    border: 1px solid rgba(34, 211, 238, 0.3);
    border-radius: 6px;
    padding: 0.3rem 0.7rem;
    margin-right: 0.7rem;
    cursor: pointer;
    transition: background 0.15s;
  }}

  input[type="file"]::file-selector-button:hover {{
    background: rgba(34, 211, 238, 0.22);
  }}

  .btn-try {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: 0.25rem;
    padding: 0.55rem 1.2rem;
    font-family: inherit;
    font-size: 0.875rem;
    font-weight: 600;
    color: #fff;
    background: linear-gradient(135deg, var(--blue-600), var(--blue-500));
    border: none;
    border-radius: 8px;
    cursor: pointer;
    box-shadow: 0 4px 14px -3px rgba(37, 99, 235, 0.5);
    transition: transform 0.15s, box-shadow 0.15s, filter 0.15s;
  }}

  .btn-try:hover {{
    transform: translateY(-1px);
    filter: brightness(1.08);
    box-shadow: 0 6px 20px -3px rgba(37, 99, 235, 0.6);
  }}

  .btn-try:active {{
    transform: translateY(0);
  }}

  .btn-try svg {{
    transition: transform 0.2s;
  }}

  .btn-try:hover svg {{
    transform: translateX(3px);
  }}

  .btn-try:disabled {{ opacity: .7; cursor: wait; transform: none; }}
  .modal-backdrop {{
    position: fixed; inset: 0; z-index: 20; display: flex; align-items: center;
    justify-content: center; padding: 1rem; background: rgba(2, 8, 23, .78);
    backdrop-filter: blur(8px);
  }}
  .modal-backdrop[hidden] {{ display: none; }}
  .modal-panel {{
    width: min(100%, 1080px); max-height: min(94vh, 1050px); overflow: auto;
    padding: 1.4rem; border: 1px solid var(--border-hover); border-radius: 16px;
    background: linear-gradient(160deg, #132342, #0F1B33 60%);
    box-shadow: 0 24px 90px rgba(0, 0, 0, .55);
    animation: fadeIn .18s ease both;
  }}
  .modal-head {{ display: flex; align-items: flex-start; gap: 1rem; }}
  .modal-copy {{ flex: 1; min-width: 0; }}
  .modal-copy h2 {{ font-size: 1.1rem; margin: .45rem 0 .2rem; }}
  .modal-copy p {{ color: var(--text-muted); font-size: .88rem; overflow-wrap: anywhere; }}
  .response-status {{
    display: inline-flex; padding: .22rem .55rem; border-radius: 999px;
    color: #6ee7b7; background: rgba(16, 185, 129, .13);
    border: 1px solid rgba(16, 185, 129, .3);
    font: 500 .72rem "JetBrains Mono", ui-monospace, monospace;
  }}
  .response-status.status-error {{
    color: #fca5a5; background: rgba(239, 68, 68, .13);
    border-color: rgba(239, 68, 68, .35);
  }}
  .modal-close {{
    width: 2.3rem; height: 2.3rem; flex: 0 0 auto; border: 1px solid var(--border);
    border-radius: 8px; color: var(--text-muted); background: rgba(255,255,255,.04);
    font-size: 1.3rem; cursor: pointer;
  }}
  .modal-close:hover {{ color: var(--text); border-color: var(--border-hover); }}
  .response-text {{
    margin-top: 1.2rem; padding: 1rem; max-height: 52vh; overflow: auto;
    border: 1px solid var(--border); border-radius: 10px; color: #dbeafe;
    background: rgba(3, 10, 24, .72); font: .82rem/1.6 "JetBrains Mono", ui-monospace, monospace;
    white-space: pre-wrap; overflow-wrap: anywhere;
  }}
  .editor-toolbar {{
    display: flex; flex-wrap: wrap; align-items: center; gap: .4rem;
    margin-top: 1rem; padding: .65rem; border: 1px solid #cbd5e1;
    border-radius: 10px 10px 0 0; background: #f1f5f9;
  }}
  .editor-toolbar[hidden], .document-editor-wrap[hidden] {{ display: none; }}
  .editor-toolbar button, .editor-toolbar select {{
    min-height: 2rem; padding: .3rem .55rem; border: 1px solid #cbd5e1;
    border-radius: 6px; color: #172033; background: #fff; font: 500 .82rem Inter, sans-serif;
  }}
  .editor-toolbar button {{ cursor: pointer; }}
  .editor-toolbar button:hover {{ background: #e2e8f0; }}
  .editor-divider {{ width: 1px; height: 1.6rem; margin: 0 .15rem; background: #cbd5e1; }}
  .document-editor-wrap {{ max-height: 68vh; overflow: auto; padding: 1.25rem; background: #dbe2ea; }}
  .document-editor {{
    box-sizing: border-box; width: min(100%, 8.5in); min-height: 11in; margin: 0 auto;
    padding: 1in; outline: none; color: #111827; background: #fff;
    box-shadow: 0 4px 24px rgba(15, 23, 42, .2); font: 11pt Arial, sans-serif;
    line-height: 1.55; overflow-wrap: anywhere;
  }}
  .document-editor h1 {{ margin: 0 0 1.4em; font-size: 22pt; }}
  .document-editor h2 {{ margin: 1.2em 0 .55em; font-size: 16pt; }}
  .document-editor h3 {{ margin: 1em 0 .45em; font-size: 13pt; }}
  .document-editor p {{ margin: 0 0 .85em; }}
  .document-editor ul {{ padding-left: 1.5em; }}
  .document-editor table {{ width: 100%; margin: 1em 0; border-collapse: collapse; font-size: 10pt; }}
  .document-editor th, .document-editor td {{ border: 1px solid #9ca3af; padding: .4em .55em; text-align: left; }}
  .document-editor th {{ background: #f1f5f9; }}
  .editor-actions {{ display: flex; justify-content: flex-end; gap: .5rem; padding: .7rem; background: #e2e8f0; }}
  .editor-actions button {{ padding: .45rem .8rem; border: 0; border-radius: 6px; cursor: pointer; color: #fff; background: #1d4ed8; }}
  .response-preview {{ margin-top: 1rem; }}
  .response-download {{
    display: inline-flex; margin-bottom: .8rem; padding: .55rem .8rem;
    color: #fff; background: linear-gradient(135deg, var(--blue-600), var(--blue-500));
    border-radius: 7px; font-size: .85rem; font-weight: 600; text-decoration: none;
  }}
  .response-frame {{ width: 100%; height: min(60vh, 600px); border: 1px solid var(--border); border-radius: 8px; background: #fff; }}
  .response-image {{ display: block; max-width: 100%; max-height: 60vh; margin: 0 auto; border-radius: 8px; }}
  body.modal-open {{ overflow: hidden; }}

  .empty {{
    font-size: 0.875rem;
    color: var(--text-dim);
    margin: 0.4rem 0;
  }}

  footer {{
    margin-top: 3rem;
    text-align: center;
    font-size: 0.8rem;
    color: var(--text-dim);
    animation: fadeIn 0.5s 0.3s ease both;
  }}

  @keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}

  @media (max-width: 560px) {{
    .header {{ gap: 0.85rem; }}
    .logo {{ width: 48px; height: 48px; }}
    .brand h1 {{ font-size: 1.4rem; }}
    .endpoint-name {{ margin-left: 0; width: 100%; }}
    .modal-panel {{ padding: 1rem; }}
    .document-editor-wrap {{ padding: .5rem; }}
    .document-editor {{ min-height: 70vh; padding: .65in .45in; }}
  }}
</style>
</head>
<body>
  <div class="container">
    <header class="header">
      <div class="logo" aria-hidden="true">e</div>
      <div class="brand">
        <h1>eDocAPI</h1>
        <p class="tagline">Document workflows in one place <span class="version">v0.2.0</span></p>
      </div>
    </header>

    <div class="info-row">
      <div class="pill"><strong>Types</strong> {type_list}</div>
      <div class="pill"><strong>Max size</strong> {max_mb:.1f} MB</div>
    </div>

    <section class="release">
      <h2>Built for everyday document work</h2>
      <ul>
        <li>Convert, extract, recognize, compress, and merge documents through one API.</li>
        <li>Generate readable PDFs with structured headings, page layouts, and tables.</li>
        <li>Explore routes, inspect results, and test document workflows from the dashboard.</li>
      </ul>
    </section>

    {cards}

    <div class="modal-backdrop" id="response-modal" hidden>
      <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="response-title">
        <div class="modal-head">
          <div class="modal-copy">
            <span class="response-status" id="response-status">Response</span>
            <h2 id="response-title">Endpoint response</h2>
            <p id="response-summary"></p>
          </div>
          <button class="modal-close" id="response-close" type="button" aria-label="Close response">&times;</button>
        </div>
        <div class="editor-toolbar" id="editor-toolbar" role="toolbar" aria-label="Document formatting" hidden>
          <select id="editor-font" aria-label="Font family">
            <option value="Arial">Arial</option><option value="Calibri">Calibri</option>
            <option value="Georgia">Georgia</option><option value="Times New Roman">Times New Roman</option>
            <option value="Verdana">Verdana</option>
          </select>
          <select id="editor-size" aria-label="Font size">
            <option value="9">9 pt</option><option value="10">10 pt</option>
            <option value="11" selected>11 pt</option><option value="12">12 pt</option>
            <option value="14">14 pt</option><option value="16">16 pt</option>
            <option value="18">18 pt</option><option value="24">24 pt</option>
          </select>
          <span class="editor-divider"></span>
          <button type="button" data-command="bold" title="Bold"><strong>B</strong></button>
          <button type="button" data-command="italic" title="Italic"><em>I</em></button>
          <button type="button" data-command="underline" title="Underline"><u>U</u></button>
          <button type="button" data-command="insertUnorderedList" title="Bulleted list">• List</button>
          <button type="button" data-command="insertOrderedList" title="Numbered list">1. List</button>
          <span class="editor-divider"></span>
          <button type="button" data-command="justifyLeft" title="Align left">Left</button>
          <button type="button" data-command="justifyCenter" title="Center">Center</button>
          <button type="button" data-command="justifyRight" title="Align right">Right</button>
          <button type="button" data-command="justifyFull" title="Justify">Justify</button>
          <button type="button" data-command="undo" title="Undo">Undo</button>
          <button type="button" data-command="redo" title="Redo">Redo</button>
        </div>
        <div id="response-editor-wrap" class="document-editor-wrap" hidden>
          <article id="response-editor" class="document-editor" contenteditable="true"
                   role="textbox" aria-label="Editable extracted document" aria-multiline="true" spellcheck="true"></article>
          <div class="editor-actions">
            <button type="button" id="editor-copy">Copy text</button>
            <button type="button" id="editor-download">Download formatted HTML</button>
          </div>
        </div>
        <pre class="response-text" id="response-text" hidden></pre>
        <div class="response-preview" id="response-preview" hidden></div>
      </section>
    </div>

    <footer>eDocAPI · Document workflows, refined release by release</footer>
  </div>
  <script>{dashboard_script}</script>
</body>
</html>"""
