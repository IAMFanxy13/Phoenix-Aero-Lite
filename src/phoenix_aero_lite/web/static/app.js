const form = document.querySelector('#job-form');
const fileInput = document.querySelector('#model');
const fileLabel = document.querySelector('#file-label');
const submitButton = document.querySelector('#submit-button');
const cancelButton = document.querySelector('#cancel-button');
const errorBox = document.querySelector('#form-error');
const viewer = document.querySelector('#model-viewer');
const viewerPlaceholder = document.querySelector('#viewer-placeholder');
const viewerBusy = document.querySelector('#viewer-busy');
const targetCellSizeInput = document.querySelector('[name="target_cell_size_m"]');
// The scientific target is a continuous positive length.  The template's
// decimal spinner increment must never make its own default value invalid.
targetCellSizeInput.step = 'any';
let currentJobId = null;
let currentGridStudyId = null;
let currentModel = null;
let currentJob = null;
let pollTimer = null;
let pollFailures = 0;
let wingSelectionBusy = false;
let pendingWingSelection = null;
let viewerLoadSequence = 0;
let modelRequestSequence = 0;
let sceneRequestSequence = 0;
let activeSceneName = 'model';
const scalarManualRanges = { cp: null, pressure: null, yplus: null };
let axesVisible = true;
let colorbarVisible = true;
const orientationUndo = [];
let preflightReady = false;
let presetCatalog = [];

async function requestJson(url, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* handled by status below */ }
    if (!response.ok) throw new Error(payload.detail?.code || `HTTP_${response.status}`);
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('REQUEST_TIMEOUT');
    if (error instanceof TypeError) throw new Error('BACKEND_UNAVAILABLE');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function loadPreflight() {
  const status = document.querySelector('#preflight-status');
  const details = document.querySelector('#preflight-details');
  try {
    const report = await requestJson('/api/preflight', {}, 30000);
    preflightReady = report.ready === true;
    status.classList.toggle('blocked', !preflightReady);
    status.classList.toggle('ready', preflightReady);
    status.lastChild.textContent = preflightReady ? '✅ 环境自检通过' : '⛔ 环境阻止 · 查看';
    details.replaceChildren(...report.checks.map(check => {
      const item = document.createElement('div');
      item.className = `preflight-item ${check.status}`;
      const heading = document.createElement('strong');
      heading.textContent = `${check.status === 'pass' ? '✅ 通过' : check.status === 'warning' ? '⚠️ 提醒' : '⛔ 阻止'} · ${check.label_zh}`;
      const summary = document.createElement('span');
      summary.textContent = check.summary_zh;
      item.append(heading, summary);
      if (check.status !== 'pass') {
        const action = document.createElement('small');
        action.textContent = check.remediation_zh;
        item.append(action);
      }
      return item;
    }));
  } catch (error) {
    preflightReady = false;
    status.classList.add('blocked');
    status.lastChild.textContent = '⛔ 环境失联 · 查看';
    details.textContent = explainError(error.message);
  }
}

document.querySelector('#preflight-status').addEventListener('click', () => {
  const status = document.querySelector('#preflight-status');
  const details = document.querySelector('#preflight-details');
  const opening = details.classList.contains('hidden');
  details.classList.toggle('hidden', !opening);
  status.setAttribute('aria-expanded', String(opening));
});

loadPreflight();

function renderPresetDescription() {
  const selected = document.querySelector('#analysis-mode').value;
  const preset = presetCatalog.find(item => item.code === selected);
  const description = document.querySelector('#preset-description');
  if (!preset) {
    description.textContent = '无法读取预设说明，请刷新页面。';
    return;
  }
  const yPlus = preset.target_y_plus == null ? '按证据判断' : `目标 Y+≈${preset.target_y_plus}`;
  description.textContent = `${preset.purpose_zh} · ${preset.runtime_zh} · ${yPlus} · 证据上限：${preset.evidence_ceiling}`;
  refreshReadySubmitLabel();
}

function readySubmitText() {
  return document.querySelector('#analysis-mode').value === 'grid_study'
    ? '📊 三档分析'
    : '⚙️ 开始分析';
}

function refreshReadySubmitLabel() {
  if (currentModel && !submitButton.disabled) submitButton.textContent = readySubmitText();
}

async function loadPresets() {
  try {
    presetCatalog = await requestJson('/api/presets');
    renderPresetDescription();
  } catch (error) {
    document.querySelector('#preset-description').textContent = explainError(error.message);
  }
}

document.querySelector('#analysis-mode').addEventListener('change', renderPresetDescription);
loadPresets();

function loadViewer(url, failureMessage, timeoutMs = 45000) {
  const sequence = ++viewerLoadSequence;
  viewer.classList.add('hidden');
  viewerBusy.classList.remove('hidden');
  const timer = setTimeout(() => {
    if (sequence !== viewerLoadSequence) return;
    viewer.classList.add('hidden'); viewerBusy.classList.add('hidden');
    errorBox.textContent = `${failureMessage}（加载超时，可点击相应视图重试）`;
  }, timeoutMs);
  viewer.onload = () => {
    if (sequence !== viewerLoadSequence) return;
    clearTimeout(timer); viewerBusy.classList.add('hidden'); viewer.classList.remove('hidden');
  };
  viewer.onerror = () => {
    if (sequence !== viewerLoadSequence) return;
    clearTimeout(timer); viewerBusy.classList.add('hidden'); viewer.classList.add('hidden');
    errorBox.textContent = failureMessage;
  };
  viewer.src = url;
}

