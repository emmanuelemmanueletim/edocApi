/* eDocAPI Dashboard client */

const state = {
  files: [],
  tool: "convert",
};

function $(sel, root = document) {
  return root.querySelector(sel);
}
function $$(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

function toast(message, type = "success") {
  const el = $("#toast");
  if (!el) return;
  el.textContent = message;
  el.className = `toast show ${type}`;
  setTimeout(() => el.classList.remove("show"), 3500);
}

function formatBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / (1024 * 1024)).toFixed(2) + " MB";
}

function setLoading(on) {
  const sp = $("#spinner");
  const btns = $$(".actions-row .btn-primary, .actions-row .btn-success");
  if (sp) sp.classList.toggle("show", on);
  btns.forEach((b) => (b.disabled = on));
}

function showResult(html, ok = true) {
  const box = $("#result");
  if (!box) return;
  box.className = `result-box show ${ok ? "success" : "error"}`;
  box.innerHTML = html;
}

function clearResult() {
  const box = $("#result");
  if (box) {
    box.className = "result-box";
    box.innerHTML = "";
  }
}

/* ----- Tool switching ----- */
function switchTool(id) {
  state.tool = id;
  state.files = [];
  clearResult();
  renderFileList();

  $$(".side-nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.tool === id);
  });
  $$(".tool-panel").forEach((p) => {
    p.classList.toggle("active", p.id === `panel-${id}`);
  });

  const titles = {
    convert: ["Convert to PDF", "Upload a document and download it as PDF."],
    extract: ["Extract text", "Pull plain text out of PDF, DOCX, HTML, Markdown, or TXT."],
    compress: ["Compress PDF", "Reduce PDF file size with medium compression."],
    merge: ["Merge PDFs", "Combine multiple PDF files into one document."],
    split: ["Split / extract pages", "Check page count or extract a page range from a PDF."],
    info: ["Document info", "Inspect metadata: type, size, pages, author, and more."],
    html2pdf: ["HTML to PDF", "Paste HTML and generate a PDF without uploading a file."],
    md2pdf: ["Markdown to PDF", "Paste Markdown and render it to PDF."],
  };
  const t = titles[id] || ["Tool", ""];
  const h = $("#panel-title");
  const s = $("#panel-sub");
  if (h) h.textContent = t[0];
  if (s) s.textContent = t[1];
}

/* ----- File handling ----- */
function onFilesSelected(fileList) {
  const arr = [...fileList];
  if (state.tool === "merge") {
    state.files = [...state.files, ...arr];
  } else {
    state.files = arr.slice(0, 1);
  }
  renderFileList();
  clearResult();
}

function renderFileList() {
  const list = $("#file-list");
  if (!list) return;
  if (!state.files.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = state.files
    .map(
      (f, i) => `
    <div class="file-item">
      <div>
        <div>${escapeHtml(f.name)}</div>
        <div class="meta">${formatBytes(f.size)} · ${f.type || "unknown type"}</div>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" data-remove="${i}">Remove</button>
    </div>`
    )
    .join("");
  list.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.files.splice(Number(btn.dataset.remove), 1);
      renderFileList();
    });
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ----- API calls ----- */
async function postFile(url, files, fieldName = "file") {
  const fd = new FormData();
  if (Array.isArray(files)) {
    if (fieldName === "files") {
      files.forEach((f) => fd.append("files", f));
    } else {
      files.forEach((f) => fd.append(fieldName, f));
    }
  } else {
    fd.append(fieldName, files);
  }
  const res = await fetch(url, { method: "POST", body: fd });
  return res;
}

async function downloadFromResponse(res, fallbackName) {
  const cd = res.headers.get("content-disposition") || "";
  let name = fallbackName;
  const m = /filename="?([^";]+)"?/i.exec(cd);
  if (m) name = m[1];
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

async function parseError(res) {
  try {
    const data = await res.json();
    return data.message || data.error || res.statusText;
  } catch {
    return res.statusText || "Request failed";
  }
}

