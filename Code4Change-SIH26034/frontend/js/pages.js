import { state, rerender } from './state.js';
import {
  API_BASE_URL,
  MAX_FILE_SIZE,
  SUPPORTED_IMAGE_TYPES,
  api,
  historyItems,
  inspectionId,
  loadHistory,
  scoreValue,
  statusValue,
} from './api.js';
import {
  arrayOf,
  bindGlobal,
  declarationTable,
  disclaimer,
  emptyHistory,
  errorPanel,
  esc,
  formatDate,
  historyTable,
  idFromPath,
  loadingPanel,
  navigate,
  shell,
  showToast,
  statusChip,
} from './ui.js';

export function dashboard() {
  if (!state.history && !state.historyError && !state.historyLoading) loadHistory();

  const items = historyItems();
  const scores = items.map(scoreValue).filter((value) => typeof value === 'number');
  const findings = items.reduce((sum, item) => sum + arrayOf(item?.violations).length, 0);
  const content = `<div class="content"><div class="header-row"><div class="header-copy">
    <div class="eyebrow">Field workspace</div>
    <h1>Good checks start with good evidence.</h1>
    <p>Review packaged commodity labels with a clear record of what was seen, what was read, and what deserves attention.</p>
  </div><button class="button button-primary" data-nav="/inspect">+ New inspection</button></div>
  ${disclaimer()}${state.historyLoading ? loadingPanel('Loading recent inspections') : state.historyError ? `<div class="panel">${errorPanel(state.historyError)}</div>` : `<div class="metrics">
    <div class="metric metric-teal"><div class="metric-label">Completed inspections</div><div class="metric-value">${items.length}</div><div class="metric-note">Records available in this workspace</div></div>
    <div class="metric metric-accent"><div class="metric-label">Average score</div><div class="metric-value">${scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 'Not available'}</div><div class="metric-note">${scores.length ? 'Based on available inspection scores' : 'No score was provided'}</div></div>
    <div class="metric metric-coral"><div class="metric-label">Findings to review</div><div class="metric-value">${items.length ? findings : 'Not available'}</div><div class="metric-note">Listed in completed inspections</div></div>
    <div class="metric metric-mint"><div class="metric-label">Service status</div><div class="metric-value" style="font-size:18px;margin-top:17px">Ready</div><div class="metric-note">You can start a new inspection</div></div>
  </div><div class="grid-2"><section class="panel"><div class="panel-head"><div><h2>Recent inspections</h2><p>Your latest completed checks</p></div><button class="button button-quiet" data-nav="/history">View history</button></div>${historyTable(items.slice(0, 5))}</section>
  <section class="panel"><div class="panel-head"><div><h2>Operator notes</h2><p>Keep every check grounded in evidence</p></div></div><div class="panel-body"><div class="signal-list">
    <div class="signal"><i class="signal-mark"></i><div><strong>Photograph the full label</strong><span>Include declarations and net quantity where possible. Avoid glare and cropped edges.</span></div></div>
    <div class="signal"><i class="signal-mark warn"></i><div><strong>Treat scores as signals</strong><span>The preliminary result is not a legal conclusion. Use the evidence view to verify what was actually read.</span></div></div>
    <div class="signal"><i class="signal-mark alert"></i><div><strong>Escalate uncertainty</strong><span>When a finding is listed or text is incomplete, route the record to your compliance lead.</span></div></div>
  </div></div></section></div>`}</div>`;

  shell(content, 'Overview');
}

export function inspectPage() {
  const content = `<div class="content"><div class="header-row"><div class="header-copy">
    <div class="eyebrow">New inspection</div><h1>Capture a packaged commodity.</h1>
    <p>Upload one label image and review the findings when the assessment is complete.</p>
  </div></div>${disclaimer()}<div class="upload-layout">
    <section class="panel"><div class="panel-head"><div><h2>Choose a label image</h2><p>JPEG, PNG, BMP, TIFF, or WEBP · use the clearest available frame</p></div></div><div class="panel-body"><div class="dropzone" id="dropzone">
      <div class="upload-glyph">↑</div><h2>Drop an image here</h2><p>Or choose a file from this device. The preview stays in your browser until you choose Analyze.</p>
      <input id="file-input" type="file" accept="image/jpeg,image/png,image/bmp,image/tiff,image/webp" hidden>
      <button class="button button-primary" data-action="choose-file">Choose image</button><div id="file-detail"></div>
    </div></div></section>
    <section class="panel"><div class="panel-head"><div><h2>Review image</h2><p>Check framing before analysis</p></div></div><div class="panel-body">
      <div class="preview" id="preview"><div class="preview-empty">No image selected<br><span>Nothing is sent until you choose Analyze.</span></div></div>
      <div id="selected-file"></div><div style="display:flex;justify-content:flex-end;margin-top:18px"><button class="button button-primary" data-action="submit-inspection" disabled id="analyze-btn">Analyze image</button></div>
    </div></section>
  </div></div>`;

  shell(content, 'New inspection');
  bindUpload();
}

