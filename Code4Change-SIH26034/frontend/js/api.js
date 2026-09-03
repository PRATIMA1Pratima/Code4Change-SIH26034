import { state, rerender } from './state.js';

const API_BASE_URL = 'http://127.0.0.1:8000';
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const SUPPORTED_IMAGE_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/bmp',
  'image/tiff',
  'image/webp',
]);

export { API_BASE_URL, MAX_FILE_SIZE, SUPPORTED_IMAGE_TYPES };

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const body = await response.text();
  let data;

  try {
    data = body ? JSON.parse(body) : null;
  } catch {
    data = body;
  }

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || 'The inspection service returned an error.');
  }

  return data;
}

export async function loadHistory() {
  state.historyLoading = true;
  state.historyError = null;
  rerender();

  try {
    state.history = await api('/api/history?page=1&page_size=20');
  } catch (error) {
    state.historyError = error.message;
  } finally {
    state.historyLoading = false;
    rerender();
  }
}

export async function loadHealth() {
  if (state.healthLoading || state.health || state.healthError) return;

  state.healthLoading = true;
  rerender();

  try {
    state.health = await api('/health');
  } catch (error) {
    state.healthError = error.message;
  } finally {
    state.healthLoading = false;
    rerender();
  }
}

export function historyItems() {
  const source = state.history;
  if (Array.isArray(source)) return source;
  return source?.items || source?.inspections || source?.results || [];
}

export function inspectionId(item) {
  return item?.inspection_id ?? item?.id ?? item?.inspectionId;
}

export function statusValue(item) {
  return String(item?.status ?? item?.result ?? '').toLowerCase();
}

export function scoreValue(item) {
  return item?.compliance_score ?? item?.score;
}