window.addEventListener('message', async event => {
  if (event.origin !== window.location.origin || !event.data) return;
  if (event.data.type === 'phoenix-picker-ready' && currentModel) {
    document.querySelector('#wing-selection').classList.add('picker-ready');
    viewer.contentWindow.postMessage({
      type: 'phoenix-set-surface-selection',
      tags: currentModel.selected_surface_tags || [],
    }, window.location.origin);
  } else if (event.data.type === 'phoenix-surface-selection' && currentModel) {
    await saveWingSelection(event.data.tags || []);
  } else if (event.data.type === 'phoenix-orientation-point' && currentModel) {
    const axis = axisFromPickedPoint(event.data.position, currentModel.inspection.geometry_center_m);
    if (!axis) {
      errorBox.textContent = '点击位置距离模型几何中心太近，无法可靠判断方向；请点击更靠近机头或机背的位置。';
      return;
    }
    const target = event.data.mode === 'nose' ? document.querySelector('#nose-axis') : document.querySelector('#up-axis');
    orientationUndo.push({ target: target.id, previous: target.value });
    target.value = axis;
    document.querySelector('#undo-orientation').disabled = false;
    document.querySelector('#orientation-pick-status').textContent = `${event.data.mode === 'nose' ? '机头' : '上方'}已按真实表面点击设为 ${axis}（曲面 ${event.data.surfaceTag}）；可继续修改或撤销。`;
  } else if (event.data.type === 'phoenix-surface-pick-error') {
    errorBox.textContent = '三维曲面点选失败，请恢复视角后重试；原模型和参数没有被修改。';
  } else if (event.data.type === 'phoenix-scene-ready') {
    const range = event.data.scalarRange || [];
    const key = activeScalarKey();
    if (key && !scalarManualRanges[key] && range.length === 2) {
      document.querySelector('#scalar-min').value = Number(range[0]).toPrecision(6);
      document.querySelector('#scalar-max').value = Number(range[1]).toPrecision(6);
    }
  } else if (event.data.type === 'phoenix-scalar-picked') {
    const unit = event.data.scalarName === 'Pressure' ? ' Pa' : '';
    document.querySelector('#scalar-probe').textContent = `${event.data.scalarTitle}: ${Number(event.data.value).toPrecision(7)}${unit}`;
  } else if (event.data.type === 'phoenix-screenshot-ready' && event.data.image) {
    const link = document.createElement('a'); link.href = event.data.image; link.download = `phoenix-scene-${Date.now()}.png`; link.click();
  }
});

function axisFromPickedPoint(position, center) {
  if (!Array.isArray(position) || !Array.isArray(center) || position.length !== 3 || center.length !== 3) return null;
  const delta = position.map((value, index) => Number(value) - Number(center[index]));
  if (delta.some(value => !Number.isFinite(value))) return null;
  const magnitudes = delta.map(Math.abs);
  const component = magnitudes.indexOf(Math.max(...magnitudes));
  if (magnitudes[component] <= 1e-9) return null;
  return `${delta[component] >= 0 ? '+' : '-'}${['X', 'Y', 'Z'][component]}`;
}

function beginOrientationPick(mode) {
  if (!currentModel || !viewer.contentWindow) return;
  viewer.contentWindow.postMessage({ type: 'phoenix-pick-mode', mode }, window.location.origin);
  document.querySelector('#orientation-pick-status').textContent = mode === 'nose'
    ? '请在三维模型上点击最靠近机头的表面位置。'
    : '请在三维模型上点击机体朝上的表面位置。';
}

document.querySelector('#pick-nose').addEventListener('click', () => beginOrientationPick('nose'));
document.querySelector('#pick-up').addEventListener('click', () => beginOrientationPick('up'));
document.querySelector('#undo-orientation').addEventListener('click', () => {
  const change = orientationUndo.pop();
  if (!change) return;
  document.querySelector(`#${change.target}`).value = change.previous;
  document.querySelector('#undo-orientation').disabled = orientationUndo.length === 0;
  document.querySelector('#orientation-pick-status').textContent = '已撤销上一次方向修改。';
});

fileInput.addEventListener('change', async () => {
  const requestSequence = ++modelRequestSequence;
  const file = fileInput.files[0];
  fileLabel.textContent = file?.name || '选择 STEP / STP';
  currentModel = null;
  submitButton.disabled = true;
  submitButton.textContent = '⏳ 检查模型';
  errorBox.textContent = '';
  if (!file) {
    submitButton.textContent = '⏳ 请先上传';
    viewerBusy.classList.add('hidden'); viewerPlaceholder.classList.remove('hidden');
    return;
  }
  viewerPlaceholder.classList.add('hidden');
  viewer.classList.add('hidden');
  viewerBusy.classList.remove('hidden');
  try {
    const upload = new FormData();
    upload.append('model', file);
    const payload = await requestJson('/api/models', { method: 'POST', body: upload }, 10 * 60 * 1000);
    if (requestSequence !== modelRequestSequence) return;
    currentModel = payload;
    showModel(payload);
    submitButton.textContent = '🧭 请确认方向';
  } catch (error) {
    if (requestSequence !== modelRequestSequence) return;
    viewerPlaceholder.classList.remove('hidden');
    errorBox.textContent = explainError(error.message);
    submitButton.textContent = '⛔ 模型未通过';
  } finally {
    if (requestSequence === modelRequestSequence && !currentModel) viewerBusy.classList.add('hidden');
  }
});

function showModel(model) {
  viewerPlaceholder.classList.add('hidden');
  const dims = model.inspection.dimensions_m.map(value => Number(value).toFixed(3));
  document.querySelector('#scene-title').textContent = model.original_filename;
  document.querySelector('#model-dimensions').textContent = `${dims.join(' × ')} m`;
  document.querySelector('#model-topology').textContent = `${model.inspection.volume_count} 实体 · ${model.inspection.surface_count} 曲面`;
  document.querySelector('#model-evidence').textContent = `SHA-256 ${model.source_sha256.slice(0, 12)}… · ${model.preview_point_count} 点 / ${model.preview_cell_count} 单元`;
  if (model.mesh_audit?.repair_applied && !model.mesh_audit?.engineering_analysis_blocked) {
    document.querySelector('#model-evidence').textContent += ` · 已用 Gmsh 官方曲面网格细化消除 ${model.mesh_audit.initial_invalid_warnings.length} 条无效单元警告（原 STEP 未修改）`;
  }
  document.querySelector('#model-summary').classList.remove('hidden');
  document.querySelector('#model-confidence').classList.remove('hidden');
  document.querySelector('#orientation-confirm').classList.remove('hidden');
  if ((model.warnings || []).length) {
    document.querySelector('#model-confidence').classList.add('has-warning');
    document.querySelector('#model-evidence').textContent += ` · Gmsh 报告 ${model.warnings.length} 条表面网格警告，预览可查看但需在正式网格阶段复核。`;
  }
  if (model.mesh_audit?.engineering_analysis_blocked) {
    document.querySelector('#model-confidence').classList.add('has-warning');
    errorBox.textContent = '当前曲面网格仍含无效单元，工程分析已阻止。请先在 CAD 中修复专业诊断指出的曲面。';
  }
  document.querySelector('#nose-axis').value = model.parameters.nose_axis.current_value;
  document.querySelector('#up-axis').value = model.parameters.up_axis.current_value;
  document.querySelector('#span-axis').value = model.parameters.span_axis.current_value;
  document.querySelector('#s-ref').value = model.parameters.s_ref_m2.current_value;
  document.querySelector('#c-ref').value = model.parameters.c_ref_m.current_value;
  document.querySelector('#span-ref').value = model.parameters.span_m.current_value;
  updateWingSelectionPanel(model);
  loadViewer(model.artifacts['preview.html'], '三维模型加载失败。请重新上传 STEP；原文件没有被修改。');
  setActiveStep('confirm');
}

