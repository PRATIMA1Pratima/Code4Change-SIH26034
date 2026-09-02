/**
 * app.js – Code4Change Inspector Frontend
 *
 * Phase 3 additions over Phase 2:
 *  - fetchWithTimeout()  : all API calls have a configurable timeout
 *  - apiRequest()        : central fetch wrapper with structured error handling
 *                          (network errors, non-JSON bodies, 4xx/5xx details)
 *  - Connection banner   : pings /api/status on load; shows live/offline state
 *  - setUiBusy()         : locks every interactive control during analysis
 *  - Retry button        : lets the user re-check the connection without reloading
 *
 * No external libraries. Pure DOM + fetch API.
 */

'use strict';

// ── Configuration ──────────────────────────────────────────────────────────────
const API_BASE         = 'http://127.0.0.1:8000';
const TIMEOUT_INSPECT  = 60_000;   // 60 s  – image upload + full pipeline
const TIMEOUT_DEFAULT  = 10_000;   // 10 s  – history, single record, report

// Human-readable labels for declaration keys returned by the API
const DECLARATION_LABELS = {
  mrp:                'MRP (Maximum Retail Price)',
  net_quantity:       'Net Quantity',
  manufacturer:       'Manufacturer / Packer Name',
  address:            'Manufacturer / Packer Address',
  manufacturing_date: 'Manufacturing / Packing Date',
  consumer_care:      'Consumer Care Information',
  product_name:       'Product Name',
};

// Loading step messages shown while the API call is in progress
const LOADING_STEPS = [
  'Uploading image…',
  'Preprocessing with OpenCV…',
  'Running OCR…',
  'Extracting declarations…',
  'Checking compliance rules…',
  'Saving to database…',
];

// ── State ──────────────────────────────────────────────────────────────────────
let selectedFile        = null;   // File object currently selected
let currentInspectionId = null;   // ID returned by last successful inspect call
let loadingStepTimer    = null;   // setInterval handle for step cycling
let isBusy              = false;  // true while an analysis is in flight

// ── DOM references ─────────────────────────────────────────────────────────────
const dropZone            = document.getElementById('dropZone');
const fileInput           = document.getElementById('fileInput');
const previewArea         = document.getElementById('previewArea');
const previewImg          = document.getElementById('previewImg');
const previewMeta         = document.getElementById('previewMeta');
const btnClear            = document.getElementById('btnClear');
const btnAnalyse          = document.getElementById('btnAnalyse');
const loadingCard         = document.getElementById('loadingCard');
const loadingStep         = document.getElementById('loadingStep');
const resultsPlaceholder  = document.getElementById('resultsPlaceholder');
const resultsWrapper      = document.getElementById('resultsWrapper');

const scoreNumber         = document.getElementById('scoreNumber');
const scoreBarFill        = document.getElementById('scoreBarFill');
const statusCard          = document.getElementById('statusCard');
const statusIcon          = document.getElementById('statusIcon');
const statusText          = document.getElementById('statusText');
const statusInspectionId  = document.getElementById('statusInspectionId');
const declarationsBody    = document.getElementById('declarationsBody');
const violationsList      = document.getElementById('violationsList');
const ocrText             = document.getElementById('ocrText');
const ocrTextContent      = document.getElementById('ocrTextContent');
const btnToggleOcr        = document.getElementById('btnToggleOcr');
const btnReport           = document.getElementById('btnReport');
const reportNote          = document.getElementById('reportNote');

const btnRefreshHistory   = document.getElementById('btnRefreshHistory');
const historyEmpty        = document.getElementById('historyEmpty');
const historyTableWrapper = document.getElementById('historyTableWrapper');
const historyBody         = document.getElementById('historyBody');
const historyTotal        = document.getElementById('historyTotal');
const historyStats        = document.getElementById('historyStats');
const statTotal           = document.getElementById('statTotal');
const statCompliant       = document.getElementById('statCompliant');
const statNonCompliant    = document.getElementById('statNonCompliant');
const statAvgScore        = document.getElementById('statAvgScore');
const historySearch       = document.getElementById('historySearch');
const pagePrev            = document.getElementById('pagePrev');
const pageNext            = document.getElementById('pageNext');
const pageInfo            = document.getElementById('pageInfo');
const pagination          = document.getElementById('pagination');

