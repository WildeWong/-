/**
 * callsheet.js — 通告单前端逻辑
 */

// ── State ──────────────────────────────────────────────────────────
let _schedule    = null;   // ProductionSchedule dict or null
let _csIndex     = {};     // date → callsheet summary (from list_callsheets)
let _selectedDate = null;
let _currentCs   = null;   // full CallSheet dict currently in editor
let _dirty       = false;  // unsaved changes flag
let _pollTimer   = null;

// ── Init ───────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  setupResizeHandle();
  setupToolbarListeners();
  loadAll();
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeLLMDialog();
  });
});

async function loadAll() {
  setStatus("加载中...", true);
  try {
    const [schRes, csRes] = await Promise.all([
      fetch("/api/schedule"),
      fetch("/api/callsheets"),
    ]);
    _schedule = schRes.ok ? await schRes.json() : null;
    const csList = csRes.ok ? await csRes.json() : [];
    _csIndex = {};
    for (const cs of csList) _csIndex[cs.date] = cs;
    renderDayList();
    setStatus("");
  } catch (e) {
    setStatus("加载失败: " + e.message, false, true);
  }
}

// ── Toolbar ─────────────────────────────────────────────────────────

function setupToolbarListeners() {
  document.getElementById("btn-generate-cs").addEventListener("click", generateCallsheet);
  document.getElementById("btn-llm-notes").addEventListener("click", llmEnhance);
  document.getElementById("btn-export-xlsx").addEventListener("click", exportXlsx);
  document.getElementById("btn-export-pdf").addEventListener("click", exportPdf);
  document.getElementById("btn-save-cs").addEventListener("click", saveCallsheet);
  document.getElementById("btn-add-scene-row").addEventListener("click", addSceneRow);
  document.getElementById("btn-add-cast-row").addEventListener("click", addCastRow);
}

function setToolbarEnabled(hasDay) {
  document.getElementById("btn-generate-cs").disabled = !hasDay;
  document.getElementById("btn-llm-notes").disabled = !hasDay;
  document.getElementById("btn-export-xlsx").disabled = !hasDay;
  document.getElementById("btn-export-pdf").disabled = !hasDay;
  document.getElementById("btn-save-cs").disabled = !hasDay;
}

// ── Day List ────────────────────────────────────────────────────────

function renderDayList() {
  const container = document.getElementById("cs-day-list");
  const empty     = document.getElementById("cs-left-empty");

  const days = _schedule?.shooting_days;
  if (!days || days.length === 0) {
    empty.style.display = "";
    container.querySelectorAll(".cs-day-item").forEach(el => el.remove());
    document.getElementById("cs-day-count").textContent = "";
    return;
  }
  empty.style.display = "none";

  // Sort by date
  const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
  document.getElementById("cs-day-count").textContent = sorted.length + " 天";

  // Re-render (keep selection)
  container.querySelectorAll(".cs-day-item").forEach(el => el.remove());
  for (const day of sorted) {
    const hasSaved = !!_csIndex[day.date];
    const item = document.createElement("div");
    item.className = "cs-day-item" + (day.date === _selectedDate ? " selected" : "");
    item.dataset.date = day.date;
    item.innerHTML = `
      <div class="cs-day-num">D${day.day_number}</div>
      <div class="cs-day-info">
        <div class="cs-day-date">${day.date}</div>
        <div class="cs-day-meta">${day.location || "地点待定"} · ${day.scene_ids?.length ?? 0}场</div>
      </div>
      ${hasSaved ? '<span class="cs-day-saved" title="已生成通告单">✓</span>' : ""}
    `;
    item.addEventListener("click", () => selectDay(day.date));
    container.appendChild(item);
  }
}

function selectDay(date) {
  if (_dirty) {
    if (!confirm("当前通告单有未保存的修改，切换后将丢失。是否继续？")) return;
  }
  _selectedDate = date;
  _dirty = false;

  // Update selection highlight
  document.querySelectorAll(".cs-day-item").forEach(el => {
    el.classList.toggle("selected", el.dataset.date === date);
  });

  setToolbarEnabled(true);
  loadCallsheet(date);
}

// ── Callsheet Load / Render ─────────────────────────────────────────

