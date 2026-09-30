/* 小型印刷排样：前端交互 */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  inputs: null,     // 服务器上当前输入（含 version / input_hash）
  solution: null,   // 服务器上当前方案
  dirty: true,      // 表单是否有未保存修改
};

// ---------- 成品行 ----------
function productRow(p) {
  p = p || {name: '', w: '', h: '', qty: '', rotatable: false};
  const tr = document.createElement('tr');
  tr.className = 'product-row';
  tr.innerHTML = `
    <td><input class="p-name" type="text" maxlength="40" value="${escapeAttr(p.name)}"></td>
    <td><input class="p-w num" type="number" min="1" max="10000" value="${p.w}"></td>
    <td><input class="p-h num" type="number" min="1" max="10000" value="${p.h}"></td>
    <td><input class="p-qty num" type="number" min="1" max="1000000" value="${p.qty}"></td>
    <td class="center"><input class="p-rot" type="checkbox" ${p.rotatable ? 'checked' : ''}></td>
    <td class="center"><button type="button" class="del">删除</button></td>`;
  tr.querySelector('.del').addEventListener('click', () => {
    tr.remove();
    markDirty();
  });
  tr.querySelectorAll('input').forEach(inp => inp.addEventListener('input', markDirty));
  return tr;
}

function escapeAttr(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
}

function markDirty() {
  state.dirty = true;
  renderStatus();
}

function collectInputs() {
  return {
    master_w: parseInt($('#master_w').value, 10),
    master_h: parseInt($('#master_h').value, 10),
    kerf: parseInt($('#kerf').value, 10),
    max_sheets: parseInt($('#max_sheets').value, 10),
    max_states: parseInt($('#max_states').value, 10),
    products: $$('#products tbody .product-row').map(tr => ({
      name: $('.p-name', tr).value.trim(),
      w: parseInt($('.p-w', tr).value, 10),
      h: parseInt($('.p-h', tr).value, 10),
      qty: parseInt($('.p-qty', tr).value, 10),
      rotatable: $('.p-rot', tr).checked,
    })),
  };
}

// ---------- API ----------
async function api(method, url, body) {
  const opt = {method, headers: {'Content-Type': 'application/json'}};
  if (body !== undefined) opt.body = JSON.stringify(body);
  const resp = await fetch(url, opt);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = data.errors ? data.errors.join('\n') : (data.error || `HTTP ${resp.status}`);
    throw new Error(msg);
  }
  return data;
}

async function loadState() {
  const data = await api('GET', '/api/state');
  state.inputs = data.inputs;
  state.solution = data.solution;
  if (state.inputs) fillForm(state.inputs);
  state.dirty = false;
  renderStatus();
  renderSolution();
}

function fillForm(inp) {
  $('#master_w').value = inp.master_w;
  $('#master_h').value = inp.master_h;
  $('#kerf').value = inp.kerf;
  $('#max_sheets').value = inp.max_sheets;
  $('#max_states').value = inp.max_states;
  const tbody = $('#products tbody');
  tbody.innerHTML = '';
  inp.products.forEach(p => tbody.appendChild(productRow(p)));
}

// ---------- 保存 ----------
async function saveInputs() {
  $('#errors').textContent = '';
  try {
    const data = await api('PUT', '/api/inputs', collectInputs());
    state.inputs = data.state.inputs;
    state.solution = data.state.solution;
    state.dirty = false;
    renderStatus();
    renderSolution();
    flash('已保存，版本 v' + data.version + '；旧方案（如有）已失效。');
  } catch (e) {
    $('#errors').textContent = e.message;
  }
}