const connectionBanner    = document.getElementById('connectionBanner');
const connIndicator       = document.getElementById('connIndicator');
const connMessage         = document.getElementById('connMessage');
const connMeta            = document.getElementById('connMeta');
const btnConnRetry        = document.getElementById('btnConnRetry');

// ── Toast notification system ──────────────────────────────────────────────────

const toastContainer = (() => {
  const el = document.createElement('div');
  el.id = 'toast-container';
  document.body.appendChild(el);
  return el;
})();

/**
 * Show a temporary toast notification.
 * @param {string} message
 * @param {'info'|'success'|'error'} type
 */
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast${type === 'error' ? ' toast-error' : type === 'success' ? ' toast-success' : ''}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ── Centralised fetch helpers ──────────────────────────────────────────────────

/**
 * fetch() wrapper that rejects after `ms` milliseconds.
 * @param {string} url
 * @param {RequestInit} options
 * @param {number} ms  timeout in milliseconds
 * @returns {Promise<Response>}
 */
function fetchWithTimeout(url, options = {}, ms = TIMEOUT_DEFAULT) {
  const controller = new AbortController();
  const timer      = setTimeout(() => controller.abort(), ms);
  return fetch(url, { ...options, signal: controller.signal })
    .finally(() => clearTimeout(timer));
}

/**
 * Central API request helper.
 *
 * Handles:
 *  - Network / timeout errors  → clear user-facing message
 *  - Non-2xx HTTP              → extracts FastAPI `detail` field if present
 *  - Non-JSON response bodies  → falls back to HTTP status string
 *
 * @param {string} url
 * @param {RequestInit} options
 * @param {number} timeoutMs
 * @returns {Promise<any>}  parsed JSON body
 * @throws {Error}  always with a user-readable `.message`
 */
async function apiRequest(url, options = {}, timeoutMs = TIMEOUT_DEFAULT) {
  let response;
  try {
    response = await fetchWithTimeout(url, options, timeoutMs);
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error(
        `Request timed out after ${timeoutMs / 1000}s. ` +
        'Check that the backend is running and reachable.'
      );
    }
    // TypeError: Failed to fetch → server not running / CORS blocked
    throw new Error(
      'Cannot reach the backend server. ' +
      'Make sure it is running: cd backend && python run.py'
    );
  }

  // Try to parse JSON regardless of status code (FastAPI errors are JSON)
  let body;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    body = await response.json();
  } else {
    // Non-JSON body (e.g. HTML error page from a proxy)
    const text = await response.text().catch(() => '');
    body = { detail: text || `HTTP ${response.status} ${response.statusText}` };
  }

  if (!response.ok) {
    // FastAPI validation errors have a `detail` array; flatten it to a string
    let detail = body?.detail ?? `HTTP ${response.status}`;
    if (Array.isArray(detail)) {
      detail = detail.map(d => `${d.loc?.join('.')}: ${d.msg}`).join('; ');
    }
    const err = new Error(String(detail));
    err.status = response.status;
    throw err;
  }

  return body;
}

// ── Connection banner ──────────────────────────────────────────────────────────

/**
 * Set the visual state of the connection banner.
 * @param {'checking'|'ok'|'error'} state
 * @param {string} message
 * @param {string} [meta]  small secondary text (version, uptime, etc.)
 */
function setConnectionState(state, message, meta = '') {
  connectionBanner.hidden = false;
  connectionBanner.className = `connection-banner conn-${state}`;
  connMessage.textContent    = message;
  connMeta.textContent       = meta;
  btnConnRetry.hidden        = state !== 'error';
}

/**
 * Hit /api/status and update the banner.
 * Never throws — silently swallows errors and shows the error state instead.
 */
async function checkConnection() {
  setConnectionState('checking', 'Connecting to backend…');
  try {
    const data = await apiRequest(`${API_BASE}/api/status`, {}, 6000);
    const uptime = data.uptime_seconds < 60
      ? `${data.uptime_seconds}s uptime`
      : `${Math.round(data.uptime_seconds / 60)}m uptime`;
    setConnectionState(
      'ok',
      `Backend connected  ·  v${data.version}`,
      `Python ${data.python_version}  ·  ${uptime}${data.debug ? '  ·  dev mode' : ''}`
    );
    // Enable the analyse button if a file is already selected
    if (selectedFile && !isBusy) btnAnalyse.disabled = false;
  } catch (err) {
    setConnectionState(
      'error',
      'Backend not reachable — start the server before analysing.',
      err.message
    );
    // Keep analyse button disabled until connection is restored
    btnAnalyse.disabled = true;
  }
}

