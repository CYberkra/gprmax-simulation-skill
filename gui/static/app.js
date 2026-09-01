// gprmax Simulation Skill GUI v2 — step-driven workflow
"use strict";

let SESSION_DIR = null;
let STEP_FIELDS = null;
let CURRENT_STEP = 0;
let CONTRACT = null; // latest contract draft (shared across steps)

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

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function errHtml(e) { return `<div class="unmatched">${esc(e.message)}</div>`; }
function imgHtml(pngB64) { return `<img class="preview" src="data:image/png;base64,${pngB64}">`; }

// ------------------------------------------------------------------------
// Step definitions
// ------------------------------------------------------------------------

const STEPS = [
  { id: "scenario", label: "① 场景与目标" },
  { id: "axes", label: "② 配置轴推荐" },
  { id: "sketch", label: "③ 几何草图" },
  { id: "env", label: "④ 环境与资源" },
  { id: "template", label: "⑤ 模板与调研" },
  { id: "diagnose", label: "⑥ 数值诊断" },
  { id: "sensitivity", label: "⑦ 敏感性" },
  { id: "report", label: "⑧ 模型卡报告" },
  { id: "study", label: "⑨ 研究目录" },
  { id: "process", label: "⑩ Ascan/Bscan" },
];

function renderStepRail() {
  $("stepRail").innerHTML = STEPS.map((s, i) =>
    `<button data-step="${i}" class="${i === CURRENT_STEP ? "active" : ""}">${s.label}</button>`
  ).join("");
  $("stepRail").querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => { CURRENT_STEP = Number(btn.dataset.step); renderCurrentStep(); });
  });
}

function renderCurrentStep() {
  renderStepRail();
  const { id } = STEPS[CURRENT_STEP];
  const A = $("panelA"), B = $("panelB");
  A.innerHTML = ""; B.innerHTML = "";
  switch (id) {
    case "scenario": renderScenarioStep(A, B); break;
    case "axes": renderAxesStep(A, B); break;
    case "sketch": renderSketchStep(A, B); break;
    case "env": renderEnvStep(A, B); break;
    case "template": renderTemplateStep(A, B); break;
    case "diagnose": renderDiagnoseStep(A, B); break;
    case "sensitivity": renderSensitivityStep(A, B); break;
    case "report": renderReportStep(A, B); break;
    case "study": renderStudyStep(A, B); break;
    case "process": renderProcessStep(A, B); break;
  }
}

// ------------------------------------------------------------------------
// ① Scenario & wizard
// ------------------------------------------------------------------------