// ---------- 求解 ----------
async function solve() {
  if (state.dirty) {
    $('#errors').textContent = '表单有未保存的修改，请先点「保存输入」。非法输入不会保存，也无法用于搜索。';
    return;
  }
  $('#errors').textContent = '';
  $('#solve').disabled = true;
  $('#search-msg').textContent = '正在搜索…';
  try {
    const data = await api('POST', '/api/solve');
    state.inputs = data.state.inputs;
    state.solution = data.state.solution;
    if (data.result_status === 'feasible') {
      $('#search-msg').textContent = '找到可行方案（非最优保证），已保存。';
    } else if (data.result_status === 'infeasible') {
      $('#search-msg').textContent = '穷尽搜索后确认无解：' + (data.reason || '');
    } else {
      $('#search-msg').textContent =
        '搜索预算耗尽（已访问 ' + data.states_used + ' 个状态）：不能据此判定无解，可调大「搜索状态数上限」后重试。';
    }
    renderStatus();
    renderSolution();
  } catch (e) {
    $('#errors').textContent = e.message;
    $('#search-msg').textContent = '';
  } finally {
    $('#solve').disabled = false;
  }
}

// ---------- 渲染 ----------
function renderStatus() {
  const box = $('#status');
  if (!state.inputs) {
    box.innerHTML = '<span class="tag tag-none">尚未保存输入</span>';
  } else {
    let html = '<span class="tag tag-saved">当前输入版本：v' + state.inputs.version + '</span>';
    html += '<span class="tag">指纹 <code>' + state.inputs.input_hash + '</code></span>';
    if (state.dirty) html += '<span class="tag tag-warn">表单已修改，未保存（旧方案将在保存后失效）</span>';
    if (state.solution && state.solution.stale) {
      html += '<span class="tag tag-stale">已保存方案已失效：输入被修改，请重新搜索；失效方案不可导出</span>';
    }
    box.innerHTML = html;
  }
  const hasFresh = !!(state.solution && !state.solution.stale);
  $('#export-link').classList.toggle('disabled-link', !hasFresh);
  const btn = $('#solve');
  btn.disabled = state.dirty || !state.inputs;
  btn.title = state.dirty ? '请先保存修改后的输入' : '';
}

function renderSolution() {
  const host = $('#result');
  const sol = state.solution;
  if (!sol) {
    host.innerHTML = '<p class="muted">尚无方案。保存输入后点击「开始搜索」。</p>';
    return;
  }
  if (sol.stale) {
    host.innerHTML = '<p class="warn-box">该方案基于旧版本输入（v' + sol.input_version +
      '）生成，当前输入已变更。请重新搜索；导出会被拒绝。</p>';
    return;
  }
  const plan = sol.payload;
  const inp = plan.inputs;
  let html = '<div class="ok-box">可行方案：使用 ' + plan.sheets.length + ' / ' + inp.max_sheets +
    ' 张母纸，共 ' + plan.sheets.reduce((n, s) => n + s.cuts.length, 0) +
    ' 刀，搜索访问 ' + plan.states_used + ' 个状态。</div>';
  html += '<h3>实际成品数</h3><table class="actual"><tr><th>成品</th><th>尺寸 (mm)</th>' +
    '<th>旋转</th><th>需求</th><th>实际</th></tr>';
  inp.products.forEach((p, i) => {
    html += '<tr><td>' + escapeAttr(p.name) + '</td><td>' + p.w + '×' + p.h + '</td><td>' +
      (p.rotatable ? '可' : '不可') + '</td><td>' + p.qty + '</td><td>' + plan.actual[i] + '</td></tr>';
  });
  html += '</table><h3>逐张排样图</h3><div id="diagrams"></div>';
  host.innerHTML = html;
  renderPlans($('#diagrams'), plan, {steps: true});
}

function flash(msg) {
  $('#search-msg').textContent = msg;
}

// ---------- 初始化 ----------
document.addEventListener('DOMContentLoaded', () => {
  $('#add-product').addEventListener('click', () => {
    $('#products tbody').appendChild(productRow());
    markDirty();
  });
  $('#save').addEventListener('click', saveInputs);
  $('#solve').addEventListener('click', solve);
  $('#export-link').addEventListener('click', (e) => {
    if (state.dirty || !state.solution || state.solution.stale) e.preventDefault();
  });
  ['master_w', 'master_h', 'kerf', 'max_sheets', 'max_states'].forEach(id =>
    $('#' + id).addEventListener('input', markDirty));

  if (!$$('#products tbody .product-row').length) {
    $('#products tbody').appendChild(productRow());
  }
  loadState().catch(e => { $('#errors').textContent = e.message; });
});