function bindUpload() {
  const input = document.getElementById('file-input');
  const drop = document.getElementById('dropzone');
  const button = document.getElementById('analyze-btn');
  if (!input || !drop || !button) return;

  input.addEventListener('change', () => selectFile(input.files?.[0]));
  ['dragenter', 'dragover'].forEach((name) => drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach((name) => drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove('drag');
  }));
  drop.addEventListener('drop', (event) => selectFile(event.dataTransfer.files?.[0]));
  button.addEventListener('click', submitInspection);

  function selectFile(file) {
    if (!file) return;
    if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
      showToast('Please choose a JPG, PNG, BMP, TIFF, or WEBP image.');
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      showToast('Please choose an image smaller than 10 MB.');
      return;
    }

    state.selectedFile = file;
    if (state.currentImage) URL.revokeObjectURL(state.currentImage);
    state.currentImage = URL.createObjectURL(file);
    document.getElementById('preview').innerHTML = `<img src="${state.currentImage}" alt="Selected package label preview">`;
    document.getElementById('selected-file').innerHTML = `<div class="file-row"><div><strong>${esc(file.name)}</strong><span>${Math.round(file.size / 1024)} KB · ${esc(file.type)}</span></div><button class="button button-quiet" data-action="clear-file">Remove</button></div>`;
    document.querySelector('[data-action="clear-file"]').addEventListener('click', clearFile);
    button.disabled = false;
  }

  function clearFile() {
    state.selectedFile = null;
    if (state.currentImage) URL.revokeObjectURL(state.currentImage);
    state.currentImage = null;
    document.getElementById('preview').innerHTML = '<div class="preview-empty">No image selected<br><span>Nothing is sent until you choose Analyze.</span></div>';
    document.getElementById('selected-file').innerHTML = '';
    button.disabled = true;
  }
}

export async function submitInspection() {
  if (!state.selectedFile) return;
  renderProcessing();
  const form = new FormData();
  form.append('file', state.selectedFile);

  try {
    const result = await api('/api/inspect', { method: 'POST', body: form });
    const id = inspectionId(result) || result?.inspection?.inspection_id || result?.inspection?.id;
    if (id) {
      state.inspection = result?.inspection || result;
      navigate(`/inspection/${encodeURIComponent(id)}`);
    } else {
      showToast('The inspection did not return a reference number.');
      navigate('/history');
    }
  } catch (error) {
    renderErrorPage(error.message, '/inspect');
  }
}

function renderProcessing() {
  shell(`<div class="content"><div class="processing"><div class="eyebrow">Inspection in progress</div><div class="processing-card">
    <div class="upload-glyph" style="margin:0 auto 20px">◌</div><h1>Reviewing the label</h1><p class="muted">This may take a moment. Please keep this window open while the assessment is completed.</p><div class="processing-rule"><span></span></div>
  </div></div></div>`, 'Processing');
}

async function loadInspection(id) {
  state.inspectionLoading = true;
  rerender();
  try {
    state.inspection = await api(`/api/inspection/${encodeURIComponent(id)}`);
  } catch (error) {
    state.inspection = { __error: error.message };
  } finally {
    state.inspectionLoading = false;
    rerender();
  }
}