async function loadCallsheet(date) {
  setStatus("加载通告单...", true);
  const res = await fetch(`/api/callsheets/${date}`);
  if (res.ok) {
    _currentCs = await res.json();
    renderEditor(_currentCs);
    showEditorContent(true);
    setStatus("通告单已加载");
  } else {
    _currentCs = null;
    showEditorContent(false);
    setStatus("未找到通告单，点击「从排期生成」");
  }
}

function showEditorContent(show) {
  document.getElementById("cs-editor-empty").style.display = show ? "none" : "";
  document.getElementById("cs-editor-content").style.display = show ? "" : "none";
  document.getElementById("cs-save-bar").style.display = show ? "" : "none";
}

function renderEditor(cs) {
  if (!cs) return;

  // Header
  const day = _schedule?.shooting_days?.find(d => d.date === cs.date);
  document.getElementById("cs-day-label").textContent =
    cs.date + (cs.day_number ? `  第 ${cs.day_number} 拍摄日` : "");
  document.getElementById("cs-project-name").value    = cs.project_name || "";
  document.getElementById("cs-date-field").value      = cs.date || "";
  document.getElementById("cs-director").value        = cs.director || "";
  document.getElementById("cs-producer").value        = cs.producer || "";

  // Call info
  document.getElementById("cs-crew-call").value          = cs.crew_call || "";
  document.getElementById("cs-location").value           = cs.location || "";
  document.getElementById("cs-location-address").value   = cs.location_address || "";

  // Tables
  renderScenesTable(cs.scenes || []);
  renderCastTable(cs.cast || []);

  // Props (aggregated from all scenes)
  renderPropsSection(cs.scenes || []);

  // Notes / preview
  document.getElementById("cs-general-notes").value    = cs.general_notes || "";
  document.getElementById("cs-next-day-preview").value = cs.next_day_preview || "";

  // Mark clean
  _dirty = false;
  updateSaveHint();

  // Attach change listeners to auto-mark dirty
  attachDirtyListeners();
}

function attachDirtyListeners() {
  document.querySelectorAll("#cs-editor-content input, #cs-editor-content textarea, #cs-editor-content select").forEach(el => {
    el.removeEventListener("input", markDirty);
    el.addEventListener("input", markDirty);
  });
}

function markDirty() {
  if (!_dirty) {
    _dirty = true;
    updateSaveHint();
  }
}

function updateSaveHint() {
  const hint = document.getElementById("cs-save-hint");
  if (hint) hint.textContent = _dirty ? "修改未保存" : "已保存";
}

// ── Scenes Table ─────────────────────────────────────────────────────

function renderScenesTable(scenes) {
  const tbody = document.getElementById("cs-scenes-tbody");
  tbody.innerHTML = "";
  for (const sc of scenes) tbody.appendChild(makeSceneRow(sc));
}

function makeSceneRow(sc) {
  const tr = document.createElement("tr");
  sc = sc || {};
  tr.innerHTML = `
    <td><input class="cs-td-input cs-td-num" type="number" value="${sc.scene_number ?? ""}" min="1"></td>
    <td><input class="cs-td-input" type="text" value="${esc(sc.heading)}" style="min-width:120px"></td>
    <td>
      <select class="cs-td-select">
        <option ${sc.int_ext === "INT"     ? "selected" : ""}>INT</option>
        <option ${sc.int_ext === "EXT"     ? "selected" : ""}>EXT</option>
        <option ${sc.int_ext === "INT/EXT" ? "selected" : ""}>INT/EXT</option>
      </select>
    </td>
    <td>
      <select class="cs-td-select">
        <option ${sc.time_of_day === "DAY"   ? "selected" : ""}>DAY</option>
        <option ${sc.time_of_day === "NIGHT" ? "selected" : ""}>NIGHT</option>
        <option ${sc.time_of_day === "DAWN"  ? "selected" : ""}>DAWN</option>
        <option ${sc.time_of_day === "DUSK"  ? "selected" : ""}>DUSK</option>
      </select>
    </td>
    <td><input class="cs-td-input" type="text" value="${esc((sc.cast_ids || []).join("、"))}" style="min-width:100px" placeholder="角色A、角色B"></td>
    <td><input class="cs-td-input cs-td-num" type="number" value="${sc.pages ?? 0}" step="0.1" min="0" style="width:50px"></td>
    <td><input class="cs-td-input" type="text" value="${esc(sc.notes)}" style="min-width:80px"></td>
    <td><button class="cs-row-del" onclick="this.closest('tr').remove(); markDirty()" title="删除">×</button></td>
  `;
  return tr;
}

