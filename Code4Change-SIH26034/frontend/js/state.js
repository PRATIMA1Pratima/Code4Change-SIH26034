export const state = {
  history: null,
  historyError: null,
  historyLoading: false,
  health: null,
  healthError: null,
  healthLoading: false,
  selectedFile: null,
  currentImage: null,
  inspection: null,
  inspectionLoading: false,
};

let renderApplication = () => {};

export function setRenderer(renderer) {
  renderApplication = renderer;
}

export function rerender() {
  renderApplication();
}