async function renderScenarioStep(A, B) {
  A.innerHTML = `<h2>① 场景与目标（向导）</h2><div id="formContainer">加载中…</div>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="btnInit">新建会话</button>
      <button id="btnDump">生成契约草稿</button>
      <button id="btnLoadContract">载入契约 → 后续步骤</button>
    </div><div id="dumpOutput" style="margin-top:10px"></div>`;
  B.innerHTML = `<h2>会话状态</h2><div id="sessionStatus">未创建会话</div>`;

  if (!STEP_FIELDS) {
    const res = await fetch("/api/wizard/fields");
    STEP_FIELDS = await res.json();
  }
  const html = Object.entries(STEP_FIELDS).map(([step, info]) => {
    const fields = Object.entries(info.fields).map(([field, spec]) => {
      const optional = spec.optional ? ' <span class="muted">(可选)</span>' : "";
      let input;
      if (spec.choices) {
        input = `<select data-field="${field}">${spec.choices.map((c) => `<option>${esc(c)}</option>`).join("")}</select>`;
      } else {
        const type = spec.type === "number" ? "number" : spec.type === "int" ? "number" : "text";
        input = `<input data-field="${field}" type="${type}" step="${spec.type === "number" ? "any" : "1"}">`;
      }
      return `<div class="field"><label>${esc(spec.label)}${optional}</label>${input}</div>`;
    }).join("");
    return `<div class="step"><h3>${esc(info.question)}</h3>${fields}</div>`;
  }).join("");
  $("formContainer").innerHTML = html;
  $("formContainer").querySelectorAll("[data-field]").forEach((el) => {
    el.addEventListener("change", async () => {
      if (!SESSION_DIR) return;
      try {
        await api("/api/wizard/answer", { session_dir: SESSION_DIR, field: el.dataset.field, value: el.value });
      } catch (e) { console.warn("answer error:", e.message); }
    });
  });

  $("btnInit").addEventListener("click", async () => {
    try {
      const res = await api("/api/wizard/init");
      SESSION_DIR = res.session_dir;
      $("sessionLabel").textContent = "会话: " + res.session_dir;
      $("sessionStatus").textContent = "会话已创建，填写表单自动保存。";
    } catch (e) { alert("创建会话失败: " + e.message); }
  });
  $("btnDump").addEventListener("click", async () => {
    if (!SESSION_DIR) { alert("请先「新建会话」"); return; }
    try {
      const payload = await api("/api/wizard/dump", { session_dir: SESSION_DIR });
      CONTRACT = payload.contract_draft;
      $("dumpOutput").innerHTML = `<h3 class="muted" style="margin:8px 0 4px">契约草稿</h3><pre>${esc(JSON.stringify(CONTRACT, null, 2))}</pre>`;
    } catch (e) { $("dumpOutput").innerHTML = errHtml(e); }
  });
  $("btnLoadContract").addEventListener("click", () => {
    if (!CONTRACT) { alert("先「生成契约草稿」"); return; }
    alert("契约已载入，后续步骤（草图/诊断/敏感性/报告）将使用它。");
  });
}

// ------------------------------------------------------------------------
// ② Axes recommendation
// ------------------------------------------------------------------------

