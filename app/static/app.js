/* 前端交互逻辑：状态机 upload -> extracting -> form -> result。 */

// 与后端 schemas.MARKER_FIELDS 保持一致；unit 用于表单与提示展示
const FIELDS = [
  { key: "albumin", label: "白蛋白", unit: "g/L" },
  { key: "creatinine", label: "肌酐", unit: "μmol/L" },
  { key: "glucose", label: "葡萄糖（血糖）", unit: "mmol/L" },
  { key: "crp", label: "C 反应蛋白", unit: "mg/L" },
  { key: "lymphocyte_pct", label: "淋巴细胞百分比", unit: "%" },
  { key: "mcv", label: "平均红细胞体积", unit: "fL" },
  { key: "rdw", label: "红细胞分布宽度（RDW-CV）", unit: "%" },
  { key: "alp", label: "碱性磷酸酶", unit: "U/L" },
  { key: "wbc", label: "白细胞计数", unit: "10⁹/L" },
  { key: "age", label: "实际年龄", unit: "岁" },
];

const DISCLAIMER =
  "本结果由公开公式计算，仅供健康参考，不构成医疗诊断或医疗建议；如有不适请就医。";
const MAX_BYTES = 10 * 1024 * 1024;

const $ = (id) => document.getElementById(id);
const steps = {
  upload: $("step-upload"),
  extracting: $("step-extracting"),
  form: $("step-form"),
  result: $("step-result"),
};

const MAX_IMAGES = 10;
let selectedFiles = [];

/* ---------- 页面状态切换 ---------- */
function showStep(name) {
  Object.keys(steps).forEach((key) => {
    steps[key].hidden = key !== name;
  });
}

/* ---------- 表单构建 ---------- */
function buildForm() {
  const grid = $("field-grid");
  grid.innerHTML = "";
  FIELDS.forEach((field) => {
    const wrap = document.createElement("div");
    wrap.className = "field";
    wrap.id = `field-${field.key}`;

    const label = document.createElement("label");
    label.htmlFor = `input-${field.key}`;
    label.textContent = field.label;
    const unit = document.createElement("span");
    unit.className = "unit";
    unit.textContent = `（${field.unit}）`;
    label.appendChild(unit);

    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.inputMode = "decimal";
    input.id = `input-${field.key}`;
    input.dataset.key = field.key;
    input.placeholder = field.key === "age" ? "必填" : "可留空后手填";

    const tag = document.createElement("span");
    tag.className = "tag";
    tag.id = `tag-${field.key}`;

    wrap.append(label, input, tag);
    grid.appendChild(wrap);
  });
}

function fillForm(extracted, missing) {
  const missingSet = new Set(missing);
  FIELDS.forEach((field) => {
    const wrap = $("field-" + field.key);
    const input = $("input-" + field.key);
    const tag = $("tag-" + field.key);
    const item = extracted[field.key] || null;

    if (item && item.value != null) {
      input.value = item.value;
      const confidence = item.confidence != null ? Math.round(item.confidence * 100) : null;
      tag.className = "tag auto";
      tag.textContent = item.raw_text
        ? `AI 识别：${item.raw_text}${confidence != null ? `（置信度 ${confidence}%）` : ""}`
        : "AI 识别，请核对";
      wrap.classList.remove("missing");
    } else {
      input.value = "";
      tag.className = "tag manual";
      tag.textContent = "需手动填写";
      wrap.classList.toggle("missing", true);
    }
    if (field.key === "age") {
      tag.className = "tag manual";
      tag.textContent = "年龄不在报告上，请手动填写";
      wrap.classList.add("missing");
    }
    if (missingSet.has(field.key)) {
      wrap.classList.add("missing");
    }
  });
}

function collectForm() {
  const markers = {};
  for (const field of FIELDS) {
    const input = $("input-" + field.key);
    const raw = input.value.trim();
    if (raw === "") {
      throw new Error(`请填写「${field.label}」`);
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      throw new Error(`「${field.label}」必须是数字`);
    }
    markers[field.key] = value;
  }
  return markers;
}

/* ---------- 上传与识别 ---------- */
const ALLOWED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
];
const ALLOWED_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"];

function isAllowedImage(file) {
  if (ALLOWED_TYPES.includes(file.type)) return true;
  // 部分手机浏览器 / WebView 上传时 file.type 为空，按扩展名兜底
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  return ALLOWED_EXTS.includes(ext);
}