document.querySelector('#confirm-model').addEventListener('click', async () => {
  if (!currentModel) return;
  const button = document.querySelector('#confirm-model');
  const updates = {
    nose_axis: document.querySelector('#nose-axis').value,
    up_axis: document.querySelector('#up-axis').value,
    span_axis: document.querySelector('#span-axis').value,
    s_ref_m2: Number(document.querySelector('#s-ref').value),
    c_ref_m: Number(document.querySelector('#c-ref').value),
    span_m: Number(document.querySelector('#span-ref').value),
  };
  if (currentModel.mesh_audit?.engineering_analysis_blocked) {
    errorBox.textContent = '当前曲面网格仍含无效单元，不能进入工程分析；预览仅用于定位问题。';
    return;
  }
  if ((currentModel.selectable_surface_tags || []).length && !(currentModel.selected_surface_tags || []).length) {
    errorBox.textContent = '请先在三维模型中点选左右主翼表面；橙色曲面表示已选择。';
    return;
  }
  button.disabled = true;
  errorBox.textContent = '';
  try {
    currentModel = await requestJson(`/api/models/${encodeURIComponent(currentModel.model_id)}/parameters`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values: updates }),
    });
    button.textContent = '✅ 已确认 · 可修改';
    submitButton.disabled = false;
    submitButton.textContent = readySubmitText();
    setActiveStep('condition');
  } catch (error) {
    errorBox.textContent = explainError(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll('[data-restore-parameter]').forEach(button => {
  button.addEventListener('click', async () => {
    if (!currentModel) return;
    const parameter = button.dataset.restoreParameter;
    button.disabled = true;
    errorBox.textContent = '';
    try {
      currentModel = await requestJson(
        `/api/models/${encodeURIComponent(currentModel.model_id)}/parameters/${encodeURIComponent(parameter)}/restore`,
        { method: 'POST' },
      );
      showModel(currentModel);
    } catch (error) {
      errorBox.textContent = explainError(error.message);
    } finally {
      button.disabled = false;
    }
  });
});

document.querySelector('#reset-wing-selection').addEventListener('click', async () => {
  if (!currentModel) return;
  viewer.contentWindow.postMessage(
    { type: 'phoenix-set-surface-selection', tags: [] }, window.location.origin
  );
  await saveWingSelection([]);
});

async function saveWingSelection(tags) {
  if (!currentModel) return;
  pendingWingSelection = [...new Set(tags.map(Number))].sort((a, b) => a - b);
  if (wingSelectionBusy) return;
  wingSelectionBusy = true;
  errorBox.textContent = '';
  try {
    while (pendingWingSelection !== null) {
      const selection = pendingWingSelection;
      pendingWingSelection = null;
      const payload = await requestJson(`/api/models/${encodeURIComponent(currentModel.model_id)}/wing-surfaces`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ surface_tags: selection }),
      });
      currentModel = payload;
      document.querySelector('#s-ref').value = payload.parameters.s_ref_m2.current_value;
      document.querySelector('#c-ref').value = payload.parameters.c_ref_m.current_value;
      document.querySelector('#span-ref').value = payload.parameters.span_m.current_value;
      updateWingSelectionPanel(payload);
    }
  } catch (error) {
    errorBox.textContent = explainError(error.message);
    viewer.contentWindow?.postMessage({
      type: 'phoenix-set-surface-selection', tags: currentModel.selected_surface_tags || [],
    }, window.location.origin);
  } finally {
    wingSelectionBusy = false;
  }
}

function updateWingSelectionPanel(model) {
  const tags = model.selected_surface_tags || [];
  document.querySelector('#wing-selection-count').textContent = `已选择 ${tags.length} 个曲面`;
  const evidence = document.querySelector('#wing-reference-evidence');
  if (!model.wing_reference) {
    evidence.textContent = (model.selectable_surface_tags || []).length
      ? `可点选 ${model.selectable_surface_tags.length} 个真实 OCC 曲面；请选择左右主翼。`
      : '当前旧预览没有曲面标签，请重新上传 STEP 生成可点选预览。';
    return;
  }
  const reference = model.wing_reference;
  evidence.textContent = `S_ref ${Number(reference.s_ref_m2).toFixed(4)} m² · c_ref ${Number(reference.c_ref_m).toFixed(4)} m · 翼展 ${Number(reference.span_m).toFixed(4)} m · ${reference.confidence === 'medium' ? '中等可信度' : '低可信度'}。${reference.rationale_zh}`;
}