btnConnRetry.addEventListener('click', () => checkConnection());

// ── UI busy state ──────────────────────────────────────────────────────────────

/**
 * Lock or unlock all interactive controls.
 * Called with true at the start of an analysis, false when it completes.
 * @param {boolean} busy
 */
function setUiBusy(busy) {
  isBusy = busy;

  // Upload section
  dropZone.style.pointerEvents  = busy ? 'none' : '';
  dropZone.setAttribute('tabindex', busy ? '-1' : '0');
  fileInput.disabled            = busy;
  btnClear.disabled             = busy;
  btnAnalyse.disabled           = busy || !selectedFile;

  // Results section
  btnReport.disabled            = busy || !currentInspectionId;
  btnToggleOcr.disabled         = busy;

  // History section
  btnRefreshHistory.disabled    = busy;

  // Visual hint: dim the upload card while processing
  const uploadCard = document.getElementById('card-upload');
  uploadCard.style.opacity = busy ? '0.6' : '';
}

// ── File selection helpers ─────────────────────────────────────────────────────

const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png', 'image/bmp', 'image/tiff', 'image/webp']);
const MAX_BYTES     = 10 * 1024 * 1024; // 10 MB

/**
 * Validate a File object. Returns an error string or null if valid.
 * @param {File} file
 * @returns {string|null}
 */
function validateFile(file) {
  if (!ALLOWED_TYPES.has(file.type)) {
    return `Unsupported file type (${file.type || 'unknown'}). Please upload JPEG, PNG, BMP, TIFF, or WEBP.`;
  }
  if (file.size > MAX_BYTES) {
    return `File too large (${formatBytes(file.size)}). Maximum allowed size is 10 MB.`;
  }
  return null;
}

function formatBytes(bytes) {
  if (bytes < 1024)          return `${bytes} B`;
  if (bytes < 1024 * 1024)   return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Accept a validated File, show preview, enable buttons if backend is up.
 * @param {File} file
 */
function acceptFile(file) {
  selectedFile = file;
  btnClear.disabled = false;
  // Only enable analyse if the connection banner is showing 'ok'
  btnAnalyse.disabled = connectionBanner.classList.contains('conn-error');

  const reader = new FileReader();
  reader.onload = (e) => {
    previewImg.src      = e.target.result;
    previewArea.hidden  = false;
    previewMeta.textContent = `${file.name}  ·  ${formatBytes(file.size)}`;
  };
  reader.readAsDataURL(file);
}

/** Reset file selection and all result panels */
function clearAll() {
  selectedFile        = null;
  currentInspectionId = null;
  fileInput.value     = '';

  btnClear.disabled   = true;
  btnAnalyse.disabled = true;
  btnReport.disabled  = true;
  reportNote.textContent = '';

  previewArea.hidden       = true;
  previewImg.src           = '';
  resultsWrapper.hidden    = true;
  resultsPlaceholder.hidden = false;
  loadingCard.hidden       = true;
  stopLoadingSteps();
}

// ── Drop zone interactions ─────────────────────────────────────────────────────

dropZone.addEventListener('click', () => { if (!isBusy) fileInput.click(); });

dropZone.addEventListener('keydown', (e) => {
  if (!isBusy && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); fileInput.click(); }
});

fileInput.addEventListener('change', () => {
  if (!fileInput.files.length) return;
  const file = fileInput.files[0];
  const err  = validateFile(file);
  if (err) { showToast(err, 'error'); return; }
  acceptFile(file);
});

dropZone.addEventListener('dragover', (e) => {
  if (isBusy) return;
  e.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (isBusy) return;
  const file = e.dataTransfer.files[0];
  if (!file) return;
  const err = validateFile(file);
  if (err) { showToast(err, 'error'); return; }
  acceptFile(file);
});

