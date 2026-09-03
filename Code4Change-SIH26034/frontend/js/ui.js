import { state, rerender } from './state.js';
import { historyItems, inspectionId, scoreValue, statusValue } from './api.js';
import { bindMobileMenu, mobileMenuMarkup } from './mobile-menu.js';

const root = document.getElementById('root');
let actions = {};
let toastTimer;

export function registerActions(actionMap) {
  actions = actionMap;
}

export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#039;',
}[char]));

export const arrayOf = (value) => Array.isArray(value) ? value : (value ? [value] : []);

export function formatDate(value) {
  if (!value) return 'Date not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? esc(value)
    : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export const idFromPath = () => decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');

export const pageName = () => location.pathname === '/'
  ? 'dashboard'
  : location.pathname.split('/')[1];

export function navigate(path) {
  history.pushState({}, '', path);
  rerender();
  window.scrollTo(0, 0);
}

export function showToast(message) {
  clearTimeout(toastTimer);
  document.querySelector('.toast')?.remove();
  const node = document.createElement('div');
  node.className = 'toast';
  node.textContent = message;
  document.body.append(node);
  toastTimer = setTimeout(() => node.remove(), 4200);
}

function icon(label) {
  return `<span class="nav-icon" aria-hidden="true">${label}</span>`;
}

function navButton(path, label, glyph) {
  const active = pageName() === path.replace('/', '') || (path === '/' && pageName() === 'dashboard');
  return `<button data-nav="${path}" class="${active ? 'active' : ''}" aria-label="${label}">${icon(glyph)}<span>${label}</span></button>`;
}

function sidebarNavigation() {
  return `<nav class="nav" aria-label="Primary navigation">
      ${navButton('/', 'Overview', '01')}
      ${navButton('/inspect', 'New inspection', '+')}
      ${navButton('/history', 'History', '≡')}
      ${navButton('/reports', 'Reports', '↗')}
      ${navButton('/analytics', 'Analytics', '∿')}
    </nav>
    <div class="nav-label" style="margin-top:24px">Reference</div>
    <nav class="nav" aria-label="Reference navigation">
      ${navButton('/rules', 'Compliance rules', '□')}
      ${navButton('/help', 'How it works', '?')}
      ${navButton('/settings', 'Settings', '·')}
    </nav>`;
}

function serviceStatus() {
  if (state.healthError) {
    return '<i class="status-dot" style="background:var(--coral)"></i> Service unavailable';
  }
  if (state.health) {
    return '<i class="status-dot"></i> Service ready';
  }
  return '<i class="status-dot" style="background:var(--ochre)"></i> Checking service';
}

export function shell(content, title) {
  root.innerHTML = `<div class="shell">
    <aside class="sidebar">
      <a class="brand" href="/" data-nav="/" aria-label="Code4Change overview">
        <div class="brand-mark">C4</div>
        <div><strong>Code4Change</strong><span>Compliance desk</span></div>
      </a>
      <div class="nav-label">Workspace</div>
      ${sidebarNavigation()}
      <div class="sidebar-bottom">
        <div class="connection"><i class="status-dot"></i><span>Service status monitored</span></div>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="crumb"><strong>${esc(title)}</strong><span> / Code4Change</span></div>
        <div class="top-actions">
          <div class="service-status">${serviceStatus()}</div>
          ${mobileMenuMarkup()}
          <div class="avatar" aria-label="Compliance team">CT</div>
        </div>
      </header>
      ${content}
    </main>
  </div>`;
  bindGlobal();
  bindMobileMenu();
}

export function bindGlobal() {
  document.querySelectorAll('[data-nav]').forEach((element) => {
    element.addEventListener('click', (event) => {
      event.preventDefault();
      navigate(element.dataset.nav);
    });
  });

  document.querySelectorAll('[data-action]').forEach((element) => {
    element.addEventListener('click', () => actions[element.dataset.action]?.(element));
  });
}

export const disclaimer = () => `<div class="disclaimer">
  <div class="disclaimer-mark">!</div>
  <div><b>Preliminary check only.</b> This AI-assisted result supports inspection work. It does not replace qualified regulatory review or a legal determination. Confirm against the applicable authority before taking action.</div>
</div>`;

export const loadingPanel = (title = 'Loading inspection') => `<div class="panel">
  <div class="panel-body">
    <div class="skeleton">${esc(title)}<span></span></div>
    <div class="skeleton short"><span></span></div>
  </div>
</div>`;

function friendlyError(message) {
  const text = String(message || '');
  if (/failed to fetch|networkerror|load failed|connection refused/i.test(text)) {
    return 'The inspection service is not available right now.';
  }
  return text || 'Something went wrong while completing this action.';
}

export function errorPanel(message, retryAction = 'load-history') {
  const retry = String(retryAction).startsWith('/')
    ? `data-nav="${retryAction}"`
    : `data-action="${retryAction}"`;
  return `<div class="empty">
    <div class="empty-mark">/ /</div>
    <h3>We could not complete that request</h3>
    <p>${esc(friendlyError(message))} Please try again when the inspection service is available.</p>
    <button class="button button-primary" ${retry}>Try again</button>
  </div>`;
}

export function emptyHistory() {
  return `<div class="empty">
    <div class="empty-mark">—</div>
    <h3>No inspections yet</h3>
    <p>Your completed inspections will appear here. Start with a clear, well-lit image of the package label.</p>
    <button class="button button-primary" data-nav="/inspect">Start an inspection</button>
  </div>`;
}

export function statusChip(item) {
  const status = statusValue(item);
  const non = status.includes('non') || status.includes('violation');
  const review = status.includes('review') || status.includes('warning');
  const processing = status.includes('process');
  const cls = non ? 'status-non' : review ? 'status-review' : processing ? 'status-processing' : 'status-compliant';
  const label = non ? 'Needs attention' : review ? 'Review needed' : processing ? 'In progress' : item?.status || 'Result returned';
  return `<span class="status ${cls}">${esc(label)}</span>`;
}

export function historyTable(items, options = {}) {
  if (!items.length) return emptyHistory();

  return `<div class="table-wrap"><table><thead><tr>
    <th>Reference</th><th>Captured</th><th>Score</th><th>Outcome</th><th>Actions</th>
  </tr></thead><tbody>${items.map((item, index) => {
    const id = inspectionId(item);
    return `<tr data-testid="row-inspection-${esc(id || index)}">
      <td><strong class="mono">${esc(id || 'Reference unavailable')}</strong><br><span class="muted">${esc(item?.image_filename || item?.filename || 'Image name unavailable')}</span></td>
      <td>${formatDate(item?.timestamp || item?.created_at || item?.createdAt)}</td>
      <td><strong>${scoreValue(item) == null ? 'Not available' : esc(scoreValue(item))}</strong></td>
      <td>${statusChip(item)}</td>
      <td><button class="button button-quiet" data-action="view-inspection" data-id="${esc(id)}">View</button>${id ? `<button class="button button-quiet" data-action="report" data-id="${esc(id)}">Report</button>` : ''}</td>
    </tr>`;
  }).join('')}</tbody></table></div>${options.pagination ? `<div class="pagination"><span class="page-note">Showing available records</span><button class="button" data-action="refresh-history">Refresh</button></div>` : ''}`;
}

export function declarationTable(values) {
  const fields = [
    ['mrp', 'MRP'],
    ['net_quantity', 'Net quantity'],
    ['manufacturer', 'Manufacturer / packer'],
    ['address', 'Address'],
    ['manufacturing_date', 'Manufacturing / packing date'],
    ['consumer_care', 'Consumer care information'],
  ];

  if (!values || typeof values !== 'object' || Array.isArray(values)) {
    return '<div class="empty" style="padding:28px"><p>No label details were returned for this inspection.</p></div>';
  }

  return `<div class="table-wrap"><table><thead><tr><th>Label detail</th><th>What was read</th><th>Status</th></tr></thead><tbody>${fields.map(([key, label]) => {
    const value = values[key];
    const detected = value !== null && value !== undefined && String(value).trim() !== '';
    return `<tr><td><strong>${label}</strong></td><td>${detected ? esc(value) : '<span class="muted">Not detected</span>'}</td><td><span class="declaration-status ${detected ? 'is-detected' : 'is-missing'}">${detected ? 'Detected' : 'Not detected'}</span></td></tr>`;
  }).join('')}</tbody></table></div>`;
}

export { historyItems, scoreValue };