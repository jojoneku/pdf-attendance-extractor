/**
 * PDF Attendance Extractor — Frontend Logic
 *
 * Handles file upload (drag-and-drop + browse), extraction API calls,
 * preview table rendering, and export to Excel / Google Sheets.
 */

// ── DOM Elements ──────────────────────────────────────────────────
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const fileList = document.getElementById("fileList");
const fileListItems = document.getElementById("fileListItems");
const fileCount = document.getElementById("fileCount");
const clearBtn = document.getElementById("clearBtn");
const extractBtn = document.getElementById("extractBtn");
const statusBar = document.getElementById("statusBar");
const spinner = document.getElementById("spinner");
const statusText = document.getElementById("statusText");
const errorsSection = document.getElementById("errorsSection");
const errorsList = document.getElementById("errorsList");
const previewSection = document.getElementById("previewSection");
const totalStudents = document.getElementById("totalStudents");
const previewBody = document.getElementById("previewBody");
const exportExcelBtn = document.getElementById("exportExcelBtn");
const exportGsheetBtn = document.getElementById("exportGsheetBtn");
const gsheetModal = document.getElementById("gsheetModal");
const gsheetCancelBtn = document.getElementById("gsheetCancelBtn");
const gsheetConfirmBtn = document.getElementById("gsheetConfirmBtn");
const sheetNameInput = document.getElementById("sheetName");
const worksheetNameInput = document.getElementById("worksheetName");

// Defaults panel
const defaultsPanel = document.getElementById("defaultsPanel");
const defaultEmail = document.getElementById("defaultEmail");
const defaultBeneficiary = document.getElementById("defaultBeneficiary");
const defaultAgeRange = document.getElementById("defaultAgeRange");
const defaultAffiliationType = document.getElementById("defaultAffiliationType");
const defaultAffiliationName = document.getElementById("defaultAffiliationName");

// ── State ─────────────────────────────────────────────────────────
let selectedFiles = [];
let extractedData = null; // holds the last extraction response data
let flatStudents = [];    // flattened array for pagination
let displayedCount = 0;   // how many rows currently rendered
const PAGE_SIZE = 100;    // rows per page in preview

// ── Visibility helpers (CSS class-based, immune to browser cache restore) ─────
function show(el) { el.classList.add("visible"); }
function hide(el) { el.classList.remove("visible"); }

// ── Reset UI immediately + on every page show ────────────────────
function resetUI() {
    console.log("[init] Resetting UI state");
    hide(gsheetModal);
    hide(statusBar);
    hide(errorsSection);
    hide(previewSection);
    hide(defaultsPanel);
    fileList.hidden = true;
    extractBtn.disabled = true;
    extractedData = null;
    selectedFiles = [];
}

// Run immediately (script is at end of body, DOM is ready)
resetUI();

// Also run on pageshow (catches bfcache / back-forward navigation)
window.addEventListener("pageshow", resetUI);

// ── File Selection ────────────────────────────────────────────────

dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("drag-over");
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf")
    );
    addFiles(files);
});

fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files);
    addFiles(files);
    fileInput.value = "";
});

clearBtn.addEventListener("click", () => {
    selectedFiles = [];
    renderFileList();
    hidePreview();
});

function addFiles(files) {
    // Avoid duplicates by name
    const existingNames = new Set(selectedFiles.map((f) => f.name));
    for (const f of files) {
        if (!existingNames.has(f.name)) {
            selectedFiles.push(f);
        }
    }
    renderFileList();
}

function renderFileList() {
    fileListItems.innerHTML = "";
    if (selectedFiles.length === 0) {
        fileList.hidden = true;
        extractBtn.disabled = true;
        return;
    }
    fileList.hidden = false;
    extractBtn.disabled = false;
    fileCount.textContent = selectedFiles.length;

    for (const f of selectedFiles) {
        const li = document.createElement("li");
        li.textContent = f.name;
        fileListItems.appendChild(li);
    }
}

// ── Extraction ────────────────────────────────────────────────────