export function resultPage() {
  const id = idFromPath();
  if (!state.inspection && !state.inspectionLoading) loadInspection(id);
  if (state.inspectionLoading || !state.inspection) {
    shell(`<div class="content">${loadingPanel('Loading inspection details')}</div>`, 'Inspection details');
    return;
  }
  if (state.inspection.__error) {
    shell(`<div class="content"><div class="panel">${errorPanel(state.inspection.__error, 'reload-inspection')}</div></div>`, 'Inspection details');
    return;
  }

  const item = state.inspection;
  const image = state.currentImage;
  const declarations = item.detected_declarations;
  const violations = arrayOf(item.violations);
  const score = scoreValue(item);
  const reference = inspectionId(item) || id;

  const content = `<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Inspection result</div><h1>Inspection details</h1><p>Reference <span class="mono">${esc(reference)}</span> · ${formatDate(item.timestamp || item.created_at)}</p></div><div style="display:flex;gap:9px"><a class="button" href="${API_BASE_URL}/api/report/${encodeURIComponent(reference)}" target="_blank" rel="noopener">View report</a><button class="button button-primary" data-action="print-report">Print record</button></div></div>${disclaimer()}
  <section class="panel"><div class="result-top">${image ? `<img class="result-image" src="${esc(image)}" alt="Inspection image">` : `<div class="preview-empty">Image preview is only available during the upload session.</div>`}<div><div class="eyebrow">Assisted review result</div><h2>${esc(item.image_filename || 'Image name unavailable')}</h2><div class="result-meta"><span class="tag">Reference ${esc(reference)}</span>${statusChip(item)}<span class="tag">${formatDate(item.timestamp || item.created_at)}</span></div><p class="muted" style="line-height:1.55;margin:0">This is a preliminary assessment based on the information read from the label. Review the image and applicable requirements before making a decision.</p></div><div class="score"><div class="score-number">${score == null ? 'Not available' : esc(score)}</div><div class="score-label">Compliance score</div></div></div></section>
  <section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>Label details</h2><p>Information read from the package label</p></div></div><div class="declaration-table">${declarationTable(declarations)}</div></section>
  <div class="result-sections"><section class="list-card warning"><h3>Findings <span class="tag">${violations.length}</span></h3>${violations.length ? `<ul>${violations.map((value) => `<li><span class="bullet">!</span>${esc(typeof value === 'object' ? JSON.stringify(value) : value)}</li>`).join('')}</ul>` : `<div class="empty" style="padding:28px 0"><p>No findings were listed for this inspection.</p></div>`}</section>
  <section class="list-card"><h3>Text read from label</h3><div class="ocr-box">${esc(item.extracted_text || 'No text was returned.')}</div><button class="button button-quiet" style="margin-top:12px" data-action="copy-ocr">Copy text</button></section></div>
  <section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>Image evidence</h2><p>Review the original image and the details read from it</p></div></div><div class="panel-body">${image ? `<img style="width:100%;max-height:320px;object-fit:contain;background:var(--surface-soft);border-radius:5px;margin-top:10px" src="${esc(image)}" alt="Original inspection evidence">` : `<div class="preview-empty" style="margin-top:12px">Image preview is unavailable after reopening this record.</div>`}</div></section>
  <section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>Review checklist</h2><p>Use this preliminary result alongside your required review</p></div></div><div class="panel-body"><div class="checklist">${violations.length ? violations.map((value) => `<div class="check-item warn"><div class="check-icon">!</div><div><strong>Finding to review</strong><p>${esc(typeof value === 'object' ? JSON.stringify(value) : value)}</p></div></div>`).join('') : `<div class="check-item"><div class="check-icon">+</div><div><strong>No findings were listed</strong><p>This is not a declaration of compliance; review the image and applicable requirements.</p></div></div>`}<div class="reference-box"><strong>Regulatory reference</strong><br>Educational context only. Confirm requirements with the applicable regulator before making a determination.</div></div></div></section></div>`;
  shell(content, 'Inspection details');
}

export function historyPage() {
  if (!state.history && !state.historyError && !state.historyLoading) loadHistory();
  const content = `<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Records</div><h1>Inspection history</h1><p>Search and review completed inspections.</p></div><button class="button button-primary" data-nav="/inspect">+ New inspection</button></div>
  <div class="toolbar"><div class="toolbar-left"><input id="history-search" type="search" placeholder="Search reference or image name" aria-label="Search inspections"><select id="history-filter" aria-label="Filter by status"><option value="">All statuses</option><option value="compliant">Compliant</option><option value="review">Review needed</option><option value="violation">Needs attention</option></select></div><div class="toolbar-right"><button class="button" data-action="refresh-history">Refresh</button></div></div>
  <section class="panel">${state.historyLoading ? loadingPanel('Loading inspection history') : state.historyError ? errorPanel(state.historyError) : historyTable(historyItems(), { pagination: true })}</section></div>`;
  shell(content, 'History');
  bindHistoryFilters();
}

function bindHistoryFilters() {
  const search = document.getElementById('history-search');
  const filter = document.getElementById('history-filter');
  if (!search) return;

  const update = () => {
    const query = search.value.toLowerCase();
    const wanted = filter.value;
    const rows = historyItems().filter((item) => `${inspectionId(item)} ${item.image_filename || item.filename || ''}`.toLowerCase().includes(query) && (!wanted || statusValue(item).includes(wanted)));
    const table = document.querySelector('.panel');
    table.innerHTML = historyTable(rows, { pagination: true });
    bindGlobal();
  };

  search.addEventListener('input', update);
  filter.addEventListener('change', update);
}