function addSceneRow() {
  document.getElementById("cs-scenes-tbody").appendChild(makeSceneRow({}));
  markDirty();
}

// ── Cast Table ────────────────────────────────────────────────────────

function renderCastTable(cast) {
  const tbody = document.getElementById("cs-cast-tbody");
  tbody.innerHTML = "";
  for (const cc of cast) tbody.appendChild(makeCastRow(cc));
}

function makeCastRow(cc) {
  cc = cc || {};
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="cs-td-input" type="text" value="${esc(cc.character_name)}" placeholder="角色名" style="min-width:70px"></td>
    <td><input class="cs-td-input" type="text" value="${esc(cc.actor_name)}"     placeholder="演员姓名" style="min-width:70px"></td>
    <td><input class="cs-td-input cs-td-time" type="text" value="${esc(cc.makeup_time)}" placeholder="HH:MM"></td>
    <td><input class="cs-td-input cs-td-time" type="text" value="${esc(cc.call_time)}"   placeholder="HH:MM"></td>
    <td><input class="cs-td-input cs-td-time" type="text" value="${esc(cc.on_set_time)}" placeholder="HH:MM"></td>
    <td>
      <select class="cs-td-select cs-td-status">
        <option value="W" ${(cc.status || "W") === "W" ? "selected" : ""}>W</option>
        <option value="S" ${cc.status === "S" ? "selected" : ""}>S</option>
      </select>
    </td>
    <td><input class="cs-td-input" type="text" value="${esc(cc.wardrobe_notes)}" placeholder="服装备注" style="min-width:80px"></td>
    <td><button class="cs-row-del" onclick="this.closest('tr').remove(); markDirty()" title="删除">×</button></td>
  `;
  return tr;
}

function addCastRow() {
  document.getElementById("cs-cast-tbody").appendChild(makeCastRow({}));
  markDirty();
}

// ── Props Section ─────────────────────────────────────────────────────

function renderPropsSection(scenes) {
  const container = document.getElementById("cs-props-list");
  container.innerHTML = "";
  const all = new Set();
  for (const sc of scenes) for (const p of (sc.props || [])) all.add(p);
  if (all.size === 0) {
    const el = document.createElement("span");
    el.className = "cs-props-none";
    el.textContent = "无（场次中未检测到道具）";
    container.appendChild(el);
    return;
  }
  for (const p of all) {
    const chip = document.createElement("span");
    chip.className = "cs-prop-chip";
    chip.textContent = p;
    container.appendChild(chip);
  }
}

// ── Collect editor state → CallSheet dict ──────────────────────────

function collectEditor() {
  const scenes = [];
  document.querySelectorAll("#cs-scenes-tbody tr").forEach(tr => {
    const inputs  = tr.querySelectorAll(".cs-td-input");
    const selects = tr.querySelectorAll(".cs-td-select");
    const snum = parseInt(inputs[0].value) || 0;
    // Preserve original pages/props from _currentCs for scenes we recognise
    const orig = (_currentCs?.scenes || []).find(s => s.scene_number === snum) || {};
    scenes.push({
      scene_number: snum,
      heading:      inputs[1].value,
      int_ext:      selects[0]?.value || "",
      time_of_day:  selects[1]?.value || "",
      cast_ids:     inputs[2].value.split(/[,、]/).map(s => s.trim()).filter(Boolean),
      pages:        parseFloat(inputs[3].value) || 0,
      notes:        inputs[4].value,
      props:        orig.props || [],
    });
  });

  const cast = [];
  document.querySelectorAll("#cs-cast-tbody tr").forEach(tr => {
    const inputs  = tr.querySelectorAll(".cs-td-input");
    const selects = tr.querySelectorAll(".cs-td-select");
    const charName = inputs[0].value;
    const orig = (_currentCs?.cast || []).find(c => c.character_name === charName) || {};
    cast.push({
      character_name: charName,
      actor_name:     inputs[1].value,
      makeup_time:    inputs[2].value,
      call_time:      inputs[3].value,
      on_set_time:    inputs[4].value,
      status:         selects[0]?.value || "W",
      wardrobe_notes: inputs[5].value,
      scenes:         orig.scenes || [],
    });
  });

  const day = _schedule?.shooting_days?.find(d => d.date === _selectedDate);
  return {
    date:             _selectedDate || "",
    day_number:       _currentCs?.day_number || day?.day_number || 0,
    project_name:     document.getElementById("cs-project-name").value,
    director:         document.getElementById("cs-director").value,
    producer:         document.getElementById("cs-producer").value,
    crew_call:        document.getElementById("cs-crew-call").value,
    location:         document.getElementById("cs-location").value,
    location_address: document.getElementById("cs-location-address").value,
    scenes,
    cast,
    general_notes:    document.getElementById("cs-general-notes").value,
    next_day_preview: document.getElementById("cs-next-day-preview").value,
  };
}

// ── Save ──────────────────────────────────────────────────────────────

async function saveCallsheet() {
  if (!_selectedDate) return;
  const data = collectEditor();
  setStatus("保存中...", true);
  try {
    const res = await fetch(`/api/callsheets/${_selectedDate}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (res.ok) {
      _currentCs = data;
      _dirty = false;
      updateSaveHint();
      _csIndex[_selectedDate] = { date: _selectedDate, day_number: data.day_number,
        crew_call: data.crew_call, location: data.location,
        scene_count: data.scenes.length, cast_count: data.cast.length };
      renderDayList();
      setStatus("已保存");
    } else {
      const err = await res.json();
      setStatus(err.error || "保存失败", false, true);
    }
  } catch (e) {
    setStatus("保存失败: " + e.message, false, true);
  }
}

