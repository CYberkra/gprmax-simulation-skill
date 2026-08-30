// gprmax Simulation Skill GUI — frontend logic
"use strict";

let SESSION_DIR = null;
let STEP_FIELDS = null;

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* noop */ }
    throw new Error(detail);
  }
  return res.json();
}

// ------------------------------------------------------------------------
// Wizard form rendering
// ------------------------------------------------------------------------

async function loadWizardFields() {
  const res = await fetch("/api/wizard/fields");
  STEP_FIELDS = await res.json();
}

function fieldInput(field, spec) {
  const choices = spec.choices;
  if (choices) {
    const opts = choices
      .map((c) => `<option value="${c}">${c}</option>`)
      .join("");
    return `<select data-field="${field}">${opts}</select>`;
  }
  const type = spec.type === "number" ? "number" : spec.type === "int" ? "number" : "text";
  return `<input data-field="${field}" type="${type}" step="${spec.type === "number" ? "any" : "1"}">`;
}

function renderForm() {
  const container = $("formContainer");
  const html = Object.entries(STEP_FIELDS)
    .map(([step, info]) => {
      const fields = Object.entries(info.fields)
        .map(([field, spec]) => {
          const optional = spec.optional ? ' <span class="muted">(可选)</span>' : "";
          return `<div class="field">
              <label>${spec.label}${optional}</label>${fieldInput(field, spec)}
            </div>`;
        })
        .join("");
      return `<div class="step"><h3>${info.question}</h3>${fields}</div>`;
    })
    .join("");
  container.innerHTML = html;
  // wire field changes to the wizard session
  container.querySelectorAll("[data-field]").forEach((el) => {
    el.addEventListener("change", async () => {
      if (!SESSION_DIR) { alert("请先点击「新建会话」"); return; }
      try {
        await api("/api/wizard/answer", {
          session_dir: SESSION_DIR, field: el.dataset.field, value: el.value,
        });
      } catch (e) { console.warn("answer error:", e.message); }
    });
  });
}

// ------------------------------------------------------------------------
// Wizard actions
// ------------------------------------------------------------------------

async function initSession() {
  try {
    const res = await api("/api/wizard/init");
    SESSION_DIR = res.session_dir;
    $("sessionLabel").textContent = "会话: " + res.session_dir;
    alert("会话已创建。填写表单（每步改变会自动保存），然后「生成契约草稿」。");
  } catch (e) { alert("创建会话失败: " + e.message); }
}

async function dumpContract() {
  if (!SESSION_DIR) { alert("请先「新建会话」"); return; }
  try {
    const payload = await api("/api/wizard/dump", { session_dir: SESSION_DIR });
    $("dumpOutput").innerHTML =
      `<h3 class="muted" style="margin:8px 0 4px">契约草稿</h3><pre>${esc(JSON.stringify(payload.contract_draft, null, 2))}</pre>`;
  } catch (e) { $("dumpOutput").innerHTML = `<div class="unmatched">${esc(e.message)}</div>`; }
}

// ------------------------------------------------------------------------
// Axes recommendations
// ------------------------------------------------------------------------

async function recommend() {
  const scenario = $("recScenario").value;
  const fidelity = $("recFidelity").value;
  const needsSfcw = $("recSfcw").checked;
  try {
    const rec = await api("/api/axes/recommend", { scenario, fidelity, needs_sfcw: needsSfcw });
    const html = Object.entries(rec)
      .map(([axis, r]) => {
        const labels = { antenna: "天线", sfcw: "SFCW", dispersion: "色散",
                         noise: "加噪", geometry: "目标几何", precision: "精度" };
        return `<div class="rec">
            <span class="axis">${labels[axis] || axis}</span>
            <span class="tag def">${esc(r.option)}</span>
            <div class="rationale">${esc(r.rationale)}</div>
          </div>`;
      })
      .join("");
    $("recOutput").innerHTML = html;
  } catch (e) { $("recOutput").innerHTML = `<div class="unmatched">${esc(e.message)}</div>`; }
}

// ------------------------------------------------------------------------
// Environment probe
// ------------------------------------------------------------------------

async function probe() {
  try {
    const res = await api("/api/probe");
    const items = [
      ["GPU", (res.data.gpu && res.data.gpu.length)
        ? res.data.gpu.map((g) => `${g.name} ${g.memory_total}`).join("; ")
        : "未检测到 NVIDIA GPU"],
      ["系统内存", res.data.memory_total_gb ? `${res.data.memory_total_gb.toFixed(1)} GB` : "未知"],
      ["磁盘", res.data.disk ? `剩余 ${res.data.disk.free_gb} GB` : "未知"],
      ["Python", res.data.python ? res.data.python.version : "未知"],
      ["gprMax", res.data.gprmax ? `已安装 ${res.data.gprmax.version}` : "未安装"],
    ];
    $("probeOutput").innerHTML =
      items.map(([k, v]) => `<div class="probe-item"><span class="k">${k}</span><span>${esc(v)}</span></div>`).join("") +
      `<pre style="margin-top:8px">${esc(res.text_report)}</pre>`;
  } catch (e) { $("probeOutput").innerHTML = `<div class="unmatched">${esc(e.message)}</div>`; }
}

// ------------------------------------------------------------------------
// Template match + research needs
// ------------------------------------------------------------------------

async function checkTemplateAndNeeds() {
  if (!SESSION_DIR) { alert("请先「新建会话」并「生成契约草稿」"); return; }
  let contract;
  try {
    const payload = await api("/api/wizard/dump", { session_dir: SESSION_DIR });
    contract = payload.contract_draft;
  } catch (e) {
    $("checkOutput").innerHTML = `<div class="unmatched">契约草稿不可用: ${esc(e.message)}</div>`;
    return;
  }
  const signature = {
    scenario_type: (contract.task && contract.task.objective) || "other",
    needs_sfcw: contract.waveform && contract.waveform.measurement_mode === "sfcw_equivalent",
    target_depth_m: contract.project && contract.project.target_depth_m,
  };
  try {
    const matchRes = await api("/api/template/match", { signature });
    const matchHtml = matchRes.matched
      ? `<div class="matched">✅ 匹配已验证模板：<b>${esc(matchRes.template.name)}</b><div class="muted">验证于：${esc(matchRes.template.verified_by.join("、"))}</div></div>`
      : `<div class="unmatched">❌ 无已验证模板严格匹配（不会部分参考）</div>`;

    const needsRes = await api("/api/research/needs", { contract, materials_dir: "materials" });
    const needsHtml = needsRes.needs.length
      ? needsRes.needs.map((n) =>
          `<div class="need">[${n.priority}] ${n.kind}: <b>${esc(n.topic)}</b><div class="reason">${esc(n.reason)}</div></div>`
        ).join("")
      : `<div class="matched">✅ 无需调研，材料库与已验证模板已覆盖。</div>`;

    $("checkOutput").innerHTML = matchHtml + `<h3 class="muted" style="margin:10px 0 6px">调研需求</h3>` + needsHtml;
  } catch (e) { $("checkOutput").innerHTML = `<div class="unmatched">${esc(e.message)}</div>`; }
}

// ------------------------------------------------------------------------
// utils
// ------------------------------------------------------------------------

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ------------------------------------------------------------------------
// init
// ------------------------------------------------------------------------

(async function init() {
  await loadWizardFields();
  renderForm();
  $("btnInit").addEventListener("click", initSession);
  $("btnDump").addEventListener("click", dumpContract);
  $("btnRecommend").addEventListener("click", recommend);
  $("btnProbe").addEventListener("click", probe);
  $("btnCheck").addEventListener("click", checkTemplateAndNeeds);
})();