export function reportsPage() {
  if (!state.history && !state.historyError && !state.historyLoading) loadHistory();
  const items = historyItems();
  const body = state.historyLoading ? loadingPanel('Loading reports') : state.historyError ? errorPanel(state.historyError) : items.length ? historyTable(items) : emptyHistory();
  shell(`<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Reporting</div><h1>Reports</h1><p>Open a report for any completed inspection.</p></div><button class="button button-primary" data-nav="/inspect">+ New inspection</button></div><div class="notice"><strong>Inspection reports</strong><br>Reports are generated from your inspection records and open in a new tab.</div><section class="panel" style="margin-top:18px">${body}</section></div>`, 'Reports');
}

export function analyticsPage() {
  if (!state.history && !state.historyError && !state.historyLoading) loadHistory();
  const items = historyItems();
  const scores = items.map(scoreValue).filter((value) => typeof value === 'number');
  const enough = items.length >= 3 && scores.length > 0;
  const bars = scores.slice(-7).map((score, index) => `<div class="bar-col"><div class="bar" style="height:${Math.max(6, Math.min(100, score))}%"></div><span class="bar-label">${index + 1}</span></div>`).join('');

  shell(`<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Signals</div><h1>Analytics</h1><p>Simple signals based on completed inspections.</p></div></div>${state.historyLoading ? loadingPanel('Loading inspection signals') : state.historyError ? `<div class="panel">${errorPanel(state.historyError)}</div>` : enough ? `<div class="metrics"><div class="metric metric-teal"><div class="metric-label">Scored inspections</div><div class="metric-value">${scores.length}</div><div class="metric-note">With a score available</div></div><div class="metric metric-accent"><div class="metric-label">Average score</div><div class="metric-value">${Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)}</div><div class="metric-note">Simple average</div></div></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><h2>Score sequence</h2><p>Recent scored inspections</p></div></div><div class="panel-body"><div class="bars">${bars}</div><div class="legend"><span><i></i>Compliance score</span></div></div></section><section class="panel"><div class="panel-head"><h2>Reading this view</h2></div><div class="panel-body"><p class="muted" style="line-height:1.7;font-size:12px">These signals are intentionally simple. They do not infer a trend or category from missing information.</p></div></section></div>` : `<section class="panel">${items.length ? `<div class="empty"><div class="empty-mark">∿</div><h3>Not enough scored inspections yet</h3><p>Analytics becomes useful after at least three inspections with numeric scores are available.</p><button class="button" data-action="refresh-history">Refresh history</button></div>` : emptyHistory()}</section>`}</div>`, 'Analytics');
}

export function rulesPage() {
  shell(`<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Reference library</div><h1>Compliance rules</h1><p>Use this page as an educational orientation, not as a substitute for the requirements that govern your commodity and market.</p></div></div><div class="reference-box"><strong>Regulatory reference · educational only</strong><br>No jurisdiction, commodity, or authority-specific rules are loaded here. Nothing on this page should be treated as a legal observation or a complete checklist.</div><div class="result-sections" style="margin-top:18px"><section class="list-card"><h3>What to verify</h3><div class="checklist"><div class="check-item"><div class="check-icon">01</div><div><strong>Identity and common name</strong><p>Confirm the label identifies the packaged commodity in the manner required by the applicable authority.</p></div></div><div class="check-item"><div class="check-icon">02</div><div><strong>Net quantity statement</strong><p>Check the declared quantity, units, placement, and legibility against the governing standard.</p></div></div><div class="check-item"><div class="check-icon">03</div><div><strong>Responsible party</strong><p>Verify the responsible business or packer information where the applicable rule requires it.</p></div></div></div></section><section class="list-card warning"><h3>What Code4Change does not decide</h3><ul><li><span class="bullet">!</span>Jurisdiction-specific legal compliance.</li><li><span class="bullet">!</span>Whether an authority will accept a label.</li><li><span class="bullet">!</span>Enforcement, recall, or disposition decisions.</li></ul></section></div></div>`, 'Compliance rules');
}