// ── Generate from schedule ────────────────────────────────────────────

async function generateCallsheet() {
  if (!_selectedDate) return;
  setStatus("生成通告单...", true);
  setBtnsDisabled(true);
  try {
    const res  = await fetch(`/api/callsheets/${_selectedDate}/generate`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      _currentCs = data;
      renderEditor(data);
      showEditorContent(true);
      _csIndex[_selectedDate] = { date: _selectedDate, day_number: data.day_number,
        crew_call: data.crew_call, location: data.location,
        scene_count: data.scenes.length, cast_count: data.cast.length };
      renderDayList();
      setStatus("通告单生成完成");
    } else {
      setStatus(data.error || "生成失败", false, true);
    }
  } catch (e) {
    setStatus("生成失败: " + e.message, false, true);
  }
  setBtnsDisabled(false);
}

// ── LLM Dialog ────────────────────────────────────────────────────────

let _llmFullText = "";

function openLLMDialog() {
  const backdrop = document.getElementById("dlg-llm-backdrop");
  backdrop.classList.remove("hidden");

  // Set subtitle from current day info
  const day = _schedule?.shooting_days?.find(d => d.date === _selectedDate);
  const subtitle = document.getElementById("dlg-llm-subtitle");
  subtitle.textContent = day
    ? `第 ${day.day_number} 拍摄日 · ${day.date} · ${day.scene_ids?.length || 0} 场`
    : (_selectedDate || "");

  // Show loading, hide others
  document.getElementById("dlg-llm-loading").style.display = "";
  document.getElementById("dlg-llm-error").style.display   = "none";
  document.getElementById("dlg-llm-result").style.display  = "none";
}

function closeLLMDialog(evt) {
  // Allow close when called directly (no evt), or when clicking the backdrop itself
  if (evt && evt.target !== document.getElementById("dlg-llm-backdrop")) return;
  document.getElementById("dlg-llm-backdrop").classList.add("hidden");
}

function setLLMDialogError(msg) {
  document.getElementById("dlg-llm-loading").style.display = "none";
  document.getElementById("dlg-llm-error").style.display   = "";
  document.getElementById("dlg-llm-error-msg").textContent  = msg;
  document.getElementById("dlg-llm-result").style.display  = "none";
}