document.querySelectorAll('.scene-tab').forEach(button => button.addEventListener('click', () => switchScene(button.dataset.view)));
document.querySelector('#pressure-field').addEventListener('change', () => switchScene('pressure'));
document.querySelector('#velocity-preset').addEventListener('change', () => switchScene('velocity'));
document.querySelector('#streamline-density').addEventListener('change', () => switchScene('streamlines'));
document.querySelectorAll('[data-camera]').forEach(button => button.addEventListener('click', () => {
  viewer.contentWindow?.postMessage({ type: 'phoenix-camera', command: button.dataset.camera }, window.location.origin);
}));
document.querySelector('#toggle-fullscreen').addEventListener('click', () => document.querySelector('.viewer-shell').requestFullscreen());
document.querySelector('#capture-scene').addEventListener('click', () => viewer.contentWindow?.postMessage({ type: 'phoenix-screenshot' }, window.location.origin));
document.querySelector('#toggle-axes').addEventListener('click', event => {
  axesVisible = !axesVisible; event.currentTarget.setAttribute('aria-pressed', String(axesVisible)); event.currentTarget.textContent = `坐标轴：${axesVisible ? '开' : '关'}`;
  viewer.contentWindow?.postMessage({ type: 'phoenix-visibility', target: 'axes', visible: axesVisible }, window.location.origin);
});
document.querySelector('#toggle-colorbar').addEventListener('click', event => {
  colorbarVisible = !colorbarVisible; event.currentTarget.setAttribute('aria-pressed', String(colorbarVisible)); event.currentTarget.textContent = `色标：${colorbarVisible ? '开' : '关'}`;
  viewer.contentWindow?.postMessage({ type: 'phoenix-visibility', target: 'scalar-bar', visible: colorbarVisible }, window.location.origin);
});
document.querySelector('#apply-scalar-range').addEventListener('click', () => {
  const key = activeScalarKey();
  if (!key) return;
  scalarManualRanges[key] = {
    minimum: document.querySelector('#scalar-min').value,
    maximum: document.querySelector('#scalar-max').value,
  };
  switchScene(activeSceneName);
});
document.querySelector('#reset-scalar-range').addEventListener('click', () => {
  const key = activeScalarKey();
  if (!key) return;
  scalarManualRanges[key] = null;
  document.querySelector('#scalar-min').value = '';
  document.querySelector('#scalar-max').value = '';
  switchScene(activeSceneName);
});
document.querySelector('#slice-position').addEventListener('input', event => document.querySelector('#slice-position-label').textContent = `${event.target.value > 0 ? '正向' : event.target.value < 0 ? '负向' : '中心'} ${event.target.value}%`);
document.querySelector('#slice-opacity').addEventListener('input', event => document.querySelector('#slice-opacity-label').textContent = `${event.target.value}%`);
document.querySelector('#apply-slice').addEventListener('click', () => switchScene('velocity'));
document.querySelector('#reset-slice').addEventListener('click', () => { document.querySelector('#slice-position').value = 0; document.querySelector('#slice-position-label').textContent = '中心 0%'; switchScene('velocity'); });
document.querySelector('#stream-width').addEventListener('input', event => document.querySelector('#stream-width-label').textContent = event.target.value);
document.querySelector('#stream-opacity').addEventListener('input', event => document.querySelector('#stream-opacity-label').textContent = `${event.target.value}%`);
document.querySelector('#apply-streamlines').addEventListener('click', () => switchScene('streamlines'));

async function switchScene(name) {
  activeSceneName = name;
  const requestSequence = ++sceneRequestSequence;
  const warning = document.querySelector('#scene-warning');
  document.querySelectorAll('.scene-tab').forEach(button => button.classList.toggle('active', button.dataset.view === name));
  document.querySelector('#pressure-field').classList.toggle('hidden', name !== 'pressure');
  document.querySelector('#velocity-preset').classList.toggle('hidden', name !== 'velocity');
  document.querySelector('#streamline-density').classList.toggle('hidden', name !== 'streamlines');
  document.querySelector('#pressure-controls').classList.toggle('hidden', !['pressure', 'yplus'].includes(name));
  document.querySelector('#velocity-controls').classList.toggle('hidden', name !== 'velocity');
  document.querySelector('#streamline-controls').classList.toggle('hidden', name !== 'streamlines');
  if (name === 'model') {
    warning.classList.add('hidden');
    if (currentModel) { loadViewer(currentModel.artifacts['preview.html'], '三维模型加载失败，请点击“模型”重试。'); document.querySelector('#scene-title').textContent = currentModel.original_filename; }
    return;
  }
  if (!['pressure', 'yplus', 'velocity', 'streamlines'].includes(name) || !currentJobId) return;
  viewerPlaceholder.classList.add('hidden');
  let endpoint; let artifact; let title;
  if (name === 'pressure') {
    const field = document.querySelector('#pressure-field').value;
    endpoint = `/api/jobs/${encodeURIComponent(currentJobId)}/scenes/pressure?field=${encodeURIComponent(field)}`;
    endpoint += scalarRangeQuery(field, '&');
    artifact = `pressure_${field}.html`;
    title = field === 'cp' ? '机体表面压力系数 Cp' : '机体表面静压力 (Pa)';
    document.querySelector('#scalar-probe').textContent = '蓝色为低压，红色为高压；点击表面读取数值';
  } else if (name === 'yplus') {
    endpoint = `/api/jobs/${encodeURIComponent(currentJobId)}/scenes/y-plus`;
    endpoint += scalarRangeQuery('yplus', '?');
    artifact = 'y_plus.html';
    title = '壁面 Y+（无量纲）';
    document.querySelector('#scalar-probe').textContent = 'Y+ 无量纲；点击表面读取求解后的真实值';
  } else if (name === 'velocity') {
    const preset = document.querySelector('#velocity-preset').value;
    endpoint = `/api/jobs/${encodeURIComponent(currentJobId)}/scenes/velocity?preset=${encodeURIComponent(preset)}`;
    endpoint += `&position=${Number(document.querySelector('#slice-position').value) / 100}&opacity=${Number(document.querySelector('#slice-opacity').value) / 100}&visible=${document.querySelector('#slice-visible').checked}`;
    artifact = `velocity_${preset}.html`;
    title = ({ longitudinal: '纵向中心速度截面', wing: '主翼附近速度截面', wake: '尾流速度截面' })[preset];
  } else {
    const density = document.querySelector('#streamline-density').value;
    endpoint = `/api/jobs/${encodeURIComponent(currentJobId)}/scenes/streamlines?density=${encodeURIComponent(density)}`;
    endpoint += `&line_width=${document.querySelector('#stream-width').value}&opacity=${Number(document.querySelector('#stream-opacity').value) / 100}&visible=${document.querySelector('#stream-visible').checked}`;
    artifact = `streamlines_${density}.html`;
    title = '上游种子平面三维流线';
  }
  viewer.classList.add('hidden'); viewerBusy.classList.remove('hidden');
  try {
    const payload = await requestJson(endpoint, { method: 'POST' }, 2 * 60 * 1000);
    if (requestSequence !== sceneRequestSequence) return;
    currentJob = payload;
    loadViewer(`${payload.artifacts[artifact]}?v=${Date.now()}`, '三维结果加载失败。实际任务产物仍保留，请点击相应视图重试。');
    document.querySelector('#scene-title').textContent = title;
    if (payload.credibility && payload.credibility !== 'reliable') {
      warning.textContent = payload.credibility === 'invalid' ? '本次计算无效：云图仅用于排错，不能用于设计结论。' : '结果仅供趋势参考：收敛或网格证据尚不足。';
      warning.classList.remove('hidden');
    } else warning.classList.add('hidden');
  } catch (error) {
    if (requestSequence !== sceneRequestSequence) return;
    errorBox.textContent = explainError(error.message);
  }
}

