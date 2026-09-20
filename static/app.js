/* 直流网络校核器 —— 原生 JS 前端 */
"use strict";

const MAX_NODES = 30;

const state = {
  nodeCount: 4,
  ground: 1,
  components: [],
  seq: { R: 0, I: 0, V: 0 },
};

const KIND_LABEL = { R: "电阻", I: "电流源", V: "电压源" };

/* ---------------- 示例网络 ---------------- */
const EXAMPLES = {
  // 双电源电桥：V1 经 R1 到节点2，电流源并联注入，节点3/4 经电阻接地
  normal: {
    node_count: 4,
    ground: 1,
    components: [
      { id: "V1", kind: "V", a: 2, b: 1, value: 12 },
      { id: "R1", kind: "R", a: 2, b: 3, value: 4 },
      { id: "R2", kind: "R", a: 3, b: 1, value: 6 },
      { id: "R3", kind: "R", a: 3, b: 4, value: 2 },
      { id: "R4", kind: "R", a: 4, b: 1, value: 3 },
      { id: "I1", kind: "I", a: 1, b: 2, value: 0.5 },
    ],
  },
  // 未接地
  noground: {
    node_count: 3,
    ground: null,
    components: [
      { id: "V1", kind: "V", a: 1, b: 2, value: 10 },
      { id: "R1", kind: "R", a: 2, b: 3, value: 5 },
      { id: "R2", kind: "R", a: 3, b: 1, value: 15 },
    ],
  },
  // 浮置子网：5-6 只经电流源 I2 与主网耦合
  floating: {
    node_count: 6,
    ground: 1,
    components: [
      { id: "V1", kind: "V", a: 2, b: 1, value: 9 },
      { id: "R1", kind: "R", a: 2, b: 3, value: 3 },
      { id: "R2", kind: "R", a: 3, b: 1, value: 6 },
      { id: "R3", kind: "R", a: 5, b: 6, value: 2 },
      { id: "R4", kind: "R", a: 6, b: 5, value: 4 },
      { id: "I2", kind: "I", a: 3, b: 5, value: 1 },
    ],
  },
  // 矛盾电压源：V1 与 V2 并联但电压不同
  conflict: {
    node_count: 3,
    ground: 1,
    components: [
      { id: "V1", kind: "V", a: 2, b: 1, value: 12 },
      { id: "V2", kind: "V", a: 2, b: 1, value: 5 },
      { id: "R1", kind: "R", a: 2, b: 3, value: 10 },
      { id: "R2", kind: "R", a: 3, b: 1, value: 10 },
    ],
  },
};

/* ---------------- 工具函数 ---------------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function fmt(x, digits = 6) {
  if (x === null || x === undefined) return "—";
  const ax = Math.abs(x);
  if (ax !== 0 && (ax < 1e-4 || ax >= 1e7)) return x.toExponential(4);
  return Number(x.toFixed(digits)).toString();
}

function nextId(kind) {
  state.seq[kind] += 1;
  return `${kind}${state.seq[kind]}`;
}

function loadIntoState(data) {
  state.nodeCount = data.node_count;
  state.ground = data.ground;
  state.components = data.components.map((c) => ({ ...c }));
  state.seq = { R: 0, I: 0, V: 0 };
  for (const c of state.components) {
    const m = /^([RIV])(\d+)$/.exec(c.id);
    if (m) state.seq[m[1]] = Math.max(state.seq[m[1]], parseInt(m[2], 10));
  }
  renderGroundOptions();
  renderComponents();
  $("#node-count").value = state.nodeCount;
  hideResults();
}

/* ---------------- 渲染：接地选择 ---------------- */
function renderGroundOptions() {
  const sel = $("#ground-select");
  sel.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "（未指定）";
  if (state.ground === null) none.selected = true;
  sel.appendChild(none);
  for (let n = 1; n <= state.nodeCount; n++) {
    const o = document.createElement("option");
    o.value = String(n);
    o.textContent = `节点 ${n}`;
    if (state.ground === n) o.selected = true;
    sel.appendChild(o);
  }
}