function handleFiles(fileList) {
  $("upload-error").hidden = true;
  const incoming = Array.from(fileList || []).filter(Boolean);
  if (!incoming.length) return;

  const valid = [];
  for (const file of incoming) {
    if (!isAllowedImage(file)) {
      showError(`「${file.name}」格式不支持，仅支持 jpg / png / webp / heic。`);
      continue;
    }
    if (file.size > MAX_BYTES) {
      showError(`「${file.name}」超过 10 MB。`);
      continue;
    }
    if (selectedFiles.length + valid.length >= MAX_IMAGES) {
      showError(`一次最多上传 ${MAX_IMAGES} 张照片。`);
      break;
    }
    valid.push(file);
  }
  selectedFiles = selectedFiles.concat(valid);
  renderPreviews();
  $("btn-extract").disabled = selectedFiles.length === 0;
  $("drop-text").textContent = selectedFiles.length
    ? `已选择 ${selectedFiles.length} 张照片，可继续添加或直接识别`
    : "点击选择照片（可多选），或将照片拖到这里";
}

function renderPreviews() {
  const list = $("preview-list");
  list.innerHTML = "";
  selectedFiles.forEach((file, idx) => {
    const item = document.createElement("div");
    item.className = "preview-item";

    const img = document.createElement("img");
    img.className = "preview-thumb";
    img.src = URL.createObjectURL(file);
    img.alt = `第 ${idx + 1} 张照片预览`;
    img.addEventListener("error", () => {
      // HEIC 等在部分浏览器无法解码预览，用文件名占位，不影响上传
      const fallback = document.createElement("div");
      fallback.className = "preview-fallback";
      fallback.textContent = file.name;
      img.replaceWith(fallback);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "preview-remove";
    remove.textContent = "移除";
    remove.addEventListener("click", (e) => {
      e.stopPropagation();
      selectedFiles.splice(idx, 1);
      renderPreviews();
      $("btn-extract").disabled = selectedFiles.length === 0;
      $("drop-text").textContent = selectedFiles.length
        ? `已选择 ${selectedFiles.length} 张照片，可继续添加或直接识别`
        : "点击选择照片（可多选），或将照片拖到这里";
    });

    item.append(img, remove);
    list.appendChild(item);
  });
}

function showError(msg) {
  const el = $("upload-error");
  el.textContent = msg;
  el.hidden = false;
}

async function compressImage(file) {
  // 浏览器无法解码 HEIC 时直接上传，交给后端转码
  if (file.type === "image/heic" || file.type === "image/heif") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const maxEdge = 2400;
    if (Math.max(bitmap.width, bitmap.height) <= maxEdge) {
      bitmap.close();
      return file;
    }
    const ratio = maxEdge / Math.max(bitmap.width, bitmap.height);
    const width = Math.max(1, Math.round(bitmap.width * ratio));
    const height = Math.max(1, Math.round(bitmap.height * ratio));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.88)
    );
    if (!blob || blob.size >= file.size) return file;
    const base = file.name.replace(/\.(jpe?g|png|webp)$/i, "");
    return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
  } catch (err) {
    return file;
  }
}

async function extract() {
  if (!selectedFiles.length) return;
  showStep("extracting");

  const files = await Promise.all(selectedFiles.map((f) => compressImage(f)));
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  let data;
  try {
    const resp = await fetch("/api/extract", { method: "POST", body: formData });
    data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      // 502 等错误：给出友好提示并引导用户改用手动录入
      throw new Error(data.detail || "识别失败，请稍后重试。");
    }
  } catch (err) {
    showStep("form");
    fillForm({}, FIELDS.map((f) => f.key));
    setFormError(
      `${err.message || "识别失败"} 你可以直接手动录入全部指标后计算。`
    );
    return;
  }

  fillForm(data.extracted || {}, data.missing || []);
  setFormError("");
  showStep("form");
}

function setFormError(msg) {
  const el = $("form-error");
  el.textContent = msg;
  el.hidden = !msg;
}

/* ---------- 计算与展示 ---------- */
async function calculate() {
  let markers;
  try {
    markers = collectForm();
  } catch (err) {
    setFormError(err.message);
    return;
  }

  const resp = await fetch("/api/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(markers),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.join("；") : data.detail;
    setFormError(detail || "计算失败，请检查输入。");
    return;
  }
  renderResult(data);
  showStep("result");
}

function formatGap(gap) {
  const v = Number(gap);
  if (v > 0) return `偏「老」 +${v.toFixed(1)} 岁`;
  if (v < 0) return `偏「年轻」 ${v.toFixed(1)} 岁`;
  return "与同龄人基本持平";
}