function activeScalarKey() {
  if (activeSceneName === 'yplus') return 'yplus';
  if (activeSceneName === 'pressure') return document.querySelector('#pressure-field').value;
  return null;
}

function scalarRangeQuery(key, prefix) {
  const range = scalarManualRanges[key];
  if (!range) {
    document.querySelector('#scalar-min').value = '';
    document.querySelector('#scalar-max').value = '';
    return '';
  }
  document.querySelector('#scalar-min').value = range.minimum;
  document.querySelector('#scalar-max').value = range.maximum;
  return `${prefix}range_min=${encodeURIComponent(range.minimum)}&range_max=${encodeURIComponent(range.maximum)}`;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.textContent = '';
  if (!currentModel) {
    errorBox.textContent = '请先上传 STEP，并等待真实三维模型检查完成。';
    return;
  }
  submitButton.disabled = true;
  submitButton.textContent = '⏳ 提交中';
  try {
    const isGridStudy = document.querySelector('#analysis-mode').value === 'grid_study';
    const endpoint = isGridStudy ? '/api/grid-studies' : '/api/jobs';
    const payload = await requestJson(endpoint, { method: 'POST', body: new FormData(form) }, 2 * 60 * 1000);
    currentGridStudyId = isGridStudy ? payload.study_id : null;
    currentJobId = isGridStudy ? null : payload.job_id;
    setCurrentResultUrl(isGridStudy ? 'study' : 'job', isGridStudy ? payload.study_id : payload.job_id);
    if (isGridStudy) showGridStudy(payload); else showJob(payload);
    setActiveStep('run');
    schedulePoll();
    await refreshHistory();
  } catch (error) {
    errorBox.textContent = explainError(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = readySubmitText();
  }
});

cancelButton.addEventListener('click', async () => {
  if (!currentJobId && !currentGridStudyId) return;
  cancelButton.disabled = true;
  try {
    const endpoint = currentGridStudyId
      ? `/api/grid-studies/${encodeURIComponent(currentGridStudyId)}/cancel`
      : `/api/jobs/${encodeURIComponent(currentJobId)}/cancel`;
    await requestJson(endpoint, { method: 'POST' });
    schedulePoll(100);
  } catch (error) {
    errorBox.textContent = explainError(error.message); cancelButton.disabled = false;
  }
});

document.querySelector('#conservative-retry').addEventListener('click', async () => {
  if (!currentJobId) return;
  const button = document.querySelector('#conservative-retry');
  button.disabled = true;
  errorBox.textContent = '';
  try {
    const payload = await requestJson(`/api/jobs/${encodeURIComponent(currentJobId)}/retry-conservative`, { method: 'POST' });
    currentGridStudyId = null;
    currentJobId = payload.job_id;
    showJob(payload);
    setActiveStep('run');
    schedulePoll(200);
  } catch (error) {
    errorBox.textContent = explainError(error.message);
    button.disabled = false;
  }
});

function schedulePoll(delay = 800) { clearTimeout(pollTimer); pollTimer = setTimeout(pollCurrent, delay); }
function nextPollDelay() { return Math.min(5000, 800 * (2 ** Math.min(pollFailures, 3))); }

async function pollCurrent() {
  if (!currentJobId && !currentGridStudyId) return;
  try {
    if (currentGridStudyId) {
      const study = await requestJson(`/api/grid-studies/${encodeURIComponent(currentGridStudyId)}`, {}, 10000);
      pollFailures = 0;
      showGridStudy(study);
      if (!['completed', 'blocked', 'failed', 'cancelled'].includes(study.state)) schedulePoll();
      else setActiveStep('result');
      return;
    }
    const job = await requestJson(`/api/jobs/${encodeURIComponent(currentJobId)}`, {}, 10000);
    pollFailures = 0;
    if (errorBox.textContent.startsWith('后台连接暂时中断')) errorBox.textContent = '';
    showJob(job);
    await refreshHistory();
    if (!['completed', 'failed', 'cancelled'].includes(job.state)) schedulePoll();
    else if (job.state === 'completed') setActiveStep('result');
  } catch (error) {
    pollFailures += 1;
    document.querySelector('#stage-text').textContent = `后台暂时无响应，正在自动重连（第 ${pollFailures} 次）`;
    errorBox.textContent = '后台连接暂时中断，任务不会被覆盖；页面正在自动恢复连接。';
    schedulePoll(nextPollDelay());
  }
}