/* ---------------- 渲染：元件表 ---------------- */
function nodeOptions(selected) {
  let html = "";
  for (let n = 1; n <= state.nodeCount; n++) {
    html += `<option value="${n}" ${n === selected ? "selected" : ""}>${n}</option>`;
  }
  return html;
}

function renderComponents() {
  const tbody = $("#comp-tbody");
  tbody.innerHTML = "";
  state.components.forEach((c, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="text" data-i="${i}" data-f="id" value="${c.id}" class="cell-id"></td>
      <td>
        <select data-i="${i}" data-f="kind">
          <option value="R" ${c.kind === "R" ? "selected" : ""}>R 电阻</option>
          <option value="I" ${c.kind === "I" ? "selected" : ""}>I 电流源</option>
          <option value="V" ${c.kind === "V" ? "selected" : ""}>V 电压源</option>
        </select>
      </td>
      <td><select data-i="${i}" data-f="a">${nodeOptions(c.a)}</select></td>
      <td><select data-i="${i}" data-f="b">${nodeOptions(c.b)}</select></td>
      <td><input type="number" step="any" data-i="${i}" data-f="value" value="${c.value}"></td>
      <td><button class="btn btn-danger-ghost" data-del="${i}" title="删除该元件">✕</button></td>`;
    tbody.appendChild(tr);
  });
}

/* ---------------- 客户端校验 ---------------- */
function validateLocal(data) {
  const warns = [];
  if (!Number.isInteger(data.node_count) || data.node_count < 1 || data.node_count > MAX_NODES) {
    warns.push(`节点数量必须为 1～${MAX_NODES} 之间的整数`);
  }
  if (data.ground !== null && !(data.ground >= 1 && data.ground <= data.node_count)) {
    warns.push("接地节点编号超出范围");
  }
  const ids = new Set();
  data.components.forEach((c, i) => {
    const name = c.id || `第 ${i + 1} 行`;
    if (!c.id.trim()) warns.push(`第 ${i + 1} 行元件缺少编号`);
    else if (ids.has(c.id)) warns.push(`元件编号「${c.id}」重复`);
    ids.add(c.id);
    if (!(c.a >= 1 && c.a <= data.node_count) || !(c.b >= 1 && c.b <= data.node_count)) {
      warns.push(`元件 ${name} 引用了超出 1～${data.node_count} 的节点`);
    }
    if (!Number.isFinite(c.value)) warns.push(`元件 ${name} 的数值无效`);
    if (c.kind === "R" && c.value <= 0) warns.push(`电阻 ${name} 的阻值必须为正数`);
    if (c.kind === "R" && c.a === c.b) warns.push(`电阻 ${name} 的两个端点不能相同`);
  });
  if (data.components.length === 0) warns.push("尚未录入任何元件");
  return warns;
}

function collectForm() {
  return {
    node_count: parseInt($("#node-count").value, 10),
    ground: $("#ground-select").value === "" ? null : parseInt($("#ground-select").value, 10),
    components: state.components.map((c) => ({
      id: c.id.trim(),
      kind: c.kind,
      a: c.a,
      b: c.b,
      value: c.value,
    })),
  };
}

/* ---------------- 结果渲染 ---------------- */
function hideResults() {
  $("#result-card").classList.add("hidden");
  $("#error-card").classList.add("hidden");
  $("#warn-card").classList.add("hidden");
}

function renderErrors(err) {
  const card = $("#error-card");
  card.classList.remove("hidden");
  $("#result-card").classList.add("hidden");
  const titles = {
    no_ground: "⚠ 无接地节点",
    structural: "⚠ 网络结构存在问题",
    singular: "⚠ 方程组无解（奇异）",
    validation_failed: "✏ 输入校验未通过",
  };
  $("#error-title").textContent = titles[err.code] || "⚠ 无法求解";
  const list = $("#error-list");
  list.innerHTML = "";
  (err.items || []).forEach((it) => {
    const div = document.createElement("div");
    div.className = "error-item";
    let chips = "";
    if (it.elements && it.elements.length) {
      chips += `<span class="chips">元件：${it.elements
        .map((e) => `<span class="chip">${e}</span>`).join("")}</span>`;
    }
    if (it.nodes && it.nodes.length) {
      chips += `<span class="chips">节点：${it.nodes
        .map((n) => `<span class="chip node">N${n}</span>`).join("")}</span>`;
    }
    div.innerHTML = `<span class="code-tag">${err.code}</span>${it.message || ""}${chips}`;
    list.appendChild(div);
  });
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderWarnings(warns) {
  const card = $("#warn-card");
  card.classList.remove("hidden");
  $("#warn-list").innerHTML = warns.map((w) => `<li>${w}</li>`).join("");
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function kindCell(kind) {
  const unit = { R: "Ω", I: "A", V: "V" }[kind];
  return `<span class="kind-tag kind-${kind}">${kind}</span>
          <span class="current-def">${KIND_LABEL[kind]} (${unit})</span>`;
}

function renderResult(res) {
  $("#error-card").classList.add("hidden");
  $("#warn-card").classList.add("hidden");
  const card = $("#result-card");
  card.classList.remove("hidden");

  // 节点电压
  const vb = $("#voltage-table tbody");
  vb.innerHTML = "";
  let vMax = 0;
  res.node_voltages.forEach((r) => { vMax = Math.max(vMax, Math.abs(r.voltage || 0)); });
  res.node_voltages.forEach((r) => {
    const tr = document.createElement("tr");
    if (r.is_ground) tr.className = "node-ground";
    else if (!r.used) tr.className = "node-unused";
    const ratio = vMax > 0 ? Math.min(1, Math.abs(r.voltage || 0) / vMax) : 0;
    let note = "";
    if (r.is_ground) note = `<span class="badge badge-ground">⏚ 接地参考</span>`;
    else if (!r.used) note = `<span class="badge badge-unused">未接入电路</span>`;
    else if (ratio > 0.66) note = `<span class="badge" style="background:#dbeafe;color:#1d4ed8;border:1px solid #93c5fd">高电位</span>`;
    tr.innerHTML = `<td><b>${r.node}</b></td>
      <td class="num voltage-high" ${ratio > 0.66 && !r.is_ground && r.used ? 'style="color:#1d4ed8"' : ""}>
        ${fmt(r.voltage)} V</td>
      <td>${note}</td>`;
    vb.appendChild(tr);
  });

  // 支路
  const bb = $("#branch-table tbody");
  bb.innerHTML = "";
  let iMax = 0;
  res.branches.forEach((b) => { iMax = Math.max(iMax, Math.abs(b.current)); });
  res.branches.forEach((b) => {
    const tr = document.createElement("tr");
    const arrow = b.direction_a_to_b ? "→" : "←";
    const dirDesc = b.direction_a_to_b ? `${b.a} → ${b.b}` : `${b.b} → ${b.a}`;
    const isSource = b.power_absorbed < -1e-12;
    if (isSource) tr.className = "power-source";
    const hot = iMax > 0 && Math.abs(b.current) / iMax > 0.8 ? 'style="color:#1d4ed8;font-weight:700"' : "";
    tr.innerHTML = `
      <td><b>${b.id}</b></td>
      <td>${kindCell(b.kind)}</td>
      <td class="endpoint">${b.a} ⟷ ${b.b}</td>
      <td class="num" ${hot}>
        <span class="${b.current < 0 ? "neg" : ""}">${fmt(b.current)} A</span>
        <span class="dir-arrow" title="实际方向 ${dirDesc}">${arrow}</span>
        <span class="current-def">${dirDesc}</span>
      </td>
      <td class="num ${b.voltage < 0 ? "neg" : ""}">${fmt(b.voltage)} V</td>
      <td class="num ${b.power_absorbed < 0 ? "neg" : ""}">${fmt(b.power_absorbed)} W</td>`;
    bb.appendChild(tr);
  });

  // 功率平衡
  const p = res.power_balance;
  $("#power-grid").innerHTML = `
    <div class="stat"><div class="label">电源总发出功率</div>
      <div class="value">${fmt(p.total_generated)} W</div></div>
    <div class="stat diss"><div class="label">总吸收（电阻等）</div>
      <div class="value">${fmt(p.total_dissipated)} W</div></div>
    <div class="stat mis"><div class="label">功率平衡误差（绝对值）</div>
      <div class="value">${fmt(p.mismatch_w, 10)} W</div></div>
    <div class="stat mis"><div class="label">相对误差</div>
      <div class="value">${p.relative_error < 1e-3 ? p.relative_error.toExponential(3) : fmt(p.relative_error)}</div></div>
    <div class="stat"><div class="label">最大 KCL 残差</div>
      <div class="value">${fmt(p.kcl_residual_a, 10)} A</div></div>`;
  const badge = $("#balance-badge");
  if (p.relative_error < 1e-9 && p.kcl_residual_a < 1e-9) {
    badge.className = "balance-badge ok";
    badge.textContent = `✔ 功率平衡校核通过：发出 ${fmt(p.total_generated)} W ≈ 吸收 ${fmt(p.total_dissipated)} W`;
  } else {
    badge.className = "balance-badge bad";
    badge.textContent = `✖ 功率不平衡！相对误差 ${p.relative_error.toExponential(3)}，KCL 残差 ${fmt(p.kcl_residual_a)} A`;
  }
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------- 提交 ---------------- */
async function analyze() {
  $("#warn-card").classList.add("hidden");
  const data = collectForm();
  const warns = validateLocal(data);
  if (warns.length) {
    renderWarnings(warns);
    return;
  }
  const btn = $("#analyze-btn");
  btn.disabled = true;
  btn.textContent = "求解中…";
  try {
    const resp = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const json = await resp.json();
    if (json.ok) renderResult(json);
    else renderErrors(json.error);
  } catch (e) {
    renderErrors({ code: "network", message: "无法连接求解服务",
                   items: [{ message: String(e) }] });
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ 校核网络";
  }
}

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  $("#node-count").addEventListener("change", (e) => {
    let n = parseInt(e.target.value, 10);
    if (Number.isNaN(n) || n < 1) n = 1;
    if (n > MAX_NODES) n = MAX_NODES;
    e.target.value = n;
    state.nodeCount = n;
    if (state.ground !== null && state.ground > n) state.ground = null;
    // 截断越界端点
    state.components.forEach((c) => {
      if (c.a > n) c.a = n;
      if (c.b > n) c.b = n;
    });
    renderGroundOptions();
    renderComponents();
  });

  $("#ground-select").addEventListener("change", (e) => {
    state.ground = e.target.value === "" ? null : parseInt(e.target.value, 10);
  });

  $("#comp-tbody").addEventListener("input", (e) => {
    const t = e.target;
    const i = t.dataset.i;
    if (i === undefined) return;
    const f = t.dataset.f;
    const c = state.components[parseInt(i, 10)];
    if (f === "a" || f === "b") c[f] = parseInt(t.value, 10);
    else if (f === "value") c[f] = parseFloat(t.value);
    else c[f] = t.value;
  });

  $("#comp-tbody").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-del]");
    if (!btn) return;
    state.components.splice(parseInt(btn.dataset.del, 10), 1);
    renderComponents();
  });

  const addComp = (kind) => {
    state.components.push({
      id: nextId(kind), kind, a: 1,
      b: Math.min(2, state.nodeCount),
      value: kind === "R" ? 10 : kind === "I" ? 1 : 5,
    });
    renderComponents();
    const rows = $$("#comp-tbody tr");
    rows[rows.length - 1]?.querySelector("input.cell-id")?.focus();
  };
  $("#add-r").addEventListener("click", () => addComp("R"));
  $("#add-i").addEventListener("click", () => addComp("I"));
  $("#add-v").addEventListener("click", () => addComp("V"));

  $("#clear-btn").addEventListener("click", () => {
    state.components = [];
    state.seq = { R: 0, I: 0, V: 0 };
    renderComponents();
    hideResults();
  });

  $("#analyze-btn").addEventListener("click", analyze);

  const menu = $("#example-menu");
  $("#example-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    menu.classList.toggle("open");
  });
  document.addEventListener("click", () => menu.classList.remove("open"));
  menu.addEventListener("click", (e) => {
    const b = e.target.closest("[data-example]");
    if (!b) return;
    loadIntoState(EXAMPLES[b.dataset.example]);
    menu.classList.remove("open");
  });
}

/* ---------------- 启动 ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadIntoState(EXAMPLES.normal);
});