function renderLLMResult(text) {
  _llmFullText = text;
  document.getElementById("dlg-llm-loading").style.display = "none";
  document.getElementById("dlg-llm-error").style.display   = "none";

  const resultEl = document.getElementById("dlg-llm-result");
  resultEl.style.display = "flex";

  const sections  = parseLLMSections(text);
  const container = document.getElementById("dlg-llm-sections");
  container.innerHTML = "";

  const BADGE_COLORS = {
    "特殊道具": { bg: "#fff7ed", color: "#c2410c", border: "#fed7aa" },
    "特效":     { bg: "#fef2f2", color: "#b91c1c", border: "#fecaca" },
    "特技":     { bg: "#fef2f2", color: "#b91c1c", border: "#fecaca" },
    "群演":     { bg: "#f5f3ff", color: "#7c3aed", border: "#ddd6fe" },
    "动物":     { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
    "儿童":     { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
    "许可证":   { bg: "#fefce8", color: "#854d0e", border: "#fef08a" },
    "情绪":     { bg: "#fff1f2", color: "#9f1239", border: "#fda4af" },
    "连续性":   { bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe" },
    "其他":     { bg: "#f8fafc", color: "#475569", border: "#e2e8f0" },
  };

  sections.forEach((sec, i) => {
    const id  = "llm-sec-" + i;
    const col = Object.entries(BADGE_COLORS).find(([k]) => sec.title.includes(k))?.[1]
                || BADGE_COLORS["其他"];
    const div = document.createElement("div");
    div.className = "cs-llm-section";
    div.innerHTML = `
      <div class="cs-llm-section-header" onclick="toggleSection('${id}')">
        <input type="checkbox" class="cs-llm-section-check" id="chk-${id}" checked
               onclick="event.stopPropagation(); updateSelectAll()">
        <span class="cs-llm-badge"
              style="background:${col.bg};color:${col.color};border:1px solid ${col.border}">
          ${esc(sec.title)}
        </span>
        <span class="cs-llm-section-title">${esc(sec.preview)}</span>
        <span class="cs-llm-toggle" id="tog-${id}">▾</span>
      </div>
      <div class="cs-llm-section-body" id="body-${id}">${esc(sec.content)}</div>
    `;
    container.appendChild(div);
  });

  document.getElementById("dlg-llm-select-all").checked       = true;
  document.getElementById("dlg-llm-select-all").indeterminate = false;
}

function parseLLMSections(text) {
  // Split on 【...】 pattern (with optional surrounding ** markers)
  const parts = text.split(/\*{0,2}【([^】]+)】\*{0,2}/);
  const sections = [];
  // parts = [preamble, title1, content1, title2, content2, ...]
  for (let i = 1; i < parts.length; i += 2) {
    const title   = parts[i].trim();
    const content = (parts[i + 1] || "").trim();
    if (!title) continue;
    // First line of content as preview (truncated)
    const firstLine = content.split("\n")[0].replace(/^[-•·\s]+/, "").trim();
    const preview   = firstLine.length > 40 ? firstLine.slice(0, 40) + "…" : firstLine;
    sections.push({ title, content, preview, raw: `【${title}】\n${content}` });
  }
  // Fallback: no 【】 markers found — treat entire text as one block
  if (sections.length === 0 && text.trim()) {
    sections.push({ title: "AI 建议", content: text.trim(), preview: "", raw: text.trim() });
  }
  return sections;
}

function toggleSection(id) {
  const body = document.getElementById("body-" + id);
  const tog  = document.getElementById("tog-"  + id);
  if (!body) return;
  const collapsed = body.style.display === "none";
  body.style.display = collapsed ? "" : "none";
  if (tog) tog.textContent = collapsed ? "▾" : "▸";
}

function toggleSelectAll(checked) {
  document.querySelectorAll(".cs-llm-section-check").forEach(cb => { cb.checked = checked; });
}

function updateSelectAll() {
  const all  = [...document.querySelectorAll(".cs-llm-section-check")];
  const saEl = document.getElementById("dlg-llm-select-all");
  const checked = all.filter(cb => cb.checked).length;
  saEl.checked       = checked === all.length;
  saEl.indeterminate = checked > 0 && checked < all.length;
}

function applySelectedSections() {
  const checks   = [...document.querySelectorAll(".cs-llm-section-check")];
  const sections = parseLLMSections(_llmFullText);
  const selected = [];
  checks.forEach((cb, idx) => {
    if (cb.checked && sections[idx]) selected.push(sections[idx].raw);
  });
  if (selected.length === 0) {
    setStatus("请至少勾选一个条目", false, true);
    return;
  }
  const el     = document.getElementById("cs-general-notes");
  const prefix = el.value ? "\n\n── AI 生成注意事项 ──\n" : "";
  el.value    += prefix + selected.join("\n\n");
  markDirty();
  closeLLMDialog();
  setStatus(`已追加 ${selected.length} 个条目到备注`);
}

function copyLLMResult() {
  if (!_llmFullText) return;
  navigator.clipboard.writeText(_llmFullText).then(() => {
    const btn  = document.getElementById("dlg-btn-copy");
    const orig = btn.textContent;
    btn.textContent = "已复制 ✓";
    setTimeout(() => { btn.textContent = orig; }, 1800);
  }).catch(() => setStatus("复制失败（请手动复制）", false, true));
}

// ── LLM Enhance ───────────────────────────────────────────────────────

async function llmEnhance() {
  if (!_selectedDate) return;

  openLLMDialog();
  setBtnsDisabled(true);
  setStatus("AI 分析场次内容...", true);

  try {
    const res  = await fetch(`/api/callsheets/${_selectedDate}/llm/notes`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setLLMDialogError(data.error || "请求失败，请检查 LLM 配置");
      setStatus(data.error || "请求失败", false, true);
      setBtnsDisabled(false);
      return;
    }
  } catch (e) {
    setLLMDialogError("网络错误：" + e.message);
    setStatus("请求失败: " + e.message, false, true);
    setBtnsDisabled(false);
    return;
  }

  startPolling("AI 分析完成", result => {
    renderLLMResult(result);
    setStatus("AI 分析完成");
    setBtnsDisabled(false);
  }, errMsg => {
    setLLMDialogError(errMsg || "AI 分析失败");
    setBtnsDisabled(false);
  });
}

function startPolling(doneMsg, onDone, onError) {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/llm/status");
      const d   = await res.json();
      if (d.status === "done") {
        clearInterval(_pollTimer); _pollTimer = null;
        setStatus(doneMsg, false);
        if (onDone) onDone(d.result || d.text || "");
      } else if (d.status === "error") {
        clearInterval(_pollTimer); _pollTimer = null;
        const errMsg = d.error || "执行失败";
        setStatus(errMsg, false, true);
        if (onError) onError(errMsg);
      }
    } catch (_) {}
  }, 1500);
}