function showGridStudy(study) {
  const studyStateText = stateText(study.state);
  currentJob = null;
  document.querySelector('#empty-state').classList.add('hidden');
  document.querySelector('#job-view').classList.remove('hidden');
  document.querySelector('#grid-study-view').classList.remove('hidden');
  document.querySelector('#user-diagnostic').classList.add('hidden');
  document.querySelector('#job-id').textContent = `网格研究 ${study.study_id.slice(0, 10)}`;
  setStateChip(study.state);
  const levels = Object.values(study.levels || {});
  const terminal = levels.filter(item => ['completed', 'failed', 'cancelled'].includes(item.state)).length;
  const progress = Math.round((terminal / 3) * 100);
  document.querySelector('#progress-bar').style.width = `${progress}%`;
  document.querySelector('#stage-text').textContent = study.state === 'running' ? '当前：三个任务按顺序计算' : `当前：${studyStateText}`;
  cancelButton.disabled = ['completed', 'blocked', 'failed', 'cancelled'].includes(study.state);
  const card = document.querySelector('#credibility-card');
  card.className = `credibility ${study.state === 'completed' ? 'reliable' : study.state === 'blocked' ? 'caution' : 'neutral'}`;
  document.querySelector('#credibility-text').textContent = study.state === 'completed' ? '✅ GCI 已计算' : study.state === 'blocked' ? '⛔ GCI 已阻止' : '⏳ 等待三档';
  document.querySelector('#credibility-reasons').textContent = (study.blocking_reasons || []).map(gridStudyReasonText).join(' · ') || '只有三档均真实收敛且设置一致时才计算 GCI。';
  const summary = document.querySelector('#grid-study-summary');
  summary.textContent = study.analysis_status === 'computed'
    ? '粗、中、细三档任务均已收敛；下方 GCI 使用真实单元数和求解结果。'
    : study.state === 'blocked'
      ? '至少一档未通过执行、收敛或数据完整性门槛，因此没有生成伪 GCI。'
      : `已完成 ${terminal}/3 档；单工作线程按顺序运行，避免普通电脑资源争抢。`;
  const body = document.querySelector('#grid-study-levels');
  body.replaceChildren();
  for (const level of levels) {
    const row = body.insertRow();
    [({ coarse: '粗', medium: '中', fine: '细' })[level.level] || level.level, stateText(level.state), level.cell_count ?? '—', formatNumber(level.cl), formatNumber(level.cd), Number.isFinite(level.elapsed_seconds) ? `${Number(level.elapsed_seconds).toFixed(1)} s` : '—']
      .forEach(value => { const cell = row.insertCell(); cell.textContent = value; });
  }
  const gci = document.querySelector('#grid-study-gci');
  gci.replaceChildren();
  for (const [name, quantity] of Object.entries(study.quantities || {})) {
    const item = document.createElement('div');
    const label = document.createElement('span');
    label.textContent = `${name} 细网格 GCI`;
    const value = document.createElement('strong');
    value.textContent = quantity.gci_computable && Number.isFinite(quantity.gci_fine_fraction)
      ? `${(Number(quantity.gci_fine_fraction) * 100).toFixed(3)}%`
      : '不可计算';
    item.append(label, value); gci.append(item);
  }
  const fine = study.levels?.fine || {};
  document.querySelector('#metric-cl').textContent = formatNumber(fine.cl);
  document.querySelector('#metric-cd').textContent = formatNumber(fine.cd);
  document.querySelector('#metric-ld').textContent = fine.cl != null && fine.cd ? formatNumber(fine.cl / fine.cd) : '—';
  document.querySelector('#metric-lift').textContent = '—';
  document.querySelector('#metric-drag').textContent = '—';
  document.querySelector('#metric-ratio').textContent = '—';
  document.querySelector('#takeoff-boundary').textContent = '网格研究只评估离散化敏感性，不单独证明工程正确性或起飞能力。';
  document.querySelector('#result-conclusion').textContent = study.state === 'completed'
    ? '三档网格研究完成；请结合各量 GCI、收敛与其他可信度证据使用。'
    : '三档网格研究尚未形成可用 GCI。';
  document.querySelector('#run-log').textContent = JSON.stringify(study, null, 2);
  document.querySelector('#artifact-links').replaceChildren();
  document.querySelector('[data-view="pressure"]').disabled = true;
  document.querySelector('[data-view="yplus"]').disabled = true;
  document.querySelector('[data-view="velocity"]').disabled = true;
  document.querySelector('[data-view="streamlines"]').disabled = true;
}

function showJob(job) {
  document.querySelector('#grid-study-view').classList.add('hidden');
  currentJob = job;
  document.querySelector('#empty-state').classList.add('hidden');
  document.querySelector('#job-view').classList.remove('hidden');
  document.querySelector('#job-id').textContent = `任务 ${job.job_id.slice(0, 10)}`;
  setStateChip(job.state);
  document.querySelector('#progress-bar').style.width = `${job.progress}%`;
  document.querySelector('#stage-text').textContent = `当前：${stageText(job.stage)}`;
  cancelButton.disabled = ['completed', 'failed', 'cancelled'].includes(job.state);
  const card = document.querySelector('#credibility-card');
  card.className = `credibility ${job.credibility || 'neutral'}`;
  document.querySelector('#credibility-text').textContent = job.scientific_use_level
    ? scientificUseText(job.scientific_use_level)
    : credibilityText(job.credibility);
  document.querySelector('#credibility-reasons').textContent = humanReasons(job);
  document.querySelector('#metric-cl').textContent = formatNumber(job.cl);
  document.querySelector('#metric-cd').textContent = formatNumber(job.cd);
  document.querySelector('#metric-ld').textContent = job.cl != null && job.cd ? formatNumber(job.cl / job.cd) : '—';
  const aero = job.aerodynamic_summary || {};
  document.querySelector('#metric-lift').textContent = formatForce(aero.lift_n);
  document.querySelector('#metric-drag').textContent = formatForce(aero.drag_n);
  document.querySelector('#metric-ratio').textContent = Number.isFinite(aero.lift_weight_ratio) ? Number(aero.lift_weight_ratio).toFixed(2) : '—';
  document.querySelector('#takeoff-boundary').textContent = aero.takeoff_boundary_zh || '';
  document.querySelector('#result-conclusion').textContent = job.coefficients_usable && Number.isFinite(aero.lift_n)
    ? `当前工程比较工况计算升力为 ${formatForce(aero.lift_n)} N，飞机重量为 ${formatForce(aero.weight_n)} N，升力约为重量的 ${Number(aero.lift_weight_ratio).toFixed(2)} 倍。`
    : (Number.isFinite(aero.lift_n)
      ? `诊断计算值：升力 ${formatForce(aero.lift_n)} N。当前科学证据等级不允许用于起飞或工程结论。`
      : '本次任务尚无可解释的升力结果。');
  showUserDiagnostic(job);
  document.querySelector('#run-log').textContent = [
    `执行状态: ${job.execution_status || job.state}`,
    `阶段: ${job.stage}`,
    `数值收敛: ${convergenceText(job.scientific_evidence?.convergence_status || job.convergence_status)}`,
    `科学用途: ${scientificUseText(job.scientific_use_level)}`,
    `当前算例验证等级: ${job.validation_level || '未分配'}`,
    job.error_code ? `错误码: ${job.error_code}` : '',
    job.coefficients_usable ? '系数通过当前可信度门槛' : '系数不能作为最终设计结论',
  ].filter(Boolean).join('\n');
  const links = document.querySelector('#artifact-links');
  links.replaceChildren();
  for (const [name, href] of Object.entries(job.artifacts || {})) {
    const anchor = document.createElement('a');
    anchor.href = href; anchor.textContent = artifactText(name); links.append(anchor);
  }
  document.querySelector('[data-view="pressure"]').disabled = !job.artifacts?.['surface_flow.vtu'];
  document.querySelector('[data-view="yplus"]').disabled = !(
    job.artifacts?.['surface_flow.vtu']
    && ['computed', 'measured', 'verified'].includes(job.quantity_evidence?.y_plus?.evidence_status)
  );
  document.querySelector('[data-view="velocity"]').disabled = !job.artifacts?.['flow.vtu'];
  document.querySelector('[data-view="streamlines"]').disabled = !(job.artifacts?.['flow.vtu'] && job.artifacts?.['surface_flow.vtu']);
}