export function helpPage() {
  shell(`<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Inspector guide</div><h1>How it works</h1><p>A short, field-ready workflow for collecting evidence and deciding what needs a closer review.</p></div></div><div class="grid-2"><section class="panel"><div class="panel-head"><h2>Four steps, one record</h2></div><div class="panel-body"><div class="checklist"><div class="check-item"><div class="check-icon">01</div><div><strong>Capture</strong><p>Choose a clear image of the full package label. Check framing, glare, and cropped edges before continuing.</p></div></div><div class="check-item"><div class="check-icon">02</div><div><strong>Analyze</strong><p>Start the assessment and keep this window open while the label is reviewed.</p></div></div><div class="check-item"><div class="check-icon">03</div><div><strong>Review evidence</strong><p>Read the text, label details, findings, score, and status together with the original image.</p></div></div><div class="check-item"><div class="check-icon">04</div><div><strong>Report or escalate</strong><p>Open the inspection report and route uncertain or flagged records to your compliance lead.</p></div></div></div></div></section><section class="panel"><div class="panel-head"><h2>When the service is unavailable</h2></div><div class="panel-body"><p class="muted" style="line-height:1.7;font-size:12px">The interface will show a clear unavailable state. It will not create placeholder inspections, scores, or history rows. Try again when the inspection service is reachable.</p><div class="notice" style="margin-top:18px"><strong>Your records stay evidence-based</strong><br>Only information returned for your inspection is shown in the result.</div></div></section></div></div>`, 'How it works');
}

export function settingsPage() {
  const serviceLabel = state.healthError ? 'Unavailable' : state.health ? 'Ready' : 'Checking';
  shell(`<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Workspace</div><h1>Settings</h1><p>Manage preferences for this inspection workspace.</p></div></div><div class="settings-grid"><nav class="settings-nav" aria-label="Settings sections"><button class="active">Workspace</button><button>Notifications</button><button>Data handling</button></nav><section class="panel"><div class="panel-head"><div><h2>Workspace preferences</h2><p>Simple options for your inspection desk</p></div></div><div class="panel-body form-stack"><div><label>Service status</label><div class="notice">${serviceLabel}. The inspection service status is checked automatically.</div></div><div><label>Image handling</label><div class="notice">Selected images are shown in this browser before you choose to analyze them.</div></div><div><label for="interface-density">Interface density</label><select id="interface-density"><option>Comfortable</option><option>Compact</option></select></div><div style="display:flex;justify-content:flex-end"><button class="button button-primary" data-action="save-settings">Save preferences</button></div></div></section></div></div>`, 'Settings');
}

export function reportPage() {
  const id = idFromPath();
  if (!state.inspection && !state.inspectionLoading) loadInspection(id);
  if (state.inspectionLoading || !state.inspection) {
    shell(`<div class="content">${loadingPanel('Loading report')}</div>`, 'Report');
    return;
  }
  if (state.inspection.__error) {
    shell(`<div class="content"><div class="panel">${errorPanel(state.inspection.__error, 'reload-inspection')}</div></div>`, 'Report');
    return;
  }

  const item = state.inspection;
  const reference = inspectionId(item) || id;
  shell(`<div class="content"><div class="header-row"><div class="header-copy"><div class="eyebrow">Report view</div><h1>Inspection report</h1><p>Reference <span class="mono">${esc(reference)}</span> · Review the completed record</p></div><a class="button button-primary" href="${API_BASE_URL}/api/report/${encodeURIComponent(reference)}" target="_blank" rel="noopener">Open PDF report</a></div>${disclaimer()}<section class="panel"><div class="panel-head"><div><h2>Inspection summary</h2><p>Use this record to support your final review</p></div>${statusChip(item)}</div><div class="panel-body"><div class="result-sections" style="margin-top:0"><div><div class="eyebrow">Inspection record</div><div class="checklist"><div class="check-item"><div><strong>Reference</strong><p class="mono">${esc(reference)}</p></div></div><div class="check-item"><div><strong>Date and time</strong><p>${formatDate(item.timestamp || item.created_at)}</p></div></div><div class="check-item"><div><strong>Image name</strong><p>${esc(item.image_filename || 'Not returned')}</p></div></div><div class="check-item"><div><strong>Compliance score</strong><p>${scoreValue(item) == null ? 'Not available' : esc(scoreValue(item))}</p></div></div></div></div><div><div class="eyebrow">Evidence</div><div class="ocr-box">${esc(item.extracted_text || 'No text was returned.')}</div><h3 style="margin:20px 0 8px">Label details</h3>${declarationTable(item.detected_declarations)}<h3 style="margin:20px 0 8px">Findings</h3><p class="muted" style="line-height:1.6;font-size:12px">${esc(arrayOf(item.violations).map((value) => typeof value === 'object' ? JSON.stringify(value) : value).join(' · ') || 'None listed')}</p></div></div></div></section></div>`, 'Report');
}

export function renderErrorPage(message, retry) {
  shell(`<div class="content"><section class="panel">${errorPanel(message, retry)}</section></div>`, 'Service unavailable');
}

export { bindUpload };