function renderResult(data) {
  $("r-pheno-age").textContent = Number(data.pheno_age).toFixed(1);
  $("r-age").textContent = `${Number(data.age).toFixed(0)} 岁`;
  $("r-gap").textContent = formatGap(data.age_gap);
  $("r-mortality").textContent = `${(Number(data.mortality_10y) * 100).toFixed(2)}%`;

  const tierText = { average: "基本持平", older: "偏「老」", younger: "偏「年轻」" }[data.tier] || "未知";
  const badge = $("r-tier");
  badge.textContent = tierText;
  badge.className = `badge ${data.tier}`;

  $("r-interpretation").textContent = data.interpretation;
  $("r-disclaimer").textContent = data.disclaimer || DISCLAIMER;
  $("r-pheno-age").dataset.gap = data.age_gap;
  $("r-pheno-age").dataset.mortality = data.mortality_10y;
  $("r-pheno-age").dataset.age = data.age;
  $("r-pheno-age").dataset.tier = tierText;
}

/* ---------- 保存结果卡片为图片（可选功能） ---------- */
function saveImage() {
  const phenoAge = $("r-pheno-age").textContent;
  const age = $("r-age").textContent;
  const gap = $("r-gap").textContent;
  const mortality = $("r-mortality").textContent;
  const tier = $("r-tier").textContent;
  const interpretation = $("r-interpretation").textContent;

  const canvas = document.createElement("canvas");
  const width = 720;
  const ctx = canvas.getContext("2d");

  const lines = [
    { text: "PhenoAge 生理年龄测算结果", size: 30, bold: true, color: "#0a626b" },
    { text: `生理年龄：${phenoAge} 岁`, size: 24, bold: true, color: "#1f2d33" },
    { text: `实际年龄：${age}`, size: 20, color: "#1f2d33" },
    { text: `差值：${gap}`, size: 20, color: "#1f2d33" },
    { text: `10 年死亡风险：${mortality}`, size: 20, color: "#1f2d33" },
    { text: `分档：${tier}`, size: 20, color: "#1f2d33" },
    { text: interpretation, size: 18, color: "#33454e" },
    { text: DISCLAIMER, size: 15, color: "#8a5a00" },
  ];

  // 先排版算出高度（免责声明等长文本需要换行）
  const margin = 48;
  let y = 36;
  const laidOut = [];
  lines.forEach((line) => {
    ctx.font = `${line.bold ? "700" : "400"} ${line.size}px "Microsoft YaHei", sans-serif`;
    const wrapped = wrapText(ctx, line.text, width - margin * 2);
    laidOut.push({ ...line, lines: wrapped });
    y += wrapped.length * (line.size + 10);
  });

  canvas.width = width;
  canvas.height = y + 40;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // 重新绘制文本
  let drawY = 56;
  laidOut.forEach((line) => {
    ctx.font = `${line.bold ? "700" : "400"} ${line.size}px "Microsoft YaHei", sans-serif`;
    ctx.fillStyle = line.color;
    line.lines.forEach((text) => {
      ctx.fillText(text, margin, drawY);
      drawY += line.size + 10;
    });
    drawY += 8;
  });

  const link = document.createElement("a");
  link.download = "phenoage-result.png";
  link.href = canvas.toDataURL("image/png");
  link.click();
}

function wrapText(ctx, text, maxWidth) {
  const chars = Array.from(text);
  const lines = [];
  let current = "";
  chars.forEach((ch) => {
    const test = current + ch;
    if (ctx.measureText(test).width > maxWidth && current) {
      lines.push(current);
      current = ch;
    } else {
      current = test;
    }
  });
  if (current) lines.push(current);
  return lines;
}

/* ---------- 事件绑定 ---------- */
$("btn-choose").addEventListener("click", () => $("file-input").click());
$("drop-zone").addEventListener("click", (e) => {
  if (e.target.closest("#preview-list") || e.target.closest("button")) return;
  $("file-input").click();
});
$("drop-zone").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") $("file-input").click();
});
$("file-input").addEventListener("change", (e) => handleFiles(e.target.files));

["dragenter", "dragover"].forEach((type) =>
  $("drop-zone").addEventListener(type, (e) => {
    e.preventDefault();
    $("drop-zone").classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((type) =>
  $("drop-zone").addEventListener(type, (e) => {
    e.preventDefault();
    $("drop-zone").classList.remove("dragover");
  })
);
$("drop-zone").addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));

$("btn-extract").addEventListener("click", extract);
$("btn-skip").addEventListener("click", () => {
  fillForm({}, FIELDS.map((f) => f.key));
  setFormError("");
  showStep("form");
});
$("btn-reupload").addEventListener("click", () => showStep("upload"));
$("btn-restart").addEventListener("click", () => {
  selectedFiles = [];
  $("file-input").value = "";
  $("preview-list").innerHTML = "";
  $("drop-text").textContent = "点击选择照片（可多选），或将照片拖到这里";
  $("btn-extract").disabled = true;
  showStep("upload");
});
$("calc-form").addEventListener("submit", (e) => {
  e.preventDefault();
  calculate();
});
$("btn-save-image").addEventListener("click", saveImage);

/* ---------- 初始化 ---------- */
buildForm();
showStep("upload");