function showUserDiagnostic(job) {
  const panel = document.querySelector('#user-diagnostic');
  const diagnostic = (job.user_diagnostics || [])[0];
  const retry = document.querySelector('#conservative-retry');
  if (!diagnostic) {
    panel.classList.add('hidden');
    retry.classList.add('hidden');
    return;
  }
  panel.classList.remove('hidden');
  document.querySelector('#diagnostic-title').textContent = `⚠️ ${diagnostic.title_zh}`;
  document.querySelector('#diagnostic-happened').textContent = diagnostic.happened_zh;
  document.querySelector('#diagnostic-causes').textContent = diagnostic.causes_zh.join('；');
  document.querySelector('#diagnostic-impact').textContent = diagnostic.impact_zh;
  document.querySelector('#diagnostic-actions').textContent = diagnostic.action_zh.join('；');
  document.querySelector('#diagnostic-fields').textContent = diagnostic.can_view_fields
    ? '可以查看真实已生成的云图，但必须同时保留本条风险提示。'
    : '不允许把缺失或无效场数据显示成云图。';
  retry.classList.toggle('hidden', !job.conservative_retry_available);
  retry.disabled = false;
}

async function refreshHistory() {
  let jobs; let studies;
  try {
    [jobs, studies] = await Promise.all([
      requestJson('/api/jobs', {}, 10000),
      requestJson('/api/grid-studies', {}, 10000),
    ]);
  } catch (_) { return; }
  const body = document.querySelector('#history-body');
  body.replaceChildren();
  if (!jobs.length && !studies.length) { const row = body.insertRow(); const cell = row.insertCell(); cell.colSpan = 5; cell.textContent = '暂无任务'; return; }
  for (const study of studies) {
    const row = body.insertRow();
    row.addEventListener('click', () => {
      currentJobId = null; currentGridStudyId = study.study_id;
      setCurrentResultUrl('study', study.study_id);
      showGridStudy(study); schedulePoll(100);
    });
    const fine = study.levels?.fine || {};
    [`📊 ${study.study_id.slice(0, 6)}`, study.original_filename, stateText(study.state), study.analysis_status === 'computed' ? '✅ GCI' : '⏳ 评估', `${formatNumber(fine.cl)} / ${formatNumber(fine.cd)}`]
      .forEach(value => { const cell = row.insertCell(); cell.textContent = value; });
  }
  for (const job of jobs.slice().reverse()) {
    const row = body.insertRow();
    row.addEventListener('click', () => { currentGridStudyId = null; currentJobId = job.job_id; setCurrentResultUrl('job', job.job_id); showJob(job); schedulePoll(100); });
    [job.job_id.slice(0, 10), job.original_filename, stateText(job.state), credibilityText(job.credibility), `${formatNumber(job.cl)} / ${formatNumber(job.cd)}`]
      .forEach(value => { const cell = row.insertCell(); cell.textContent = value; });
  }
}

function setCurrentResultUrl(kind, identifier) {
  const url = new URL(window.location.href);
  url.searchParams.delete(kind === 'job' ? 'study' : 'job');
  url.searchParams.set(kind, identifier);
  window.history.replaceState({}, '', url);
}

function gridStudyReasonText(code) {
  return ({
    GRID_LEVEL_EXECUTION_NOT_COMPLETED: '至少一档任务没有正常完成；请打开对应子任务查看执行错误。',
    GRID_LEVEL_NOT_CONVERGED: '至少一档没有达到收敛门槛；本次不能计算可信 GCI。',
    GRID_LEVEL_RESULT_INCOMPLETE: '至少一档缺少真实网格数量、气动力或耗时记录。',
    GRID_LEVEL_RESULT_INVALID: '至少一档包含非正网格数量或非有限气动力数值。',
    GRID_CELL_COUNTS_NOT_REFINED: '实际单元数量没有按粗、中、细严格增加；请调整网格尺寸后重新建立研究。',
    GRID_COMMON_SETUP_MISMATCH: '三档的模型或共同物理设置不一致，不能进行同一网格族比较。',
    GRID_STUDY_CREATION_FAILED: '三档任务未全部创建成功；已保留已创建任务并停止继续提交。',
    GRID_STUDY_INTERRUPTED_ON_RESTART: '程序在研究进行中重启；旧任务已保留，但本组不会自动冒充完成。',
    GRID_STUDY_CANCELLED: '用户已取消整个研究；已完成的子任务仍保留。',
  })[code] || `专业诊断：${code}`;
}