extractBtn.addEventListener("click", async () => {
    if (selectedFiles.length === 0) return;

    showStatus("Uploading and extracting data...");
    hidePreview();
    hideErrors();

    const formData = new FormData();
    for (const f of selectedFiles) {
        formData.append("files", f);
    }

    try {
        console.log(`[upload] Sending ${selectedFiles.length} file(s)...`);
        showStatus(`Uploading ${selectedFiles.length} file(s)… Large files may take a few minutes.`);

        const controller = new AbortController();
        const res = await fetch("/api/upload", {
            method: "POST",
            body: formData,
            signal: controller.signal,
        });

        console.log(`[upload] Response status: ${res.status} ${res.statusText}`);
        showStatus("Parsing response…");

        if (!res.ok) {
            const err = await res.json();
            throw new Error(parseError(err));
        }

        const json = await res.json();
        extractedData = json.data;
        console.log(`[upload] Extracted ${json.total_students} student(s) from ${json.data.length} file(s)`);

        // Collect errors/warnings
        const allErrors = [];
        for (const fileResult of json.data) {
            for (const e of fileResult.errors) {
                allErrors.push(e);
            }
        }
        if (allErrors.length > 0) {
            console.warn(`[upload] ${allErrors.length} warning(s):`, allErrors);
            showErrors(allErrors);
        }

        showStatus(`Rendering preview of ${json.total_students.toLocaleString()} records…`);
        // Use setTimeout to let the browser paint the status message first
        await new Promise((r) => setTimeout(r, 50));
        renderPreview(json.data, json.total_students);        show(defaultsPanel);        hideStatus();
    } catch (err) {
        hideStatus();
        if (err.name === "AbortError") {
            showErrors(["Request was cancelled."]);
        } else {
            showErrors([err.message]);
        }
    }
});

// ── Preview Rendering ─────────────────────────────────────────────

function buildFullName(s) {
    const last = (s.lastname || "").trim();
    const first = (s.firstname || "").trim();
    const middle = (s.middlename || "").trim();
    const ext = (s.extension || "").trim();
    const parts = [first];
    if (middle) parts.push(middle);
    if (ext) parts.push(ext);
    const after = parts.join(" ");
    if (last && after) return `${last}, ${after}`;
    return last || after || "";
}

function renderPreview(data, total) {
    previewBody.innerHTML = "";

    // Flatten all students into a single array for pagination
    flatStudents = [];
    for (const fileResult of data) {
        for (const s of fileResult.students) {
            flatStudents.push({
                full_name: buildFullName(s),
                gender: s.gender || "",
                source_file: fileResult.source_file,
                // keep raw data for export
                ...s,
            });
        }
    }
    displayedCount = 0;

    // Render first page
    renderNextPage();

    totalStudents.textContent = total.toLocaleString();
    updatePaginationInfo();
    show(previewSection);
}

