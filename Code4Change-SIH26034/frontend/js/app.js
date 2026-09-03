import { state, setRenderer } from './state.js';
import { loadHealth, loadHistory } from './api.js';
import {
  analyticsPage,
  dashboard,
  helpPage,
  historyPage,
  inspectPage,
  renderErrorPage,
  reportPage,
  reportsPage,
  resultPage,
  rulesPage,
  settingsPage,
  submitInspection,
} from './pages.js';
import { navigate, registerActions, showToast } from './ui.js';

const actions = {
  'choose-file': () => document.getElementById('file-input')?.click(),
  'submit-inspection': submitInspection,
  'view-inspection': (element) => {
    state.inspection = null;
    navigate(`/inspection/${encodeURIComponent(element.dataset.id)}`);
  },
  report: (element) => {
    state.inspection = null;
    navigate(`/report/${encodeURIComponent(element.dataset.id)}`);
  },
  'print-report': () => window.print(),
  'refresh-history': () => {
    state.history = null;
    loadHistory();
  },
  'load-history': () => {
    state.history = null;
    loadHistory();
  },
  'reload-inspection': () => {
    state.inspection = null;
    render();
  },
  'copy-ocr': () => {
    const text = state.inspection?.extracted_text || '';
    if (!text) return;
    navigator.clipboard?.writeText(text)
      .then(() => showToast('Text copied.'))
      .catch(() => showToast('Copy is unavailable in this browser.'));
  },
  'save-settings': () => showToast('Preferences saved for this browser session.'),
};

function render() {
  loadHealth();
  const path = location.pathname;

  if (path === '/' || path === '') dashboard();
  else if (path === '/inspect') inspectPage();
  else if (path.startsWith('/inspection/')) resultPage();
  else if (path === '/history') historyPage();
  else if (path === '/reports') reportsPage();
  else if (path.startsWith('/report/')) reportPage();
  else if (path === '/analytics') analyticsPage();
  else if (path === '/rules') rulesPage();
  else if (path === '/help') helpPage();
  else if (path === '/settings') settingsPage();
  else renderErrorPage('This page does not exist.', '/');
}

registerActions(actions);
setRenderer(render);
window.addEventListener('popstate', render);
render();