// ── Export ────────────────────────────────────────────────────────────

function exportXlsx() {
  if (!_selectedDate) return;
  window.location = `/api/callsheets/${_selectedDate}/export/xlsx`;
}

function exportPdf() {
  if (!_selectedDate) return;
  window.open(`/api/callsheets/${_selectedDate}/export/pdf`, "_blank");
}

// ── Resize handle ─────────────────────────────────────────────────────

function setupResizeHandle() {
  const handle = document.getElementById("cs-resize");
  const left   = document.getElementById("cs-left");
  if (!handle || !left) return;

  let dragging = false;
  let startX   = 0;
  let startW   = 0;

  handle.addEventListener("mousedown", e => {
    dragging = true;
    startX   = e.clientX;
    startW   = left.getBoundingClientRect().width;
    handle.classList.add("active");
    e.preventDefault();
  });
  document.addEventListener("mousemove", e => {
    if (!dragging) return;
    const w = Math.max(140, Math.min(480, startW + e.clientX - startX));
    left.style.width = w + "px";
  });
  document.addEventListener("mouseup", () => {
    if (dragging) { dragging = false; handle.classList.remove("active"); }
  });
}

// ── Helpers ───────────────────────────────────────────────────────────

function esc(v) {
  if (!v) return "";
  return String(v).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function setStatus(msg, spinning = false, isError = false) {
  const txt  = document.getElementById("cs-toolbar-status-text");
  const spin = document.getElementById("cs-toolbar-spinner");
  const bar  = document.getElementById("cs-statusbar-text");
  if (txt)  { txt.textContent = msg; txt.parentElement.classList.toggle("is-error", isError); }
  if (spin) spin.style.display = spinning ? "" : "none";
  if (bar)  { bar.textContent = msg; bar.classList.toggle("is-error", isError); }
}

function setBtnsDisabled(disabled) {
  ["btn-generate-cs","btn-llm-notes","btn-export-xlsx","btn-export-pdf","btn-save-cs"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled || !_selectedDate;
  });
}