function renderNextPage() {
    const end = Math.min(displayedCount + PAGE_SIZE, flatStudents.length);
    const fragment = document.createDocumentFragment();

    for (let i = displayedCount; i < end; i++) {
        const s = flatStudents[i];
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${i + 1}</td>
            <td>${esc(s.full_name)}</td>
            <td>${esc(s.gender)}</td>
            <td>${esc(s.source_file)}</td>
        `;
        fragment.appendChild(tr);
    }

    previewBody.appendChild(fragment);
    displayedCount = end;
    updatePaginationInfo();
}

function updatePaginationInfo() {
    const info = document.getElementById("paginationInfo");
    const loadMoreBtn = document.getElementById("loadMoreBtn");
    const loadAllBtn = document.getElementById("loadAllBtn");

    if (info) {
        info.textContent = `Showing ${displayedCount.toLocaleString()} of ${flatStudents.length.toLocaleString()} records`;
    }
    if (loadMoreBtn) {
        loadMoreBtn.style.display = displayedCount < flatStudents.length ? "inline-flex" : "none";
    }
    if (loadAllBtn) {
        loadAllBtn.style.display = (displayedCount < flatStudents.length && flatStudents.length <= 50000) ? "inline-flex" : "none";
    }
}

function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ── Helper: collect current default values ───────────────────────
function getDefaults() {
    return {
        email: defaultEmail.value.trim(),
        beneficiary: defaultBeneficiary.value,
        age_range: defaultAgeRange.value,
        affiliation_type: defaultAffiliationType.value,
        affiliation_name: defaultAffiliationName.value.trim(),
    };
}

// ── Excel Export ──────────────────────────────────────────────────

exportExcelBtn.addEventListener("click", async () => {
    if (!extractedData) {
        console.warn("[excel] No data to export");
        showErrors(["No data to export. Please upload and extract PDFs first."]);
        return;
    }

    console.log(`[excel] Exporting ${extractedData.length} file result(s)...`);
    showStatus("Generating Excel file...");

    try {
        const res = await fetch("/api/export/excel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ data: extractedData, ...getDefaults() }),
        });

        console.log(`[excel] Response: ${res.status} ${res.statusText}`);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(parseError(err));
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "attendance_export.xlsx";
        a.click();
        URL.revokeObjectURL(url);
        hideStatus();
    } catch (err) {
        hideStatus();
        showErrors([err.message]);
    }
});

// ── Google Sheets Export ──────────────────────────────────────────

exportGsheetBtn.addEventListener("click", () => {
    if (!extractedData) return;
    show(gsheetModal);
});

gsheetCancelBtn.addEventListener("click", () => {
    hide(gsheetModal);
});

gsheetConfirmBtn.addEventListener("click", async () => {
    hide(gsheetModal);

    if (!extractedData) {
        console.warn("[gsheet] No data to export");
        showErrors(["No data to export. Please upload and extract PDFs first."]);
        return;
    }

    const sheetName = sheetNameInput.value || "Attendance Export";
    const tabName = worksheetNameInput.value || "Sheet1";
    console.log(`[gsheet] Exporting to "${sheetName}" / "${tabName}"...`);
    showStatus("Exporting to Google Sheets...");

    try {
        const res = await fetch("/api/export/gsheet", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                data: extractedData,
                spreadsheet_name: sheetName,
                worksheet_name: tabName,
                ...getDefaults(),
            }),
        });

        console.log(`[gsheet] Response: ${res.status} ${res.statusText}`);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(parseError(err));
        }

        const json = await res.json();
        hideStatus();
        console.log(`[gsheet] Success: ${json.message}`);
        alert(json.message || "Exported successfully!");
    } catch (err) {
        console.error("[gsheet] Export failed:", err);
        hideStatus();
        showErrors([err.message]);
    }
});

// Close modal on backdrop click
gsheetModal.addEventListener("click", (e) => {
    if (e.target === gsheetModal) hide(gsheetModal);
});
// ── Pagination Controls ──────────────────────────────────────────

document.getElementById("loadMoreBtn").addEventListener("click", () => {
    renderNextPage();
});

document.getElementById("loadAllBtn").addEventListener("click", () => {
    showStatus(`Rendering all ${flatStudents.length.toLocaleString()} rows…`);
    // Render in batches to avoid freezing the browser
    function renderBatch() {
        const batchEnd = Math.min(displayedCount + 500, flatStudents.length);
        const fragment = document.createDocumentFragment();
        for (let i = displayedCount; i < batchEnd; i++) {
            const s = flatStudents[i];
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${i + 1}</td>
                <td>${esc(s.full_name)}</td>
                <td>${esc(s.gender)}</td>
                <td>${esc(s.source_file)}</td>
            `;
            fragment.appendChild(tr);
        }
        previewBody.appendChild(fragment);
        displayedCount = batchEnd;
        updatePaginationInfo();

        if (displayedCount < flatStudents.length) {
            showStatus(`Rendering… ${displayedCount.toLocaleString()} / ${flatStudents.length.toLocaleString()}`);
            requestAnimationFrame(renderBatch);
        } else {
            hideStatus();
        }
    }
    requestAnimationFrame(renderBatch);
});
// ── UI Helpers ────────────────────────────────────────────────────

function showStatus(msg) {
    statusText.textContent = msg;
    show(statusBar);
    console.log(`[status] ${msg}`);
}

function hideStatus() {
    hide(statusBar);
}

// Click status bar to dismiss (escape hatch if stuck)
statusBar.addEventListener("click", () => {
    console.log("[status] Dismissed by user click");
    hideStatus();
});

function showErrors(errors) {
    errorsList.innerHTML = "";
    for (const e of errors) {
        const li = document.createElement("li");
        li.textContent = e;
        errorsList.appendChild(li);
    }
    show(errorsSection);
}

function hideErrors() {
    hide(errorsSection);
    errorsList.innerHTML = "";
}

function hidePreview() {
    hide(previewSection);
    hide(defaultsPanel);
    previewBody.innerHTML = "";
    extractedData = null;
    flatStudents = [];
    displayedCount = 0;
}

/**
 * Parse FastAPI error responses into a readable string.
 * FastAPI 422 returns { detail: [{ loc, msg, type }] }, not a plain string.
 */
function parseError(errBody) {
    if (!errBody) return "Unknown error";
    if (typeof errBody.detail === "string") return errBody.detail;
    if (Array.isArray(errBody.detail)) {
        return errBody.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    }
    return JSON.stringify(errBody);
}