btnClear.addEventListener('click', clearAll);

// ── OCR panel toggle ───────────────────────────────────────────────────────────

btnToggleOcr.addEventListener('click', () => {
  const expanded = btnToggleOcr.getAttribute('aria-expanded') === 'true';
  btnToggleOcr.setAttribute('aria-expanded', String(!expanded));
  ocrTextContent.hidden = expanded;
});

// ── Loading step cycling ───────────────────────────────────────────────────────

function startLoadingSteps() {
  let idx = 0;
  loadingStep.textContent = LOADING_STEPS[0];
  loadingStepTimer = setInterval(() => {
    idx = (idx + 1) % LOADING_STEPS.length;
    loadingStep.textContent = LOADING_STEPS[idx];
  }, 1400);
}

function stopLoadingSteps() {
  clearInterval(loadingStepTimer);
  loadingStepTimer = null;
}

// ── Compliance result rendering ────────────────────────────────────────────────

function renderScore(score, status) {
  const rounded     = Math.round(score);
  const isCompliant = status === 'COMPLIANT';

  scoreNumber.textContent = `${rounded}%`;
  scoreNumber.className   = `score-number ${isCompliant ? 'is-compliant' : 'is-noncompliant'}`;

  requestAnimationFrame(() => {
    scoreBarFill.style.width      = `${rounded}%`;
    scoreBarFill.style.background =
      rounded >= 100 ? 'var(--clr-score-high)' :
      rounded >= 60  ? 'var(--clr-score-mid)'  :
                       'var(--clr-score-low)';
  });
}

function renderStatus(status, inspectionId) {
  const isCompliant = status === 'COMPLIANT';

  statusIcon.textContent         = isCompliant ? '✔' : '✘';
  statusText.textContent         = isCompliant ? 'Compliant' : 'Non-Compliant';
  statusInspectionId.textContent = inspectionId;
  statusCard.className           = `status-card ${isCompliant ? 'is-compliant' : 'is-noncompliant'}`;
}