function setActiveStep(name) { document.querySelectorAll('.steps li').forEach(item => item.classList.toggle('active', item.dataset.step === name)); }
function stateText(value) { return ({ queued: '⏳ 排队', running: '⏳ 运行', completed: '✅ 完成', blocked: '⛔ 阻止', failed: '⛔ 失败', cancelled: '🛑 取消' })[value] || value; }
function setStateChip(value) {
  const chip = document.querySelector('#state-chip');
  const known = ['queued', 'running', 'completed', 'blocked', 'failed', 'cancelled'];
  chip.className = `chip state-${known.includes(value) ? value : 'unknown'}`;
  chip.textContent = stateText(value);
}
function stageText(value) { return ({ queued: '等待计算资源', pipeline: '准备分析', stage: '复制并校验模型', inspect: '检查 STEP 几何', mesh: '生成外流场网格', config: '生成 SU2 配置', solve: 'SU2 正在迭代求解', parse: '检查收敛与气动力', visualize: '生成真实流场图', report: '生成分析报告', completed: '计算阶段已执行', failed: '执行失败', cancelled: '任务已取消' })[value] || value; }
function credibilityText(value) { return ({ reliable: '✅ 结果可用', caution: '⚠️ 仅供趋势', invalid: '⛔ 结果无效' })[value] || '⏳ 等待评估'; }
function scientificUseText(value) { return ({
  invalid: '无科学使用权限',
  diagnostic_only: '仅用于诊断排错',
  trend_only: '仅用于趋势比较',
  engineering_comparison: '可用于工程比较',
  externally_validated: '当前算例已有外部验证',
})[value] || '等待科学证据评估'; }
function convergenceText(value) { return ({
  not_evaluated: '尚未判定',
  converged: '严格收敛',
  likely_converged: '可能收敛（降级状态）',
  stagnated: '残差停滞',
  oscillating: '持续振荡',
  diverged: '数值发散',
  incomplete: '运行不完整',
  invalid: '历史数据无效',
})[value] || '等待'; }
function formatNumber(value) { return Number.isFinite(value) ? Number(value).toFixed(5) : '—'; }
function formatForce(value) { return Number.isFinite(value) ? Number(value).toFixed(2) : '—'; }
function humanReasons(job) {
  if (job.error_code) return explainError(job.error_code);
  if (!(job.credibility_reason_codes || []).length) return '完成后将联合检查残差、气动力稳定性、网格和退出原因。';
  return job.credibility_reason_codes.map(code => explainError(code)).join(' · ');
}
function artifactText(name) { return ({ 'history.csv': '📈 收敛', 'flow.vtu': '💨 体流场', 'surface_flow.vtu': '🌈 表面场', 'y_plus.html': '🧱 Y+', 'report.html': '📄 报告', 'solver_stdout.txt': '🔬 求解输出', 'solver_stderr.txt': '⚠️ 求解错误' })[name] || name; }
function explainError(code) {
  const known = {
    MODEL_MUST_BE_STEP: '请选择 STEP 或 STP 文件。', MODEL_EMPTY: '模型文件为空。', MODEL_TOO_LARGE: '模型文件超过本地安全上限。',
    MODEL_STEP_IMPORT_FAILED: 'Gmsh OpenCASCADE 无法导入该 STEP；请检查导出格式或几何损坏。', MODEL_STEP_NO_VOLUMES: '模型没有可用的封闭三维实体。',
    MODEL_ORIENTATION_AXES_CONFLICT: '机头、上方和翼展必须使用三个不同的坐标轴。', MODEL_PARAMETER_VALUE_INVALID: '识别结果的修改值无效，请检查数值或方向。',
    WING_SURFACE_SELECTION_INVALID: '主翼曲面选择格式无效，请重置后重新点选。', WING_SURFACE_TAG_INVALID: '所选曲面不属于当前真实 STEP 预览，请重新上传模型。',
    WING_SURFACE_SELECTION_EMPTY: '尚未选择主翼曲面。', WING_REFERENCE_CALCULATION_INVALID: '所选曲面无法形成有效的主翼投影，请检查是否同时选中了左右主翼。',
    Y_PLUS_FIELD_MISSING: '当前真实表面结果没有求解后的 Y+ 字段，不能生成伪 Y+ 云图。',
    Y_PLUS_FIELD_INVALID: '求解后的 Y+ 字段不是有效的非负标量，已阻止误导性云图。',
    Y_PLUS_EVIDENCE_UNAVAILABLE: '当前任务没有可用于诊断的真实壁面 Y+ 证据，已阻止生成伪云图。',
    JOB_CANCELLED: '任务已取消。', JOB_INTERRUPTED_BY_RESTART: '程序重启中断了任务，请重新计算。', CONVERGENCE_STAGNATED: '计算没有继续趋于稳定，本次数据只能查看趋势。',
    REQUEST_TIMEOUT: '本次操作等待超时，没有覆盖原任务。请检查后台状态后重试。', BACKEND_UNAVAILABLE: '本地后台暂时无法连接，页面会在任务运行时自动重连。',
  };
  return known[code] || `操作未完成（${code}）。可在专业诊断中查看原始信息。`;
}

refreshHistory();
loadRequestedModel();
loadRequestedJob();
loadRequestedGridStudy();

async function loadRequestedGridStudy() {
  const studyId = new URLSearchParams(window.location.search).get('study');
  if (!studyId) return;
  try {
    currentJobId = null;
    currentGridStudyId = studyId;
    const study = await requestJson(`/api/grid-studies/${encodeURIComponent(studyId)}`, {}, 10000);
    showGridStudy(study);
    setActiveStep('result');
    if (!['completed', 'blocked', 'failed', 'cancelled'].includes(study.state)) schedulePoll(100);
  } catch (_) {
    /* A stale grid-study link leaves history and normal upload available. */
  }
}

async function loadRequestedModel() {
  const modelId = new URLSearchParams(window.location.search).get('model');
  if (!modelId) return;
  try {
    currentModel = await requestJson(`/api/models/${encodeURIComponent(modelId)}`, {}, 10000);
    fileLabel.textContent = currentModel.original_filename;
    showModel(currentModel);
    submitButton.disabled = true;
    submitButton.textContent = '重新选择文件后可提交分析';
  } catch (_) {
    /* A stale model link leaves the normal upload workflow available. */
  }
}

async function loadRequestedJob() {
  const parameters = new URLSearchParams(window.location.search);
  const jobId = parameters.get('job');
  if (!jobId) return;
  try {
    currentGridStudyId = null;
    currentJobId = jobId;
    const job = await requestJson(`/api/jobs/${encodeURIComponent(jobId)}`, {}, 10000);
    showJob(job);
    setActiveStep('result');
    const view = parameters.get('view');
    if (['pressure', 'velocity', 'streamlines'].includes(view)) await switchScene(view);
  } catch (_) {
    /* A stale job link leaves history and normal upload available. */
  }
}