async function runConvert() {
  if (!state.files.length) return toast("Choose a file first", "error");
  setLoading(true);
  try {
    const res = await postFile("/api/convert", state.files[0]);
    if (!res.ok) throw new Error(await parseError(res));
    await downloadFromResponse(res, "converted.pdf");
    showResult(`<div class="result-title">Conversion complete</div><p>PDF downloaded.</p>`);
    toast("PDF ready");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runExtract() {
  if (!state.files.length) return toast("Choose a file first", "error");
  setLoading(true);
  try {
    const res = await postFile("/api/extract", state.files[0]);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.error || "Extract failed");
    showResult(`
      <div class="result-title">Text extracted from ${escapeHtml(data.filename)}</div>
      <div class="result-meta">
        <div class="meta-card"><label>Type</label><span>${escapeHtml(data.type)}</span></div>
        <div class="meta-card"><label>Characters</label><span>${data.characters}</span></div>
      </div>
      <div class="result-text" style="margin-top:0.9rem">${escapeHtml(data.text || "(empty)")}</div>
    `);
    toast("Text extracted");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runCompress() {
  if (!state.files.length) return toast("Choose a PDF first", "error");
  setLoading(true);
  try {
    const res = await postFile("/api/compress", state.files[0]);
    if (!res.ok) throw new Error(await parseError(res));
    await downloadFromResponse(res, "compressed.pdf");
    showResult(`<div class="result-title">Compression complete</div><p>Compressed PDF downloaded.</p>`);
    toast("Compressed PDF ready");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runMerge() {
  if (state.files.length < 2) return toast("Add at least two PDF files", "error");
  setLoading(true);
  try {
    const res = await postFile("/api/merge", state.files, "files");
    if (!res.ok) throw new Error(await parseError(res));
    await downloadFromResponse(res, "merged.pdf");
    showResult(`<div class="result-title">Merge complete</div><p>${state.files.length} files merged.</p>`);
    toast("Merged PDF ready");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runInfo() {
  if (!state.files.length) return toast("Choose a file first", "error");
  setLoading(true);
  try {
    const res = await postFile("/api/info", state.files[0]);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.error || "Info failed");
    const cards = Object.entries(data)
      .filter(([k]) => k !== "success")
      .map(
        ([k, v]) =>
          `<div class="meta-card"><label>${escapeHtml(k)}</label><span>${escapeHtml(
            v == null || v === "" ? "—" : String(v)
          )}</span></div>`
      )
      .join("");
    showResult(`<div class="result-title">Document information</div><div class="result-meta">${cards}</div>`);
    toast("Info loaded");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runSplitInfo() {
  if (!state.files.length) return toast("Choose a PDF first", "error");
  setLoading(true);
  try {
    const res = await postFile("/api/split-info", state.files[0]);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.error || "Failed");
    showResult(`
      <div class="result-title">${escapeHtml(data.filename)}</div>
      <div class="result-meta">
        <div class="meta-card"><label>Pages</label><span>${data.pages}</span></div>
        <div class="meta-card"><label>Size</label><span>${formatBytes(data.size)}</span></div>
      </div>
      <p style="margin-top:0.8rem;color:var(--text-muted);font-size:0.9rem">Use Extract pages below with a start/end range (1-based).</p>
    `);
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runExtractPages() {
  if (!state.files.length) return toast("Choose a PDF first", "error");
  const start = Number($("#page-start")?.value || 1);
  const end = $("#page-end")?.value ? Number($("#page-end").value) : start;
  setLoading(true);
  try {
    const res = await postFile(`/api/extract-pages?start=${start}&end=${end}`, state.files[0]);
    if (!res.ok) throw new Error(await parseError(res));
    await downloadFromResponse(res, `pages-${start}-${end}.pdf`);
    showResult(`<div class="result-title">Pages extracted</div><p>Pages ${start}–${end} downloaded.</p>`);
    toast("Pages ready");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runHtml2Pdf() {
  const html = $("#html-input")?.value || "";
  if (!html.trim()) return toast("Paste some HTML first", "error");
  setLoading(true);
  try {
    const res = await fetch("/api/html-to-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html }),
    });
    if (!res.ok) throw new Error(await parseError(res));
    await downloadFromResponse(res, "from-html.pdf");
    showResult(`<div class="result-title">PDF generated from HTML</div>`);
    toast("PDF ready");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

async function runMd2Pdf() {
  const markdown = $("#md-input")?.value || "";
  if (!markdown.trim()) return toast("Paste some Markdown first", "error");
  setLoading(true);
  try {
    const res = await fetch("/api/markdown-to-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown }),
    });
    if (!res.ok) throw new Error(await parseError(res));
    await downloadFromResponse(res, "from-markdown.pdf");
    showResult(`<div class="result-title">PDF generated from Markdown</div>`);
    toast("PDF ready");
  } catch (e) {
    showResult(`<div class="result-title">Error</div><p>${escapeHtml(e.message)}</p>`, false);
    toast(e.message, "error");
  } finally {
    setLoading(false);
  }
}

/* ----- Init ----- */
document.addEventListener("DOMContentLoaded", () => {
  if (!$("#dash-root")) return;

  $$(".side-nav button").forEach((btn) => {
    btn.addEventListener("click", () => switchTool(btn.dataset.tool));
  });

  const dz = $("#dropzone");
  const input = $("#file-input");
  if (dz && input) {
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      if (e.dataTransfer?.files?.length) onFilesSelected(e.dataTransfer.files);
    });
    input.addEventListener("change", () => {
      if (input.files?.length) onFilesSelected(input.files);
      input.value = "";
    });
  }

  $("#btn-convert")?.addEventListener("click", runConvert);
  $("#btn-extract")?.addEventListener("click", runExtract);
  $("#btn-compress")?.addEventListener("click", runCompress);
  $("#btn-merge")?.addEventListener("click", runMerge);
  $("#btn-info")?.addEventListener("click", runInfo);
  $("#btn-split-info")?.addEventListener("click", runSplitInfo);
  $("#btn-extract-pages")?.addEventListener("click", runExtractPages);
  $("#btn-html2pdf")?.addEventListener("click", runHtml2Pdf);
  $("#btn-md2pdf")?.addEventListener("click", runMd2Pdf);

  switchTool("convert");
});