function renderDeclarations(declarations, declarationStatus) {
  declarationsBody.innerHTML = '';
  const allKeys = [...new Set([...Object.keys(DECLARATION_LABELS), ...Object.keys(declarations)])];

  allKeys.forEach((key) => {
    const label = DECLARATION_LABELS[key] || key.replace(/_/g, ' ');

    // Prefer declaration_status (Phase 7) — it carries found + valid + severity.
    // Fall back to raw detected_declarations for backwards compat with old DB rows.
    const ds = declarationStatus && declarationStatus[key];

    let found, valid, severity, value;
    if (ds) {
      found    = ds.found;
      valid    = ds.valid;
      severity = ds.severity || 'ERROR';
      value    = ds.value;
    } else {
      value    = declarations[key];
      found    = value !== null && value !== undefined && String(value).trim() !== '';
      valid    = found;          // no validation info available
      severity = 'ERROR';
    }

    // Choose pill class:
    //   found + valid          → pill-found  (green)
    //   found + invalid        → pill-invalid (purple)  — present but fails validation
    //   not found + WARNING    → pill-warning (amber)   — informational field
    //   not found + ERROR      → pill-missing (red)     — legally required
    let pillClass, pillLabel;
    if (found && valid) {
      pillClass = 'pill-found';   pillLabel = 'Valid';
    } else if (found && !valid) {
      pillClass = 'pill-invalid'; pillLabel = 'Invalid';
    } else if (!found && severity === 'WARNING') {
      pillClass = 'pill-warning'; pillLabel = 'Missing';
    } else {
      pillClass = 'pill-missing'; pillLabel = 'Missing';
    }

    const displayValue = found
      ? escapeHtml(String(value))
      : '<em>Not detected</em>';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="decl-name">${escapeHtml(label)}</td>
      <td class="decl-value ${found ? 'found' : ''}">${displayValue}</td>
      <td class="col-status">
        <span class="pill ${pillClass}">${pillLabel}</span>
      </td>`;
    declarationsBody.appendChild(tr);
  });
}

function renderViolations(violations) {
  violationsList.innerHTML = '';

  if (!violations.length) {
    violationsList.innerHTML = `
      <div class="violations-empty">
        <span aria-hidden="true">✔</span> All required declarations detected and valid.
      </div>`;
    return;
  }

  violations.forEach((msg) => {
    // Determine type from the [PREFIX] at the start of the message (Phase 7).
    // Fall back to 'type-notice' for legacy "OCR notice:" strings.
    let typeClass, icon;

    if (msg.startsWith('[MISSING]')) {
      typeClass = 'type-error';
      icon      = '✘';
    } else if (msg.startsWith('[INVALID]')) {
      typeClass = 'type-invalid';
      icon      = '⚠';
    } else if (msg.startsWith('[WARNING]')) {
      typeClass = 'type-warning';
      icon      = '◎';
    } else if (msg.toLowerCase().startsWith('ocr notice')) {
      typeClass = 'type-notice';
      icon      = 'ℹ';
    } else {
      // Unrecognised prefix — default to error styling
      typeClass = 'type-error';
      icon      = '✘';
    }

    // Strip the "[PREFIX]  " prefix for display — it's already conveyed by colour
    const displayMsg = msg.replace(/^\[(?:MISSING|INVALID|WARNING)\]\s*/i, '');

    const div = document.createElement('div');
    div.className = `violation-item ${typeClass}`;
    div.setAttribute('role', 'listitem');
    div.innerHTML = `
      <span class="violation-icon" aria-hidden="true">${icon}</span>
      <span>${escapeHtml(displayMsg)}</span>`;
    violationsList.appendChild(div);
  });
}

function renderOcrText(text) {
  if (text && text.trim()) {
    ocrText.textContent = text;
  } else {
    ocrText.innerHTML = '<span class="ocr-empty">No text extracted — OCR not yet configured (Phase 5).</span>';
  }
  ocrTextContent.hidden = true;
  btnToggleOcr.setAttribute('aria-expanded', 'false');
}

/**
 * Render a complete InspectionResult object into all UI panels.
 * @param {Object} data  JSON from POST /api/inspect or GET /api/inspection/{id}
 */
function renderResult(data) {
  renderScore(data.compliance_score, data.status);
  renderStatus(data.status, data.inspection_id);
  renderDeclarations(data.detected_declarations || {}, data.declaration_status || {});
  renderViolations(data.violations || []);
  renderOcrText(data.extracted_text || '');

  currentInspectionId = data.inspection_id;

  btnReport.disabled     = false;
  reportNote.textContent = '';
  reportNote.className   = 'report-note';

  resultsPlaceholder.hidden = true;
  resultsWrapper.hidden     = false;
}

// ── POST /api/inspect ──────────────────────────────────────────────────────────

btnAnalyse.addEventListener('click', async () => {
  if (!selectedFile || isBusy) return;

  setUiBusy(true);
  loadingCard.hidden        = false;
  resultsWrapper.hidden     = true;
  resultsPlaceholder.hidden = true;
  startLoadingSteps();

  try {
    const formData = new FormData();
    formData.append('file', selectedFile);

    const data = await apiRequest(
      `${API_BASE}/api/inspect`,
      { method: 'POST', body: formData },
      TIMEOUT_INSPECT
    );

    stopLoadingSteps();
    renderResult(data);
    showToast('Analysis complete.', 'success');
    loadHistory();  // refresh history silently

  } catch (err) {
    stopLoadingSteps();
    resultsPlaceholder.hidden = false;

    // Distinguish timeout/network from server errors
    const isNetwork = err.message.includes('Cannot reach') || err.message.includes('timed out');
    showToast(
      isNetwork
        ? err.message
        : `Analysis failed: ${err.message}`,
      'error'
    );

    // If network error, re-check connection and update banner
    if (isNetwork) checkConnection();
    console.error('[inspect]', err);

  } finally {
    loadingCard.hidden = true;
    setUiBusy(false);
  }
});

// ── GET /api/report/{id} ───────────────────────────────────────────────────────

btnReport.addEventListener('click', async () => {
  if (!currentInspectionId || isBusy) return;

  reportNote.textContent = 'Requesting report…';
  reportNote.className   = 'report-note';

  try {
    const response = await fetchWithTimeout(
      `${API_BASE}/api/report/${currentInspectionId}`,
      {},
      TIMEOUT_DEFAULT
    );

    if (response.status === 404) {
      reportNote.textContent = 'PDF generation not yet available (Phase 10).';
      showToast('PDF report generation will be available in Phase 10.', 'info');
      return;
    }

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Server error ${response.status}`);
    }

    const blob   = await response.blob();
    const url    = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href     = url;
    anchor.download = `compliance_report_${currentInspectionId}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);

    reportNote.textContent = 'Report downloaded.';
    reportNote.className   = 'report-note report-ready';
    showToast('Report downloaded.', 'success');

  } catch (err) {
    reportNote.textContent = `Report error: ${err.message}`;
    showToast(`Report error: ${err.message}`, 'error');
    console.error('[report]', err);
  }
});

// ── GET /api/history ───────────────────────────────────────────────────────────

function formatTimestamp(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

// ── History state ──────────────────────────────────────────────────────────────
const historyState = {
  page:      1,
  pageSize:  20,
  filter:    'all',   // 'all' | 'COMPLIANT' | 'NON_COMPLIANT'
  search:    '',
  totalPages: 1,
};

/**
 * Load stats bar from GET /api/history/stats.
 * Never throws — silently hides the bar on error.
 */
async function loadHistoryStats() {
  try {
    const data = await apiRequest(`${API_BASE}/api/history/stats`);
    statTotal.textContent       = data.total;
    statCompliant.textContent   = data.compliant;
    statNonCompliant.textContent = data.non_compliant;
    statAvgScore.textContent    = data.total > 0 ? `${Math.round(data.avg_score)}%` : '—';
    historyStats.hidden = (data.total === 0);
  } catch {
    historyStats.hidden = true;
  }
}

/**
 * Build the history table from the current historyState.
 * Calls both the list endpoint and the stats endpoint.
 */
async function loadHistory() {
  // Build query string from current state
  const params = new URLSearchParams({
    page:      historyState.page,
    page_size: historyState.pageSize,
  });
  if (historyState.filter !== 'all') params.set('status', historyState.filter);
  if (historyState.search.trim())    params.set('search', historyState.search.trim());

  try {
    const [data] = await Promise.all([
      apiRequest(`${API_BASE}/api/history?${params}`),
      loadHistoryStats(),
    ]);

    historyState.totalPages = data.total_pages ?? 1;

    if (!data.total) {
      historyEmpty.hidden        = false;
      historyTableWrapper.hidden = true;
      historyEmpty.textContent   =
        historyState.filter !== 'all' || historyState.search
          ? 'No inspections match the current filter.'
          : 'No inspections recorded yet.';
      _updatePagination(0, 1);
      return;
    }

    historyEmpty.hidden        = true;
    historyTableWrapper.hidden = false;
    historyBody.innerHTML      = '';

    data.inspections.forEach((insp) => {
      const isCompliant = insp.status === 'COMPLIANT';
      const tr          = document.createElement('tr');
      tr.innerHTML = `
        <td class="td-id">${insp.inspection_id}</td>
        <td class="td-time">${formatTimestamp(insp.timestamp)}</td>
        <td class="td-file" title="${escapeHtml(insp.image_filename)}">${escapeHtml(insp.image_filename)}</td>
        <td class="td-score" style="color:${isCompliant ? 'var(--clr-compliant)' : 'var(--clr-noncompliant)'}">
          ${Math.round(insp.compliance_score)}%
        </td>
        <td>
          <span class="pill ${isCompliant ? 'pill-found' : 'pill-missing'}">
            ${isCompliant ? 'Compliant' : 'Non-Compliant'}
          </span>
        </td>
        <td class="td-actions">
          <button class="btn-link" data-id="${insp.inspection_id}" data-action="view">View</button>
          <button class="btn-link" data-id="${insp.inspection_id}" data-action="report">Report</button>
          <button class="btn-delete" data-id="${insp.inspection_id}" data-action="delete"
                  aria-label="Delete inspection ${insp.inspection_id}" title="Delete">✕</button>
        </td>`;
      historyBody.appendChild(tr);
    });

    const start = (historyState.page - 1) * historyState.pageSize + 1;
    const end   = Math.min(historyState.page * historyState.pageSize, data.total);
    historyTotal.textContent = `Showing ${start}–${end} of ${data.total} inspection${data.total !== 1 ? 's' : ''}`;
    _updatePagination(data.total, data.total_pages);

  } catch (err) {
    historyEmpty.hidden        = false;
    historyTableWrapper.hidden = true;
    historyEmpty.textContent   = `Could not load history: ${err.message}`;
    console.error('[history]', err);
  }
}

function _updatePagination(total, totalPages) {
  historyState.totalPages = totalPages;
  const hasPrev = historyState.page > 1;
  const hasNext = historyState.page < totalPages;
  pagePrev.disabled = !hasPrev;
  pageNext.disabled = !hasNext;
  pageInfo.textContent = total > 0
    ? `Page ${historyState.page} of ${totalPages}`
    : '';
  pagination.hidden = (totalPages <= 1);
}

// History table: delegated click handler
historyBody.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn || isBusy) return;

  const id     = parseInt(btn.dataset.id, 10);
  const action = btn.dataset.action;

  if (action === 'view')   await loadInspectionById(id);
  if (action === 'report') await downloadReportById(id);
  if (action === 'delete') await deleteInspection(id, btn.closest('tr'));
});

// Filter buttons
document.querySelectorAll('.filter-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach((b) => {
      b.classList.remove('active');
      b.setAttribute('aria-pressed', 'false');
    });
    btn.classList.add('active');
    btn.setAttribute('aria-pressed', 'true');
    historyState.filter = btn.dataset.filter;
    historyState.page   = 1;
    loadHistory();
  });
});

// Search input — debounced 400 ms
let _searchTimer = null;
historySearch.addEventListener('input', () => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    historyState.search = historySearch.value;
    historyState.page   = 1;
    loadHistory();
  }, 400);
});

// Pagination buttons
pagePrev.addEventListener('click', () => {
  if (historyState.page > 1) { historyState.page--; loadHistory(); }
});
pageNext.addEventListener('click', () => {
  if (historyState.page < historyState.totalPages) { historyState.page++; loadHistory(); }
});

btnRefreshHistory.addEventListener('click', () => {
  historyState.page = 1;
  showToast('Refreshing history…', 'info');
  loadHistory();
});

async function loadInspectionById(id) {
  try {
    const data = await apiRequest(`${API_BASE}/api/inspection/${id}`);
    renderResult(data);
    document.querySelector('.column-right').scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast(`Loaded inspection #${id}`, 'success');
  } catch (err) {
    showToast(`Could not load inspection #${id}: ${err.message}`, 'error');
    console.error('[view]', err);
  }
}