function renderAxesStep(A, B) {
  A.innerHTML = `<h2>② 配置轴推荐</h2>
    <div class="field"><label>场景类型</label><select id="recScenario">
      ${["tunnel","landslide","archaeology","geotechnical","inspection","other"]
        .map((s) => `<option>${s}</option>`).join("")}
    </select></div>
    <div class="field"><label>拟真度</label><select id="recFidelity">
      <option value="quick">快速验证</option><option value="standard" selected>标准研究</option>
      <option value="publication">发表级</option>
    </select></div>
    <div class="field"><label><input type="checkbox" id="recSfcw" checked> 需要 SFCW 体制结论</label></div>
    <button class="primary" id="btnRecommend" style="width:100%">生成推荐</button>
    <div id="recOutput" style="margin-top:10px"></div>`;
  B.innerHTML = `<h2>推荐结果</h2><div id="recResult" class="muted">点「生成推荐」查看各配置轴建议。</div>`;

  $("btnRecommend").addEventListener("click", async () => {
    try {
      const rec = await api("/api/axes/recommend", {
        scenario: $("recScenario").value, fidelity: $("recFidelity").value,
        needs_sfcw: $("recSfcw").checked,
      });
      const labels = { antenna: "天线", sfcw: "SFCW", dispersion: "色散", noise: "加噪",
                       geometry: "目标几何", precision: "精度", dimension: "模型维度" };
      $("recResult").innerHTML = Object.entries(rec).map(([axis, r]) =>
        `<div class="rec"><span class="axis">${labels[axis] || axis}</span>
         <span class="tag def">${esc(r.option)}</span>
         <div class="rationale">${esc(r.rationale)}</div></div>`
      ).join("");
      $("recOutput").innerHTML = "";
    } catch (e) { $("recResult").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ③ Geometry sketch
// ------------------------------------------------------------------------

function renderSketchStep(A, B) {
  A.innerHTML = `<h2>③ 几何截面草图</h2>
    <div class="muted" style="margin-bottom:8px">基于契约草稿（①步骤生成）渲染剖面示意图：域、介质、目标、Tx/Rx。</div>
    <button class="primary" id="btnSketch">渲染草图</button>
    <div id="sketchHint" class="muted" style="margin-top:8px"></div>`;
  B.innerHTML = `<h2>草图预览</h2><div id="sketchOutput" class="muted">等待渲染…</div>`;

  $("btnSketch").addEventListener("click", async () => {
    if (!CONTRACT) { $("sketchHint").innerHTML = "⚠ 请先在 ① 步骤生成契约草稿。"; return; }
    try {
      const res = await api("/api/sketch", { contract: CONTRACT });
      $("sketchOutput").innerHTML = imgHtml(res.png_b64);
      $("sketchHint").innerHTML = "";
    } catch (e) { $("sketchOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ④ Environment
// ------------------------------------------------------------------------

function renderEnvStep(A, B) {
  A.innerHTML = `<h2>④ 环境与资源</h2>
    <div class="muted" style="margin-bottom:8px">探测本机 GPU/内存/磁盘/Python/gprMax。只提供信息，运行环境由你决定。</div>
    <button class="primary" id="btnProbe">探测本机</button>`;
  B.innerHTML = `<h2>探测报告</h2><div id="probeOutput" class="muted">未探测。</div>`;

  $("btnProbe").addEventListener("click", async () => {
    try {
      const res = await api("/api/probe");
      const items = [
        ["GPU", (res.data.gpu && res.data.gpu.length)
          ? res.data.gpu.map((g) => `${g.name} ${g.memory_total}`).join("; ") : "未检测到 NVIDIA GPU"],
        ["系统内存", res.data.memory_total_gb ? `${res.data.memory_total_gb.toFixed(1)} GB` : "未知"],
        ["磁盘", res.data.disk ? `剩余 ${res.data.disk.free_gb} GB` : "未知"],
        ["Python", res.data.python ? res.data.python.version : "未知"],
        ["gprMax", res.data.gprmax ? `已安装 ${res.data.gprmax.version}` : "未安装"],
      ];
      $("probeOutput").innerHTML = items.map(([k, v]) =>
        `<div class="probe-item"><span class="k">${k}</span><span>${esc(v)}</span></div>`).join("") +
        `<pre style="margin-top:8px">${esc(res.text_report)}</pre>`;
    } catch (e) { $("probeOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ⑤ Template match + research needs
// ------------------------------------------------------------------------

function renderTemplateStep(A, B) {
  A.innerHTML = `<h2>⑤ 模板匹配 + 调研需求</h2>
    <div class="muted" style="margin-bottom:8px">基于契约草稿检查是否匹配已验证场景模板；不匹配则列出待调研项。</div>
    <button class="primary" id="btnCheck">检查</button>`;
  B.innerHTML = `<h2>结果</h2><div id="checkOutput" class="muted">未检查。</div>`;

  $("btnCheck").addEventListener("click", async () => {
    if (!CONTRACT) { $("checkOutput").innerHTML = `<div class="unmatched">请先在 ① 生成契约草稿。</div>`; return; }
    try {
      const signature = {
        scenario_type: (CONTRACT.task && CONTRACT.task.objective) || "other",
        needs_sfcw: CONTRACT.waveform && CONTRACT.waveform.measurement_mode === "sfcw_equivalent",
        target_depth_m: CONTRACT.project && CONTRACT.project.target_depth_m,
      };
      const matchRes = await api("/api/template/match", { signature });
      const matchHtml = matchRes.matched
        ? `<div class="matched">✅ 匹配已验证模板：<b>${esc(matchRes.template.name)}</b>
           <div class="muted">验证于：${esc(matchRes.template.verified_by.join("、"))}</div></div>`
        : `<div class="unmatched">❌ 无已验证模板严格匹配（不会部分参考）</div>`;
      const needsRes = await api("/api/research/needs", { contract: CONTRACT, materials_dir: "materials" });
      const needsHtml = needsRes.needs.length
        ? needsRes.needs.map((n) =>
            `<div class="need">[${n.priority}] ${n.kind}: <b>${esc(n.topic)}</b>
             <div class="reason">${esc(n.reason)}</div></div>`).join("")
        : `<div class="matched">✅ 无需调研，材料库与已验证模板已覆盖。</div>`;
      $("checkOutput").innerHTML = matchHtml + `<h3 class="muted" style="margin:10px 0 6px">调研需求</h3>` + needsHtml;
    } catch (e) { $("checkOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ⑥ Numerical diagnostics
// ------------------------------------------------------------------------

function renderDiagnoseStep(A, B) {
  A.innerHTML = `<h2>⑥ 数值诊断</h2>
    <div class="muted" style="margin-bottom:8px">对契约做网格/CFL/PML/时窗/显存预诊断。</div>
    <button class="primary" id="btnDiagnose">运行诊断</button>`;
  B.innerHTML = `<h2>诊断结果</h2><div id="diagOutput" class="muted">未运行。</div>`;

  $("btnDiagnose").addEventListener("click", async () => {
    if (!CONTRACT) { $("diagOutput").innerHTML = `<div class="unmatched">请先在 ① 生成契约草稿。</div>`; return; }
    try {
      const res = await api("/api/diagnose", { contract: CONTRACT });
      const markers = { BLOCK: "⛔", WARN: "⚠️", OK: "✅" };
      $("diagOutput").innerHTML = res.findings.map((f) =>
        `<div class="finding ${f.severity}">${markers[f.severity] || "·"} <b>[${f.severity}]</b> ${esc(f.check)}: ${esc(f.message)}</div>`
      ).join("") || `<div class="matched">无发现。</div>`;
    } catch (e) { $("diagOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ⑦ Sensitivity
// ------------------------------------------------------------------------

function renderSensitivityStep(A, B) {
  A.innerHTML = `<h2>⑦ 参数敏感性</h2>
    <div class="muted" style="margin-bottom:8px">对关键参数 ±扰动扫描，按相对变化排序。</div>
    <button class="primary" id="btnSens">运行敏感性分析</button>`;
  B.innerHTML = `<h2>敏感性表</h2><div id="sensOutput" class="muted">未运行。</div>`;

  $("btnSens").addEventListener("click", async () => {
    if (!CONTRACT) { $("sensOutput").innerHTML = `<div class="unmatched">请先在 ① 生成契约草稿。</div>`; return; }
    try {
      const res = await api("/api/sensitivity", { contract: CONTRACT });
      const rows = res.results.slice(0, 10).map((r) =>
        `<tr><td>${esc(r.parameter)}</td><td>${esc(r.check)}</td>
         <td>${r.base_metric != null ? Number(r.base_metric).toPrecision(3) : "—"}</td>
         <td>${r.relative_change != null ? (Number(r.relative_change) * 100).toFixed(1) + "%" : "—"}</td></tr>`
      ).join("");
      $("sensOutput").innerHTML = `<table><thead><tr><th>参数</th><th>检查</th><th>基准</th><th>相对变化</th></tr></thead><tbody>${rows}</tbody></table>`;
    } catch (e) { $("sensOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ⑧ Model-card report
// ------------------------------------------------------------------------

function renderReportStep(A, B) {
  A.innerHTML = `<h2>⑧ 模型卡报告</h2>
    <div class="muted" style="margin-bottom:8px">把契约/诊断/敏感性/处理链/环境聚合成一份 Markdown 模型卡。</div>
    <button class="primary" id="btnReport">生成模型卡</button>`;
  B.innerHTML = `<h2>Markdown 预览</h2><div id="reportOutput" class="muted">未生成。</div>`;

  $("btnReport").addEventListener("click", async () => {
    if (!CONTRACT) { $("reportOutput").innerHTML = `<div class="unmatched">请先在 ① 生成契约草稿。</div>`; return; }
    try {
      const res = await api("/api/report", { contract: CONTRACT });
      $("reportOutput").innerHTML = `<pre>${esc(res.markdown)}</pre>`;
    } catch (e) { $("reportOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ⑨ Study directory
// ------------------------------------------------------------------------

function renderStudyStep(A, B) {
  A.innerHTML = `<h2>⑨ 研究目录管理</h2>
    <div class="field"><label>研究目录路径</label><input id="studyPath" value="study" placeholder="01_20260830_SFCW_SLIDE_WET"></div>
    <div class="field"><label>研究名（可选，init 用）</label><input id="studyName" placeholder="01_20260830_SFCW_SLIDE_WET"></div>
    <div class="row">
      <button class="primary" id="btnStudyInit">init 骨架</button>
      <button id="btnStudyAudit">layout audit</button>
      <button id="btnStudyHash">layout hash</button>
      <button id="btnStudyCheck">check-model</button>
    </div>`;
  B.innerHTML = `<h2>结果</h2><div id="studyOutput" class="muted">未操作。</div>`;

  $("btnStudyInit").addEventListener("click", async () => {
    try {
      const res = await api("/api/study/init", { path: $("studyPath").value, name: $("studyName").value });
      $("studyOutput").innerHTML = `<div class="matched">✅ 已创建 ${res.created.length} 项。</div>`;
    } catch (e) { $("studyOutput").innerHTML = errHtml(e); }
  });
  $("btnStudyAudit").addEventListener("click", async () => {
    try {
      const res = await api("/api/study/audit", { path: $("studyPath").value });
      $("studyOutput").innerHTML = res.findings.map((f) =>
        `<div class="finding ${f.severity}">[${f.severity}] ${esc(f.check)}: ${esc(f.message)}</div>`).join("");
    } catch (e) { $("studyOutput").innerHTML = errHtml(e); }
  });
  $("btnStudyHash").addEventListener("click", async () => {
    try {
      const res = await api("/api/study/hash", { path: $("studyPath").value });
      $("studyOutput").innerHTML = `<div class="matched">✅ 已记录 ${res.count} 个 SHA-256 → ${esc(res.manifest)}</div>`;
    } catch (e) { $("studyOutput").innerHTML = errHtml(e); }
  });
  $("btnStudyCheck").addEventListener("click", async () => {
    try {
      const res = await api("/api/study/check", { path: $("studyPath").value });
      $("studyOutput").innerHTML = res.established
        ? `<div class="matched">✅ 模型已确立，可进入批量仿真。</div>`
        : `<div class="unmatched">❌ 模型未确立：<br>${res.gaps.map((g) => `· ${esc(g)}`).join("<br>")}</div>`;
    } catch (e) { $("studyOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// ⑩ Ascan/Bscan processing
// ------------------------------------------------------------------------

function renderProcessStep(A, B) {
  A.innerHTML = `<h2>⑩ Ascan/Bscan 可视化</h2>
    <div class="field"><label>.out 文件路径</label><input id="procPath" placeholder="outputs/case.out"></div>
    <div class="field"><label>频带 (MHz)</label><input id="procBand" value="200-350"></div>
    <button class="primary" id="btnProcess">处理并绘制 A-scan</button>
    <div id="procParams" style="margin-top:10px"></div>`;
  B.innerHTML = `<h2>A-scan 预览</h2><div id="procOutput" class="muted">未处理。</div>`;

  $("btnProcess").addEventListener("click", async () => {
    try {
      const res = await api("/api/process", {
        out_path: $("procPath").value, band: $("procBand").value,
      });
      $("procOutput").innerHTML = imgHtml(res.png_b64);
      $("procParams").innerHTML = `<pre>${esc(res.params_json)}</pre>`;
    } catch (e) { $("procOutput").innerHTML = errHtml(e); }
  });
}

// ------------------------------------------------------------------------
// init
// ------------------------------------------------------------------------

(async function init() {
  renderStepRail();
  renderCurrentStep();
})();