async function downloadReportById(id) {
  try {
    const response = await fetchWithTimeout(
      `${API_BASE}/api/report/${id}`, {}, TIMEOUT_DEFAULT
    );
    if (response.status === 404) {
      showToast('PDF report not yet generated for this inspection (Phase 10).', 'info');
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const blob   = await response.blob();
    const url    = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href     = url;
    anchor.download = `compliance_report_${id}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
    showToast(`Report for #${id} downloaded.`, 'success');
  } catch (err) {
    showToast(`Report download failed: ${err.message}`, 'error');
    console.error('[history-report]', err);
  }
}

async function deleteInspection(id, rowEl) {
  if (!confirm(`Delete inspection #${id}? This cannot be undone.`)) return;

  try {
    const response = await fetchWithTimeout(
      `${API_BASE}/api/inspection/${id}`,
      { method: 'DELETE' },
      TIMEOUT_DEFAULT
    );

    if (response.status === 404) {
      showToast(`Inspection #${id} not found.`, 'error');
      return;
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    // Animate row out, then reload
    if (rowEl) {
      rowEl.style.transition = 'opacity .3s';
      rowEl.style.opacity    = '0';
      setTimeout(() => loadHistory(), 320);
    } else {
      loadHistory();
    }

    // If this was the currently-displayed inspection, clear results
    if (currentInspectionId === id) clearAll();

    showToast(`Inspection #${id} deleted.`, 'success');
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
    console.error('[delete]', err);
  }
}

// ── Security helper ────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Initialisation ─────────────────────────────────────────────────────────────

(function init() {
  btnReport.disabled = true;

  // Check backend connection immediately; load history once it responds
  checkConnection().then(() => loadHistory());
})();
