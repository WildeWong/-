/* schedule.js — 排期管理前端逻辑 */
'use strict';

// ── State ─────────────────────────────────────────────────────────
let _schedule   = null;   // ProductionSchedule dict (from /api/schedule)
let _conflicts  = [];     // violation objects (from /api/schedule/conflicts)
let _snapshots  = [];     // snapshot metadata list
let _appState   = null;   // from /api/scenes/global (global scene numbering, aligns with schedule scene_ids)
let _sceneMap   = {};     // scene_number -> scene dict
let _entityMap  = {};     // scene_number (int/str) -> {characters, props}
let _selectedDate = null; // currently selected day date string
let _pollTimer  = null;   // setInterval handle for async task polling
let _pendingChangeType = null;   // for reschedule dialog

// AI / learning state
let _llmSuggestionDates = new Set(); // dates where LLM found unaccepted suggestions
let _learnedRules = [];              // learned structural rules (from /api/schedule/learned-preferences)
let _learnedRuleDates = new Set();   // dates whose scene_ids are covered by learned rules

// Filters
let _filterText = '';
let _filterLoc  = '';
let _filterChar = '';

// ── Helpers ───────────────────────────────────────────────────────
function esc(s) {
  const d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}

function q(id)  { return document.getElementById(id); }

function toast(msg, duration = 2500) {
  const el = q('sch-toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._tid);
  el._tid = setTimeout(() => el.classList.remove('show'), duration);
}

function setStatus(msg, spinning = false) {
  q('sb-text').textContent = msg;
  q('toolbar-status-text').textContent = spinning ? msg : '';
  q('toolbar-spinner').style.display = spinning ? '' : 'none';
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];
function fmtDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T12:00:00');
  return `${dateStr} 周${WEEKDAYS[d.getDay()]}`;
}

function statusLabel(s) {
  return {planned:'计划中', shooting:'拍摄中', completed:'已完成', cancelled:'已取消'}[s] || '计划中';
}

// Build set of scheduled scene IDs from current schedule
function scheduledSceneIds() {
  const ids = new Set();
  if (!_schedule || !_schedule.shooting_days) return ids;
  _schedule.shooting_days.forEach(day => (day.scene_ids || []).forEach(id => ids.add(id)));
  return ids;
}

// Collect actors/props for a list of scene IDs
function entitiesForScenes(sceneIds) {
  const actors = new Set(), props = new Set();
  (sceneIds || []).forEach(sid => {
    const ent = _entityMap[sid] || _entityMap[String(sid)] || {};
    (ent.characters || []).forEach(c => actors.add(c));
    (ent.props || []).forEach(p => props.add(p));
  });
  return { actors: [...actors], props: [...props] };
}

// Primary location for a day (most frequent among its scenes)
function primaryLocation(day) {
  if (day.location) return day.location;
  const counts = {};
  (day.scene_ids || []).forEach(sid => {
    const sc = _sceneMap[sid] || _sceneMap[String(sid)];
    if (sc && sc.location) counts[sc.location] = (counts[sc.location] || 0) + 1;
  });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  return top ? top[0] : '';
}

// Conflicts for a given date
function conflictsForDate(dateStr) {
  return _conflicts.filter(c => c.day_date === dateStr);
}

// ── Boot ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupResizeHandles();
  setupDropdowns();
  setupToolbar();
  setupDetailPanel();
  setupDialogs();
  loadAll();
});

// ── Data loading ──────────────────────────────────────────────────
async function loadAll() {
  setStatus('加载中...', true);
  try {
    const [schedResp, conflictsResp, scenesResp] = await Promise.all([
      fetch('/api/schedule'),
      fetch('/api/schedule/conflicts'),
      fetch('/api/scenes/global'),
    ]);
    if (schedResp.ok) {
      const data = await schedResp.json();
      _schedule = data;
    }
    if (conflictsResp.ok) {
      _conflicts = await conflictsResp.json();
    }
    if (scenesResp.ok) {
      _appState = await scenesResp.json();
      buildMaps();
    }
    await loadSnapshots();
    // Silently load learned rules for card badge computation
    try {
      const pr = await fetch('/api/schedule/learned-preferences');
      if (pr.ok) {
        const pd = await pr.json();
        _learnedRules = pd.rules || [];
        _computeLearnedRuleDates();
      }
    } catch (_) {}
    render();
    setStatus('就绪');
  } catch (e) {
    setStatus('加载失败: ' + e.message);
  }
}

async function loadSnapshots() {
  try {
    const r = await fetch('/api/schedule/snapshots');
    if (r.ok) _snapshots = await r.json();
  } catch (_) {}
}

function buildMaps() {
  _sceneMap  = {};
  _entityMap = {};
  if (!_appState) return;
  (_appState.scenes || []).forEach(s => {
    _sceneMap[s.scene_number] = s;
    _sceneMap[String(s.scene_number)] = s;
  });
  const raw = _appState.entities || {};
  Object.entries(raw).forEach(([k, v]) => {
    _entityMap[parseInt(k)] = v;
    _entityMap[k] = v;
  });
}

// ── Warnings banner ───────────────────────────────────────────────
function _renderWarningsBanner(warnings) {
  const CENTER_ID = 'sch-center';
  const BANNER_ID = 'sch-warnings-banner';
  let banner = q(BANNER_ID);
  if (!warnings || warnings.length === 0) {
    if (banner) banner.style.display = 'none';
    return;
  }
  if (!banner) {
    banner = document.createElement('div');
    banner.id = BANNER_ID;
    banner.style.cssText = [
      'background:#fef3c7',
      'border:1px solid #f59e0b',
      'border-radius:6px',
      'padding:10px 14px',
      'margin:8px 0 10px',
      'font-size:13px',
      'line-height:1.6',
    ].join(';');
    const center = q(CENTER_ID);
    const daysContainer = q('days-container');
    if (center && daysContainer) {
      center.insertBefore(banner, daysContainer);
    }
  }
  banner.style.display = '';
  banner.innerHTML = warnings.map(w => `<div>⚠ ${esc(w)}</div>`).join('');
}

// ── Render ────────────────────────────────────────────────────────
function render() {
  renderLeftPanel();
  renderCenterPanel();
  if (_selectedDate) renderDetailPanel(_selectedDate);
  updateToolbarState();
}

// ── Left panel ────────────────────────────────────────────────────
function renderLeftPanel() {
  populateFilterDropdowns();
  applyFilters();
}

function populateFilterDropdowns() {
  const scenes = _appState ? (_appState.scenes || []) : [];
  const locs = [...new Set(scenes.map(s => s.location).filter(Boolean))].sort();
  const locSel = q('filter-location');
  const cur = locSel.value;
  locSel.innerHTML = '<option value="">全部地点</option>' +
    locs.map(l => `<option value="${esc(l)}"${l === cur ? ' selected' : ''}>${esc(l)}</option>`).join('');

  const chars = new Set();
  Object.values(_entityMap).forEach(ent => (ent.characters || []).forEach(c => chars.add(c)));
  const charSel = q('filter-character');
  const curC = charSel.value;
  charSel.innerHTML = '<option value="">全部人物</option>' +
    [...chars].sort().map(c => `<option value="${esc(c)}"${c === curC ? ' selected' : ''}>${esc(c)}</option>`).join('');
}

function applyFilters() {
  const scenes = _appState ? (_appState.scenes || []) : [];
  const scheduled = scheduledSceneIds();
  const container = q('unscheduled-list');

  if (scenes.length === 0) {
    container.innerHTML = '<div class="sch-left-empty">暂无场次数据<br>请先在主界面导入剧本</div>';
    q('scene-list-count').textContent = '';
    return;
  }

  let visible = 0;
  container.innerHTML = '';
  scenes.forEach(s => {
    // Filter matching
    const matchText = !_filterText ||
      String(s.scene_number).includes(_filterText) ||
      (s.heading || '').toLowerCase().includes(_filterText.toLowerCase()) ||
      (s.location || '').toLowerCase().includes(_filterText.toLowerCase());
    const matchLoc = !_filterLoc || s.location === _filterLoc;
    const matchChar = !_filterChar || (() => {
      const ent = _entityMap[s.scene_number] || _entityMap[String(s.scene_number)] || {};
      return (ent.characters || []).includes(_filterChar);
    })();

    if (!matchText || !matchLoc || !matchChar) return;
    visible++;

    const isScheduled = scheduled.has(s.scene_number);
    const div = document.createElement('div');
    div.className = 'sch-scene-item' + (isScheduled ? ' is-scheduled' : '');
    div.dataset.sceneNum = s.scene_number;
    div.innerHTML = `
      <span class="sch-num-badge">${s.scene_number}</span>
      <div class="sch-scene-info">
        <div class="sch-scene-heading">${esc(s.heading || '(无标题)')}</div>
        <div class="sch-scene-meta">${esc([s.int_ext, s.location, s.time_of_day].filter(Boolean).join(' · '))}</div>
      </div>
    `;
    if (!isScheduled) {
      div.title = '点击添加到拍摄日';
      div.addEventListener('click', () => openAddSceneDialog(s.scene_number));
    }
    container.appendChild(div);
  });

  const total = scenes.length;
  const inSched = [...scheduled].filter(id => scenes.some(s => s.scene_number === id)).length;
  q('scene-list-count').textContent = `已排 ${inSched}/${total}`;
}

// ── Center panel ──────────────────────────────────────────────────
function renderCenterPanel() {
  const container = q('days-container');
  const emptyEl   = q('days-empty');

  if (!_schedule || !_schedule.shooting_days || _schedule.shooting_days.length === 0) {
    container.innerHTML = '';
    container.appendChild(emptyEl || (() => {
      const el = document.createElement('div');
      el.className = 'sch-days-empty';
      el.innerHTML = '暂无排期数据<br><span style="font-size:12px">点击「自动排期」按钮生成初始排期</span>';
      return el;
    })());
    q('sch-center-meta').textContent = '';
    return;
  }

  const conflictDates = new Set(_conflicts.map(c => c.day_date));
  container.innerHTML = '';
  _schedule.shooting_days.forEach((day, idx) => {
    const card = buildDayCard(day, idx + 1, conflictDates.has(day.date));
    container.appendChild(card);
  });

  const days = _schedule.shooting_days.length;
  const total = _schedule.shooting_days.reduce((s, d) => s + (d.scene_ids || []).length, 0);
  q('sch-center-meta').textContent =
    `共 ${days} 个拍摄日 · ${total} 场次` +
    (_schedule.start_date ? ` · ${_schedule.start_date} 开机` : '') +
    (_schedule.end_date   ? ` → ${_schedule.end_date}` : '');
}

function buildDayCard(day, dayNum, hasConflict) {
  const { actors } = entitiesForScenes(day.scene_ids);
  const loc = primaryLocation(day);
  const status = day.status || 'planned';

  const dateWeek = fmtDate(day.date);
  const sceneCount = (day.scene_ids || []).length;

  const conflictScenes = new Set(
    _conflicts.filter(c => c.day_date === day.date).flatMap(c => c.scene_ids || [])
  );

  const sceneTags = (day.scene_ids || []).map(sid => {
    const sc = _sceneMap[sid] || _sceneMap[String(sid)];
    const locAbbr = sc ? (sc.location || '').slice(0, 6) : '';
    const cls = conflictScenes.has(sid) ? ' conflict-tag' : '';
    return `<span class="sch-stag${cls}" title="${esc(sc ? sc.heading : '')}">${esc(sid)}${locAbbr ? ' · ' + esc(locAbbr) : ''}</span>`;
  }).join('') || '<span class="sch-stag-none">暂无场次</span>';

  const card = document.createElement('div');
  card.className = [
    'sch-day-card',
    hasConflict  ? 'has-conflict' : '',
    _selectedDate === day.date ? 'selected' : '',
    'st-' + status,
  ].filter(Boolean).join(' ');
  card.dataset.date = day.date;

  const llmBadge  = _llmSuggestionDates.has(day.date)
    ? '<span class="card-badge badge-warn" title="LLM 曾对本日提出改进建议（未完全采纳）">!</span>' : '';
  const ruleBadge = _learnedRuleDates.has(day.date)
    ? '<span class="card-badge badge-rule" title="有已学习规则约束本日场次">≡</span>' : '';

  card.innerHTML = `
    <div class="sch-card-header">
      <span class="sch-card-daynum">第 ${dayNum} 天</span>
      <span class="sch-card-date">${esc(dateWeek)}</span>
      <span class="sch-card-status ${status}">${statusLabel(status)}</span>
      ${llmBadge}${ruleBadge}
    </div>
    <div class="sch-card-meta">
      <span class="sch-card-loc">${loc ? '📍 ' + esc(loc) : ''}</span>
      <span class="sch-card-cnt">${sceneCount} 场</span>
    </div>
    <div class="sch-card-scenes">${sceneTags}</div>
    ${actors.length > 0 ? `<div class="sch-card-actors">👤 ${esc(actors.slice(0,5).join(' / '))}${actors.length > 5 ? ` +${actors.length - 5}` : ''}</div>` : ''}
    ${hasConflict ? '<div class="sch-conflict-row">⚠ 存在冲突</div>' : ''}
  `;
  card.addEventListener('click', () => selectDay(day.date));
  return card;
}

// ── Select a day ──────────────────────────────────────────────────
function selectDay(dateStr) {
  _selectedDate = dateStr;
  // Update card highlights
  document.querySelectorAll('.sch-day-card').forEach(c => {
    c.classList.toggle('selected', c.dataset.date === dateStr);
  });
  renderDetailPanel(dateStr);
}

// ── Right panel — detail ──────────────────────────────────────────
function renderDetailPanel(dateStr) {
  if (!_schedule) return;
  const day = (_schedule.shooting_days || []).find(d => d.date === dateStr);
  if (!day) {
    q('detail-placeholder').style.display = '';
    q('detail-content').style.display = 'none';
    return;
  }

  q('detail-placeholder').style.display = 'none';
  q('detail-content').style.display = '';

  const dayIdx = (_schedule.shooting_days || []).indexOf(day);
  q('d-date').textContent = `第 ${dayIdx + 1} 天 · ${fmtDate(day.date)}`;
  q('d-status').value     = day.status || 'planned';
  q('d-call-time').value  = day.call_time || '';
  q('d-est-end').value    = day.estimated_end || '';
  q('d-location').value   = day.location || '';
  q('d-notes').value      = day.notes || '';
  q('d-weather').value    = day.weather_backup || '';

  // Scene list
  const sceneList = q('d-scenes-list');
  sceneList.innerHTML = '';
  q('d-scene-count').textContent = `${(day.scene_ids || []).length} 场`;
  (day.scene_ids || []).forEach(sid => {
    const sc = _sceneMap[sid] || _sceneMap[String(sid)];
    const row = document.createElement('div');
    row.className = 'sch-detail-scene-row';
    row.innerHTML = `
      <span class="sch-detail-num">${esc(sid)}</span>
      <div class="sch-detail-scene-info">
        <div class="sch-detail-heading">${esc(sc ? (sc.heading || '(无标题)') : `场次 ${sid}`)}</div>
        ${sc ? `<div class="sch-detail-loc">${esc([sc.int_ext, sc.location, sc.time_of_day].filter(Boolean).join(' · '))}</div>` : ''}
      </div>
      <button class="sch-rm-btn" data-sid="${sid}" title="查看时长/类型详情" style="border-color:#93c5fd;color:#1d4ed8;margin-right:2px">详情</button>
      <button class="sch-rm-btn" data-sid="${sid}" data-action="remove" title="从本日移除">移除</button>
    `;
    row.querySelectorAll('.sch-rm-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const s = parseInt(e.target.dataset.sid);
        if (e.target.dataset.action === 'remove') {
          removeSceneFromDay(dateStr, s);
        } else {
          openSceneDetailDialog(s);
        }
      });
    });
    sceneList.appendChild(row);
  });

  // Actors / props
  const { actors, props } = entitiesForScenes(day.scene_ids);
  q('d-actors').innerHTML = actors.length
    ? actors.map(a => `<span class="sch-chip">${esc(a)}</span>`).join('')
    : '<span class="sch-chip-empty">暂无</span>';
  q('d-props').innerHTML = props.length
    ? props.map(p => `<span class="sch-chip prop">${esc(p)}</span>`).join('')
    : '<span class="sch-chip-empty">暂无</span>';

  // Conflicts
  const dayConflicts = conflictsForDate(dateStr);
  if (dayConflicts.length > 0) {
    q('d-conflicts-wrap').style.display = '';
    q('d-conflicts').innerHTML = dayConflicts.map(c => `
      <div class="sch-conflict-item${c.severity === 'warning' ? ' warn' : ''}">
        <strong>${esc(c.type)}</strong>: ${esc(c.message)}
      </div>
    `).join('');
  } else {
    q('d-conflicts-wrap').style.display = 'none';
  }
}

// ── Toolbar state ─────────────────────────────────────────────────
function updateToolbarState() {
  const hasSchedule = _schedule && (_schedule.shooting_days || []).length > 0;
  q('btn-llm-loop').disabled   = !hasSchedule;
  q('btn-conflicts').disabled  = !hasSchedule;
  q('btn-reschedule').disabled = !hasSchedule;
  q('btn-contingency').disabled = !hasSchedule;
}

// ── API calls ─────────────────────────────────────────────────────
async function generateSchedule(params) {
  setStatus('生成排期中...', true);
  // After 5 s show a longer-wait hint (CP-SAT may take up to 10 s)
  const longWaitTimer = setTimeout(() => {
    setStatus('CP-SAT 搜索最优解中，最长 10 秒...', true);
  }, 5000);
  try {
    const resp = await fetch('/api/schedule/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(params),
    });
    clearTimeout(longWaitTimer);
    const data = await resp.json();
    if (!resp.ok) { toast('生成失败: ' + (data.error || '未知错误')); setStatus('生成失败'); return; }
    _schedule = data;
    _conflicts = [];
    _selectedDate = null;
    _llmSuggestionDates.clear();     // reset LLM badges on new schedule
    _computeLearnedRuleDates();
    render();
    _renderWarningsBanner(data.warnings);
    setStatus(`已生成 ${(_schedule.shooting_days || []).length} 个拍摄日`);
    if (data.warnings && data.warnings.length > 0) {
      toast('⚠ 排期含数据清洗警告，请查看顶部提示', 8000);
    } else if (data.warning) {
      toast('⚠ ' + data.warning, 8000);
    } else {
      toast('排期生成完成');
    }
  } catch (e) {
    clearTimeout(longWaitTimer);
    setStatus('生成失败: ' + e.message);
    toast('网络错误: ' + e.message);
  }
}

async function optimizeSchedule() {
  if (_pollTimer) return;
  setStatus('优化排期中...', true);
  try {
    const resp = await fetch('/api/schedule/optimize', { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) { toast('优化失败: ' + (data.error || '')); setStatus('优化失败'); return; }
    startPolling('优化完成', null, null);
  } catch (e) {
    toast('网络错误: ' + e.message);
    setStatus('优化失败');
  }
}

async function runLLMLoop() {
  if (_pollTimer) { toast('已有任务运行中'); return; }
  setStatus('启动 LLM 智能推演...', true);
  q('btn-llm-loop').disabled = true;
  try {
    const resp = await fetch('/api/schedule/llm-loop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ time_limit: 15, max_rounds: 3 }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      toast('推演启动失败: ' + (data.error || ''));
      setStatus('推演失败');
      q('btn-llm-loop').disabled = false;
      return;
    }
    // Show elapsed seconds during polling (round count not available from status endpoint)
    const startTime = Date.now();
    const statusTimer = setInterval(() => {
      const s = Math.round((Date.now() - startTime) / 1000);
      setStatus(`LLM 推演中 (${s}s, 最多 3 轮)...`, true);
    }, 1000);
    startPolling(
      'LLM 推演完成',
      () => { clearInterval(statusTimer); q('btn-llm-loop').disabled = false; },
      (result) => showLLMLoopResult(result),
    );
  } catch (e) {
    toast('网络错误: ' + e.message);
    setStatus('推演失败');
    q('btn-llm-loop').disabled = false;
  }
}

function showLLMLoopResult(result) {
  if (!result) return;
  const rounds = result.rounds || [];

  // Mark all days with yellow ! if any round had unaccepted suggestions
  _llmSuggestionDates.clear();
  const hasUnaccepted = rounds.some(r =>
    (r.llm_suggestions || []).length > (r.accepted || []).length
  );
  if (hasUnaccepted && _schedule && _schedule.shooting_days) {
    _schedule.shooting_days.forEach(d => _llmSuggestionDates.add(d.date));
  }

  const score = typeof result.final_score === 'number' ? result.final_score.toFixed(1) : '--';
  let html = `<div class="llm-result-summary">
    共 <b>${result.total_rounds || 0}</b> 轮推演 &nbsp;·&nbsp; 最终评分 <b>${score}</b>（越低越优）
  </div>`;
  if (result.warning) {
    html += `<div class="gen-learned-hint" style="margin-bottom:12px">⚠ ${esc(result.warning)}</div>`;
  }

  if (rounds.length === 0) {
    html += '<p class="llm-sugg-empty" style="text-align:center;padding:20px">暂无推演记录</p>';
  } else {
    rounds.forEach(r => {
      const suggestions = r.llm_suggestions || [];
      const accepted = r.accepted || [];
      const solverOk = r.solver_status !== 'infeasible';
      html += `<div class="llm-round-card">
        <div class="llm-round-hdr">
          <span class="llm-round-label">第 ${r.round} 轮</span>
          <span class="llm-round-stat ${solverOk ? 'ok' : 'err'}">${r.solver_status || ''}</span>
          ${accepted.length ? `<span class="llm-round-accepted">+${accepted.length} 约束</span>` : ''}
        </div>
        ${suggestions.length
          ? `<ul class="llm-sugg-list">${suggestions.map(s => `<li>${esc(s)}</li>`).join('')}</ul>`
          : '<p class="llm-sugg-empty">LLM 认为排期已合理，无需调整</p>'
        }
        ${accepted.length
          ? `<div class="llm-constraints">采纳约束: ${accepted.map(a => `<code>${esc(a)}</code>`).join(' ')}</div>`
          : ''
        }
      </div>`;
    });
  }

  q('llm-loop-result').innerHTML = html;
  q('dlg-llm-title').textContent = `LLM 智能推演完成 — ${result.total_rounds || 0} 轮`;
  openDialog('dlg-llm-loop');
  renderCenterPanel(); // re-render cards to show/hide badges
}

// onResult(result): called instead of showDiff when present
// pass onResult=null to keep the old showDiff behaviour
function startPolling(doneMsg, onDone, onResult) {
  _pollTimer = setInterval(async () => {
    try {
      const r = await fetch('/api/llm/status');
      if (!r.ok) return;
      const d = await r.json();
      if (d.status === 'done') {
        stopPolling();
        // Reload schedule & conflicts
        const sr = await fetch('/api/schedule');
        if (sr.ok) _schedule = await sr.json();
        const cr = await fetch('/api/schedule/conflicts');
        if (cr.ok) _conflicts = await cr.json();
        _computeLearnedRuleDates();
        render();
        setStatus(doneMsg);
        const relaxWarn = d.result && d.result.warning;
        if (relaxWarn) {
          toast('⚠ ' + relaxWarn, 8000);
        } else {
          toast(doneMsg);
        }
        if (onResult && d.result !== undefined) onResult(d.result);
        else if (!onResult && d.result) showDiff(d.result);
        if (onDone) onDone();
      } else if (d.status === 'error') {
        stopPolling();
        setStatus('任务失败: ' + d.error);
        toast('任务失败: ' + d.error, 4000);
        if (onDone) onDone();
      }
    } catch (_) {}
  }, 1500);
}

// Like startPolling but does NOT reload the schedule (analysis-only tasks)
function startLLMTextPolling(doneMsg, onResult, onDone) {
  _pollTimer = setInterval(async () => {
    try {
      const r = await fetch('/api/llm/status');
      if (!r.ok) return;
      const d = await r.json();
      if (d.status === 'done') {
        stopPolling();
        setStatus(doneMsg);
        if (onResult) onResult(d.result, null);
        if (onDone) onDone();
      } else if (d.status === 'error') {
        stopPolling();
        setStatus('失败: ' + d.error);
        toast('失败: ' + d.error, 4000);
        if (onResult) onResult(null, d.error);
        if (onDone) onDone();
      }
    } catch (_) {}
  }, 1500);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

async function checkConflicts() {
  setStatus('检测冲突中...', true);
  try {
    const r = await fetch('/api/schedule/conflicts');
    if (!r.ok) { setStatus('检测失败'); return; }
    _conflicts = await r.json();
    render();
    if (_conflicts.length === 0) {
      toast('未发现冲突 ✓');
      setStatus('无冲突');
    } else {
      toast(`发现 ${_conflicts.length} 个冲突`);
      setStatus(`发现 ${_conflicts.length} 个冲突`);
    }
  } catch (e) {
    setStatus('检测失败: ' + e.message);
  }
}

async function doReschedule(changeType, changeData) {
  if (_pollTimer) { toast('已有任务运行中'); return; }
  setStatus('动态调整中...', true);
  q('btn-reschedule').disabled = true;
  try {
    const resp = await fetch('/api/schedule/reschedule', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ change_type: changeType, change_data: changeData }),
    });
    const data = await resp.json();
    if (!resp.ok) { toast('调整失败: ' + (data.error || '')); setStatus('调整失败'); q('btn-reschedule').disabled = false; return; }
    startPolling('调整完成', () => { q('btn-reschedule').disabled = false; });
  } catch (e) {
    toast('网络错误: ' + e.message);
    setStatus('调整失败');
    q('btn-reschedule').disabled = false;
  }
}

async function saveDay(dateStr) {
  const data = {
    status:           q('d-status').value,
    call_time:        q('d-call-time').value.trim(),
    estimated_end:    q('d-est-end').value.trim(),
    location:         q('d-location').value.trim(),
    notes:            q('d-notes').value.trim(),
    weather_backup:   q('d-weather').value.trim(),
  };
  try {
    const r = await fetch(`/api/schedule/days/${dateStr}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    if (!r.ok) { const e = await r.json(); toast('保存失败: ' + (e.error || '')); return; }
    const updated = await r.json();
    // Update local state
    const day = (_schedule.shooting_days || []).find(d => d.date === dateStr);
    if (day) Object.assign(day, updated);
    renderCenterPanel();
    renderDetailPanel(dateStr);
    toast('已保存');
  } catch (e) {
    toast('网络错误: ' + e.message);
  }
}

async function addSceneToDay(dateStr, sceneId) {
  try {
    const r = await fetch(`/api/schedule/days/${dateStr}/add_scene`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ scene_id: sceneId }),
    });
    if (!r.ok) { const e = await r.json(); toast('添加失败: ' + (e.error || '')); return; }
    const updated = await r.json();
    const day = (_schedule.shooting_days || []).find(d => d.date === dateStr);
    if (day) Object.assign(day, updated);
    render();
    if (_selectedDate === dateStr) renderDetailPanel(dateStr);
    toast('场次已添加');
  } catch (e) {
    toast('网络错误: ' + e.message);
  }
}

async function removeSceneFromDay(dateStr, sceneId) {
  try {
    const r = await fetch(`/api/schedule/days/${dateStr}/remove_scene`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ scene_id: sceneId }),
    });
    if (!r.ok) { const e = await r.json(); toast('移除失败: ' + (e.error || '')); return; }
    const updated = await r.json();
    const day = (_schedule.shooting_days || []).find(d => d.date === dateStr);
    if (day) Object.assign(day, updated);
    render();
    renderDetailPanel(dateStr);
    toast('场次已移除');
  } catch (e) {
    toast('网络错误: ' + e.message);
  }
}

async function restoreSnapshot(version) {
  if (!confirm(`确认将排期回滚到版本 v${version}？当前排期会先存为快照。`)) return;
  setStatus('回滚中...', true);
  try {
    const r = await fetch(`/api/schedule/snapshots/${version}/restore`, { method: 'POST' });
    if (!r.ok) { const e = await r.json(); toast('回滚失败: ' + (e.error || '')); setStatus('回滚失败'); return; }
    _schedule = await r.json();
    await loadSnapshots();
    render();
    setStatus(`已回滚到版本 v${version}`);
    toast(`已回滚到版本 v${version}`);
    closeDialog('dlg-snapshots');
  } catch (e) {
    toast('网络错误: ' + e.message);
    setStatus('回滚失败');
  }
}

// ── Contingency (应急预案) ────────────────────────────────────────
const _RISK_LABELS_CN = {
  rain:                 '天气 / 恶劣天气',
  actor_sick:           '演员临时缺席',
  location_unavailable: '场地不可用',
  overtime:             '进度严重超时',
};

async function runContingency(riskType) {
  if (_pollTimer) { toast('已有任务运行中'); return; }
  const label = _RISK_LABELS_CN[riskType] || riskType;
  q('contingency-title').textContent = `应急预案 — ${label}`;
  q('contingency-body').innerHTML =
    '<div style="text-align:center;padding:30px;color:var(--text-secondary)">⏳ AI 分析中，请稍候...</div>';
  openDialog('dlg-contingency');
  setStatus('生成应急预案...', true);
  try {
    const resp = await fetch('/api/schedule/llm/contingency', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ risk_type: riskType }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      q('contingency-body').innerHTML =
        `<div style="color:var(--danger);padding:16px">启动失败: ${esc(data.error || '')}</div>`;
      setStatus('就绪');
      return;
    }
    startLLMTextPolling(
      '应急预案已生成',
      (result, err) => {
        if (err) {
          q('contingency-body').innerHTML =
            `<div style="color:var(--danger);padding:16px">生成失败: ${esc(err)}</div>`;
        } else if (typeof result === 'string') {
          q('contingency-body').innerHTML =
            `<pre class="llm-text-result">${esc(result)}</pre>`;
        }
      },
      null,
    );
  } catch (e) {
    q('contingency-body').innerHTML =
      `<div style="color:var(--danger);padding:16px">网络错误: ${esc(e.message)}</div>`;
    setStatus('就绪');
  }
}

// ── Preferences dialog ────────────────────────────────────────────
function _computeLearnedRuleDates() {
  _learnedRuleDates.clear();
  if (!_schedule || !_learnedRules.length) return;
  const ruleSceneIds = new Set(_learnedRules.flatMap(r => r.scenes || []));
  (_schedule.shooting_days || []).forEach(day => {
    if ((day.scene_ids || []).some(id => ruleSceneIds.has(id))) {
      _learnedRuleDates.add(day.date);
    }
  });
}

async function openPreferencesDialog() {
  openDialog('dlg-preferences');
  await loadPreferences();
}

async function loadPreferences() {
  q('pref-content').innerHTML =
    '<div style="text-align:center;padding:30px;color:var(--text-secondary)">加载中...</div>';
  try {
    const resp = await fetch('/api/schedule/learned-preferences');
    if (!resp.ok) {
      q('pref-content').innerHTML =
        '<div style="text-align:center;padding:30px;color:var(--text-secondary)">暂无偏好数据（请先打开项目）</div>';
      return;
    }
    const data = await resp.json();
    _learnedRules = data.rules || [];
    _computeLearnedRuleDates();
    _renderPreferences(data);
  } catch (e) {
    q('pref-content').innerHTML =
      `<div style="padding:20px;color:var(--danger)">加载失败: ${esc(e.message)}</div>`;
  }
}

function _renderPreferences(data) {
  const w = data.weights || {};
  const rules = data.rules || [];
  const DEFAULT_W = {
    weight_transition: 1.0, weight_actor: 1.0, weight_location: 1.0,
    weight_balance: 0.5, weight_days: 1.5,
  };
  const LABELS = {
    weight_transition: '转场成本', weight_actor: '演员成本',
    weight_location: '场地成本', weight_balance: '均衡度', weight_days: '压缩天数',
  };
  const maxW = Math.max(5.0, ...Object.values(w).map(Number));
  const bars = Object.entries(LABELS).map(([key, label]) => {
    const learned = (w[key] || 0).toFixed(2);
    const def = DEFAULT_W[key].toFixed(2);
    const pct = Math.round(((w[key] || 0) / maxW) * 100);
    const defPct = Math.round((DEFAULT_W[key] / maxW) * 100);
    return `<div class="pref-bar-row">
      <div class="pref-bar-label">${esc(label)}</div>
      <div class="pref-bar-wrap">
        <div class="pref-bar-learned" style="width:${pct}%"></div>
        <div class="pref-bar-def-marker" style="left:${defPct}%" title="默认: ${def}"></div>
      </div>
      <div class="pref-bar-val">${learned} <span class="pref-def-val">(默认 ${def})</span></div>
    </div>`;
  }).join('');

  const rulesHtml = rules.length === 0
    ? '<div class="pref-no-rules">暂无已学习的排期规则</div>'
    : rules.map(r => `
      <div class="pref-rule-item">
        <span class="pref-rule-type">${esc(r.type || '')}</span>
        <span class="pref-rule-scenes">场次: ${(r.scenes || []).join(', ')}</span>
        ${r.reason ? `<span class="pref-rule-reason" title="${esc(r.reason)}">${esc(r.reason)}</span>` : ''}
      </div>`).join('');

  const adjInfo = data.adjustment_count > 0
    ? `已学习 <b>${data.adjustment_count}</b> 次调整记录，最后更新：${(data.last_adjusted || '').slice(0, 16).replace('T', ' ')}`
    : '暂无调整记录。手动调整排期后，系统会自动学习您的偏好。';

  q('pref-content').innerHTML = `
    <div class="pref-adj-info">${adjInfo}</div>
    <div class="pref-section-title">已学习权重 <span style="font-weight:400;color:#94a3b8">（紫色条 = 学习值，灰线 = 默认值）</span></div>
    <div class="pref-bars">${bars}</div>
    <div class="pref-section-title">已学习排期规则 (${rules.length})</div>
    <div class="pref-rules">${rulesHtml}</div>
  `;
}

async function applyLearnedWeights() {
  try {
    const resp = await fetch('/api/schedule/learned-preferences');
    if (!resp.ok) { toast('无法加载偏好数据'); return; }
    const data = await resp.json();
    const w = data.weights || {};
    const set = (id, val) => { const el = q(id); if (el) el.value = parseFloat(val).toFixed(2); };
    set('gen-w-trans', w.weight_transition || 1.0);
    set('gen-w-actor', w.weight_actor      || 1.0);
    set('gen-w-loc',   w.weight_location   || 1.0);
    set('gen-w-bal',   w.weight_balance    || 0.5);
    set('gen-w-days',  w.weight_days       || 1.5);
    closeDialog('dlg-preferences');
    openDialog('dlg-generate');
    toast('建议权重已预填到排期配置');
  } catch (e) {
    toast('操作失败: ' + e.message);
  }
}

async function resetLearnedPreferences() {
  if (!confirm('确认重置所有学习数据？这将清除已学习的权重和规则。')) return;
  try {
    const resp = await fetch('/api/schedule/learned-preferences/reset', { method: 'POST' });
    if (!resp.ok) { toast('重置失败'); return; }
    _learnedRules = [];
    _learnedRuleDates.clear();
    toast('已重置学习数据');
    // Reload preferences panel if dialog is open
    if (!q('dlg-preferences').classList.contains('hidden')) await loadPreferences();
    // Hide hint banner in generate dialog
    const hint = q('gen-learned-hint');
    if (hint) hint.style.display = 'none';
    renderCenterPanel();
  } catch (e) {
    toast('操作失败: ' + e.message);
  }
}

// ── Diff display ──────────────────────────────────────────────────
function showDiff(impact) {
  let text = '';
  if (typeof impact === 'string') {
    text = impact;
  } else if (impact && typeof impact === 'object') {
    text = JSON.stringify(impact, null, 2);
  }
  q('diff-content').textContent = text || '无详细变更信息';
  q('dlg-diff-title').textContent = '动态调整结果';
  openDialog('dlg-diff');
}

// ── Add-to-day dialog ─────────────────────────────────────────────
let _addSceneNum = null;

function openAddSceneDialog(sceneNum) {
  if (!_schedule || !(_schedule.shooting_days || []).length) {
    toast('请先生成排期');
    return;
  }
  _addSceneNum = sceneNum;
  const sc = _sceneMap[sceneNum] || _sceneMap[String(sceneNum)];
  q('add-scene-desc').textContent =
    `场次 ${sceneNum}：${sc ? sc.heading || '(无标题)' : ''}`;

  const sel = q('add-scene-day');
  sel.innerHTML = _schedule.shooting_days.map((d, i) =>
    `<option value="${esc(d.date)}">第${i+1}天 · ${esc(d.date)}</option>`
  ).join('');

  openDialog('dlg-add-scene');
}

// ── Snapshots dialog ──────────────────────────────────────────────
function openSnapshotsDialog() {
  const container = q('snapshots-list');
  if (_snapshots.length === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-secondary);padding:40px;font-size:13px">暂无快照记录</div>';
  } else {
    container.innerHTML = [..._snapshots].reverse().map(s => `
      <div class="sch-snap-item">
        <span class="sch-snap-ver">v${s.version}</span>
        <div class="sch-snap-info">
          <div class="sch-snap-trigger">${esc(s.trigger || '手动快照')}</div>
          <div class="sch-snap-ts">${esc(s.timestamp ? s.timestamp.slice(0,16).replace('T',' ') : '')}</div>
          ${s.diff_summary ? `<div style="font-size:11px;color:var(--text-secondary)">${esc(s.diff_summary)}</div>` : ''}
        </div>
        <button class="btn-inline" data-v="${s.version}" style="flex-shrink:0">回滚</button>
      </div>
    `).join('');
    container.querySelectorAll('button[data-v]').forEach(btn => {
      btn.addEventListener('click', () => restoreSnapshot(parseInt(btn.dataset.v)));
    });
  }
  openDialog('dlg-snapshots');
}

// ── Reschedule dialog ─────────────────────────────────────────────
const CHANGE_LABELS = {
  weather:       '天气变更',
  actor:         '演员变动',
  location:      '场地变更',
  script_add:    '新增场次',
  script_remove: '删除场次',
};

const CHANGE_FORMS = {
  weather: `
    <div class="sch-fsect">天气变更详情</div>
    <div class="sch-frow"><label>受影响日期</label><input type="date" id="rs-date"></div>
    <div class="sch-frow"><label>天气状况</label>
      <select id="rs-weather"><option value="rain">雨天</option><option value="storm">暴风雨</option><option value="extreme_heat">极端高温</option><option value="fog">大雾</option></select>
    </div>
  `,
  actor: `
    <div class="sch-fsect">演员变动详情</div>
    <div class="sch-frow"><label>演员姓名</label><input type="text" id="rs-actor-name" placeholder="输入演员/角色名"></div>
    <div class="sch-frow"><label>变动类型</label>
      <select id="rs-actor-change"><option value="unavailable">临时无档</option><option value="available_early">档期提前</option><option value="available_late">档期延后</option><option value="leave">退组</option></select>
    </div>
    <div class="sch-frow"><label>起始日期</label><input type="date" id="rs-actor-from"></div>
    <div class="sch-frow"><label>结束日期</label><input type="date" id="rs-actor-to"></div>
  `,
  location: `
    <div class="sch-fsect">场地变更详情</div>
    <div class="sch-frow"><label>场地名称</label><input type="text" id="rs-loc-name" placeholder="原场地名称"></div>
    <div class="sch-frow"><label>变更原因</label>
      <select id="rs-loc-reason"><option value="unavailable">场地不可用</option><option value="cost">成本问题</option><option value="replaced">更换场地</option></select>
    </div>
    <div class="sch-frow"><label>新场地</label><input type="text" id="rs-loc-new" placeholder="替换场地（可选）"></div>
  `,
  script_add: `
    <div class="sch-fsect">新增场次</div>
    <div class="sch-frow"><label>场次编号</label><input type="number" id="rs-add-id" placeholder="场次号" min="1"></div>
    <div class="sch-frow"><label>场次地点</label><input type="text" id="rs-add-loc" placeholder="地点（可选）"></div>
    <p style="font-size:12px;color:var(--text-secondary);margin-top:4px">请确保已在主界面完成场次识别后再进行此操作</p>
  `,
  script_remove: `
    <div class="sch-fsect">删除场次</div>
    <div class="sch-frow"><label>场次编号</label><input type="number" id="rs-rm-id" placeholder="场次号" min="1"></div>
    <p style="font-size:12px;color:var(--text-secondary);margin-top:4px">删除后将触发受影响日期的重新编排</p>
  `,
};

function buildChangeData(changeType) {
  switch (changeType) {
    case 'weather':
      return { date: q('rs-date') && q('rs-date').value, weather: q('rs-weather') && q('rs-weather').value };
    case 'actor':
      return {
        actor_name:   (q('rs-actor-name') || {}).value || '',
        change:       (q('rs-actor-change') || {}).value || '',
        from_date:    (q('rs-actor-from') || {}).value || '',
        to_date:      (q('rs-actor-to') || {}).value || '',
      };
    case 'location':
      return {
        location_name: (q('rs-loc-name') || {}).value || '',
        reason:        (q('rs-loc-reason') || {}).value || '',
        new_location:  (q('rs-loc-new') || {}).value || '',
      };
    case 'script_add':
      return { scene_id: parseInt((q('rs-add-id') || {}).value || 0), location: (q('rs-add-loc') || {}).value || '' };
    case 'script_remove':
      return { scene_id: parseInt((q('rs-rm-id') || {}).value || 0) };
    default:
      return {};
  }
}

// ── Dialog helpers ────────────────────────────────────────────────
function openDialog(id)  { q(id) && q(id).classList.remove('hidden'); }
function closeDialog(id) { q(id) && q(id).classList.add('hidden'); }

// ── Learned-preference helpers ────────────────────────────────────
async function _prefillLearnedWeights() {
  try {
    const resp = await fetch('/api/schedule/learned-preferences');
    if (!resp.ok) return;
    const data = await resp.json();
    const w = data.weights || {};
    if (w.weight_transition !== undefined) {
      const set = (id, val) => { const el = q(id); if (el) el.value = parseFloat(val).toFixed(2); };
      set('gen-w-trans',  w.weight_transition);
      set('gen-w-actor',  w.weight_actor);
      set('gen-w-loc',    w.weight_location);
      set('gen-w-bal',    w.weight_balance);
      set('gen-w-days',   w.weight_days);

      // Show the hint banner
      const hint = q('gen-learned-hint');
      if (hint) hint.style.display = '';

      // If there are learned rules, mention their count
      const rulesHint = q('gen-learned-rules-hint');
      if (rulesHint && data.rules && data.rules.length > 0) {
        rulesHint.textContent =
          `同时携带 ${data.rules.length} 条已学习排期规则（将在优化时自动应用）`;
        rulesHint.style.display = '';
      }
    }
  } catch (_) {
    // Silently ignore — no project open or network error
  }
}

// ── Setup functions ───────────────────────────────────────────────
function setupToolbar() {
  function _refreshDurationHint() {
    const hint = q('gen-duration-hint');
    if (!hint) return;
    const genreKey = (q('sched-genre-key') || {}).value || 'B1_现代都市';
    hint.style.display = 'none';
    fetch(`/api/schedule/estimate-durations?genre_key=${encodeURIComponent(genreKey)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data || data.error) return;
        const genreLabel = (q('sched-genre-key') || {}).options
          ? (q('sched-genre-key').options[q('sched-genre-key').selectedIndex] || {}).text || ''
          : '';
        hint.innerHTML =
          `📊 <b>预估拍摄信息</b><br>` +
          `总场次: ${data.scene_count} &nbsp;|&nbsp; ` +
          `预估总时长: ${data.total_hours}小时 &nbsp;|&nbsp; ` +
          `按每天10小时需 <b>${data.min_days_10h}天</b>，12小时需 <b>${data.min_days_12h}天</b><br>` +
          `当前类型: ${genreLabel} &nbsp;(系数×${data.genre_factor})`;
        hint.style.display = '';
      })
      .catch(() => {});
  }

  q('btn-generate').addEventListener('click', () => {
    openDialog('dlg-generate');
    _prefillLearnedWeights();
    _refreshDurationHint();
  });

  // 切换项目类型时刷新预估
  q('sched-genre-key') && q('sched-genre-key').addEventListener('change', _refreshDurationHint);
  q('btn-llm-loop').addEventListener('click', runLLMLoop);
  q('btn-conflicts').addEventListener('click', checkConflicts);
  q('btn-preferences').addEventListener('click', openPreferencesDialog);

  // Generate dialog
  q('gen-ok').addEventListener('click', async () => {
    const startDate = q('gen-start').value;
    if (!startDate) { toast('请选择开机日期'); return; }
    const restDays = [...q('gen-rest').selectedOptions].map(o => parseInt(o.value));
    const params = {
      start_date:         startDate,
      max_hours_per_day:  parseFloat(q('gen-hours').value) || 12,
      rest_days:          restDays,
      weight_transition:  parseFloat(q('gen-w-trans').value) || 1.0,
      weight_actor:       parseFloat(q('gen-w-actor').value) || 1.0,
      weight_location:    parseFloat(q('gen-w-loc').value)   || 1.0,
      weight_balance:     parseFloat(q('gen-w-bal').value)   || 0.5,
      weight_days:        parseFloat(q('gen-w-days').value)  || 1.5,
      genre_key:          (q('sched-genre-key') || {}).value || 'B1_现代都市',
      constraint_level:   (q('sched-constraint-level') || {}).value || 'relaxed',
    };
    closeDialog('dlg-generate');
    await generateSchedule(params);
  });
  q('gen-cancel').addEventListener('click', () => closeDialog('dlg-generate'));

  // Reschedule dialog
  q('reschedule-ok').addEventListener('click', async () => {
    if (!_pendingChangeType) return;
    const changeData = buildChangeData(_pendingChangeType);
    closeDialog('dlg-reschedule');
    await doReschedule(_pendingChangeType, changeData);
    _pendingChangeType = null;
  });
  q('reschedule-cancel').addEventListener('click', () => { closeDialog('dlg-reschedule'); _pendingChangeType = null; });

  // Snapshots
  q('dd-open-snapshots').addEventListener('click', () => {
    closeDropdown('menu-snapshots');
    openSnapshotsDialog();
  });
  q('snapshots-close').addEventListener('click', () => closeDialog('dlg-snapshots'));

  // Diff dialog
  q('diff-close').addEventListener('click', () => closeDialog('dlg-diff'));

  // LLM loop result dialog
  q('llm-loop-close').addEventListener('click', () => closeDialog('dlg-llm-loop'));

  // Contingency dialog
  q('contingency-close').addEventListener('click', () => {
    closeDialog('dlg-contingency');
    stopPolling();
  });

  // Preferences dialog
  q('pref-close').addEventListener('click', () => closeDialog('dlg-preferences'));
  q('pref-apply').addEventListener('click', applyLearnedWeights);
  q('pref-reset').addEventListener('click', resetLearnedPreferences);

  // Generate dialog — "查看详情" and "重置学习数据" buttons
  q('gen-view-pref') && q('gen-view-pref').addEventListener('click', () => {
    closeDialog('dlg-generate');
    openPreferencesDialog();
  });
  q('gen-reset-learned').addEventListener('click', resetLearnedPreferences);

  // Add-scene dialog
  q('add-scene-ok').addEventListener('click', async () => {
    const dateStr = q('add-scene-day').value;
    if (!dateStr || _addSceneNum == null) return;
    closeDialog('dlg-add-scene');
    await addSceneToDay(dateStr, _addSceneNum);
    _addSceneNum = null;
  });
  q('add-scene-cancel').addEventListener('click', () => { closeDialog('dlg-add-scene'); _addSceneNum = null; });

  // Close overlays on backdrop click
  document.querySelectorAll('.sch-overlay').forEach(ov => {
    ov.addEventListener('click', e => { if (e.target === ov) ov.classList.add('hidden'); });
  });
}

function setupDetailPanel() {
  q('btn-save-day').addEventListener('click', () => {
    if (_selectedDate) saveDay(_selectedDate);
  });
}

function setupDropdowns() {
  // Reschedule dropdown items
  document.querySelectorAll('#menu-reschedule .sch-dd-item[data-change]').forEach(item => {
    item.addEventListener('click', () => {
      const changeType = item.dataset.change;
      closeDropdown('menu-reschedule');
      openRescheduleDialog(changeType);
    });
  });

  // Contingency dropdown items
  document.querySelectorAll('#menu-contingency .sch-dd-item[data-risk]').forEach(item => {
    item.addEventListener('click', () => {
      const riskType = item.dataset.risk;
      closeDropdown('menu-contingency');
      runContingency(riskType);
    });
  });

  // Toggle dropdown on button click
  q('btn-reschedule').addEventListener('click', e => {
    e.stopPropagation();
    toggleDropdown('menu-reschedule');
  });
  q('btn-contingency').addEventListener('click', e => {
    e.stopPropagation();
    toggleDropdown('menu-contingency');
  });
  q('btn-snapshots').addEventListener('click', e => {
    e.stopPropagation();
    toggleDropdown('menu-snapshots');
  });

  // Close all dropdowns on outside click
  document.addEventListener('click', () => {
    document.querySelectorAll('.sch-dd-menu.open').forEach(m => m.classList.remove('open'));
  });
}

function toggleDropdown(menuId) {
  const menu = q(menuId);
  if (!menu) return;
  const wasOpen = menu.classList.contains('open');
  document.querySelectorAll('.sch-dd-menu.open').forEach(m => m.classList.remove('open'));
  if (!wasOpen) menu.classList.add('open');
}

function closeDropdown(menuId) {
  q(menuId) && q(menuId).classList.remove('open');
}

function openRescheduleDialog(changeType) {
  _pendingChangeType = changeType;
  q('dlg-reschedule-title').textContent = '动态调整 — ' + (CHANGE_LABELS[changeType] || changeType);
  q('dlg-reschedule-body').innerHTML = CHANGE_FORMS[changeType] || '<p style="color:var(--text-secondary)">暂无配置项</p>';
  openDialog('dlg-reschedule');
}

function setupDialogs() {
  // Filters
  q('filter-text').addEventListener('input', e => {
    _filterText = e.target.value;
    applyFilters();
  });
  q('filter-location').addEventListener('change', e => {
    _filterLoc = e.target.value;
    applyFilters();
  });
  q('filter-character').addEventListener('change', e => {
    _filterChar = e.target.value;
    applyFilters();
  });
}

// ── Resize handles ────────────────────────────────────────────────
function setupResizeHandles() {
  setupResize('resize-left', 'sch-left', 'sch-center', true);
  setupResize('resize-right', 'sch-center', 'sch-right', false);
}

function setupResize(handleId, leftId, rightId, resizeLeft) {
  const handle = q(handleId);
  if (!handle) return;
  let startX, startW;

  handle.addEventListener('mousedown', e => {
    e.preventDefault();
    handle.classList.add('active');
    startX = e.clientX;
    const target = resizeLeft ? q(leftId) : q(rightId);
    startW = target ? target.offsetWidth : 280;

    function onMove(ev) {
      const delta = ev.clientX - startX;
      const el = resizeLeft ? q(leftId) : q(rightId);
      if (!el) return;
      const newW = Math.max(160, Math.min(500, startW + (resizeLeft ? delta : -delta)));
      el.style.width = newW + 'px';
    }
    function onUp() {
      handle.classList.remove('active');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

// ══════════════════════════════════════════════════════════════════
// Mod 7: 时长参数配置对话框
// ══════════════════════════════════════════════════════════════════

let _dpParams = null;  // 当前加载的 DurationParams dict

async function openDurationParamsDialog() {
  try {
    const r = await fetch('/api/schedule/duration-params');
    _dpParams = r.ok ? await r.json() : {};
  } catch (_) { _dpParams = {}; }
  _renderDpDialog();
  openDialog('dlg-duration-params');
}

function _renderDpDialog() {
  if (!_dpParams) return;
  const set = (id, val) => { const el = q(id); if (el) el.value = val; };
  set('dp-lines-per-page',   _dpParams.lines_per_page   || 30);
  set('dp-min-pages',        _dpParams.min_pages        || 0.125);
  set('dp-transition-base',  _dpParams.transition_base  || 40);

  // 渲染表A
  const tbody = document.querySelector('#dp-table-a tbody');
  if (tbody) {
    tbody.innerHTML = '';
    const tableA = _dpParams.table_a || {};
    Object.entries(tableA).forEach(([key, entry]) => {
      const label = typeof entry === 'object' ? (entry.label || key) : key;
      const mins  = typeof entry === 'object' ? (entry.minutes || 0) : entry;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:var(--text-secondary);font-size:11px;white-space:nowrap">${esc(key)}</td>
        <td>${esc(label)}</td>
        <td><input type="number" value="${mins}" min="1" max="300" step="1" data-a-key="${esc(key)}"></td>
      `;
      tbody.appendChild(tr);
    });
  }

  // 渲染自定义类型
  _renderCustomTypesTable();
}

function _renderCustomTypesTable() {
  const tbody = q('dp-custom-types-body');
  if (!tbody || !_dpParams) return;
  tbody.innerHTML = '';
  const custom = _dpParams.custom_scene_types || {};
  const rules  = _dpParams.keyword_rules || {};
  if (Object.keys(custom).length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-secondary);font-style:italic;padding:8px">暂无自定义类型</td></tr>';
    return;
  }
  Object.entries(custom).forEach(([key, entry]) => {
    const label = typeof entry === 'object' ? (entry.label || key) : key;
    const mins  = typeof entry === 'object' ? (entry.minutes || 0) : entry;
    const kws   = (rules[key] && rules[key].keywords) ? rules[key].keywords.join(',') : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="font-size:11px;color:var(--text-secondary)">${esc(key)}</td>
      <td>${esc(label)}</td>
      <td>${mins}</td>
      <td style="font-size:11px">${esc(kws)}</td>
      <td><button class="dp-del-btn" data-key="${esc(key)}">删除</button></td>
    `;
    tr.querySelector('.dp-del-btn').addEventListener('click', async e => {
      const k = e.target.dataset.key;
      await fetch('/api/schedule/custom-scene-types', {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: k}),
      });
      delete (_dpParams.custom_scene_types || {})[k];
      delete (_dpParams.keyword_rules || {})[k];
      _renderCustomTypesTable();
      toast('已删除: ' + k);
    });
    tbody.appendChild(tr);
  });
}

// 保存时长参数
async function saveDurationParams() {
  if (!_dpParams) return;

  // 读取基本参数
  _dpParams.lines_per_page  = parseFloat(q('dp-lines-per-page').value)  || 30;
  _dpParams.min_pages       = parseFloat(q('dp-min-pages').value)       || 0.125;
  _dpParams.transition_base = parseInt(q('dp-transition-base').value)   || 40;

  // 读取表A的修改值
  document.querySelectorAll('#dp-table-a input[data-a-key]').forEach(inp => {
    const key = inp.dataset.aKey;
    if (!key || !_dpParams.table_a || !_dpParams.table_a[key]) return;
    _dpParams.table_a[key].minutes = parseInt(inp.value) || _dpParams.table_a[key].minutes;
  });

  try {
    const r = await fetch('/api/schedule/duration-params', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(_dpParams),
    });
    if (r.ok) {
      toast('时长参数已保存');
      closeDialog('dlg-duration-params');
    } else {
      toast('保存失败');
    }
  } catch (e) {
    toast('保存出错: ' + e.message);
  }
}

// 恢复默认值（重新获取不带自定义修改的默认参数）
async function resetDurationParamsToDefaults() {
  if (!confirm('确定要恢复所有参数到系统默认值吗？自定义类型也会被清空。')) return;
  // 发送空对象触发服务端用 DurationParams() 默认值覆盖
  await fetch('/api/schedule/duration-params', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({}),
  });
  await openDurationParamsDialog();  // 重新加载
  toast('已恢复默认值');
}

// 添加自定义类型
async function addCustomSceneType() {
  const key   = (q('dp-new-type-key').value || '').trim();
  const label = (q('dp-new-type-label').value || '').trim();
  const mins  = parseInt(q('dp-new-type-minutes').value) || 20;
  const kwStr = (q('dp-new-type-keywords').value || '').trim();
  if (!key) { toast('请填写类型键'); return; }

  const body = { key, label: label || key, minutes: mins };
  if (kwStr) body.keywords = kwStr.split(/[,，\s]+/).filter(Boolean);

  try {
    const r = await fetch('/api/schedule/custom-scene-types', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) { toast('添加失败'); return; }
    // 更新本地 _dpParams
    if (!_dpParams.custom_scene_types) _dpParams.custom_scene_types = {};
    _dpParams.custom_scene_types[key] = {label: label || key, minutes: mins};
    if (kwStr) {
      if (!_dpParams.keyword_rules) _dpParams.keyword_rules = {};
      _dpParams.keyword_rules[key] = {keywords: body.keywords, priority: 50, description: label||key};
    }
    _renderCustomTypesTable();
    q('dp-new-type-key').value = '';
    q('dp-new-type-label').value = '';
    q('dp-new-type-keywords').value = '';
    toast('已添加: ' + key);
  } catch (e) {
    toast('添加出错: ' + e.message);
  }
}

// ══════════════════════════════════════════════════════════════════
// Mod 8: 场次时长详情 / 类型覆盖对话框
// ══════════════════════════════════════════════════════════════════

let _sdCurrentSceneNum = null;

async function openSceneDetailDialog(sceneNum) {
  _sdCurrentSceneNum = sceneNum;
  const sc = _sceneMap[sceneNum] || _sceneMap[String(sceneNum)];

  q('sd-title').textContent = `场次 ${sceneNum} — 时长详情`;
  q('sd-heading').textContent = sc ? (sc.heading || '（无标题）') : `场次 ${sceneNum}`;
  q('sd-meta').textContent = sc
    ? [sc.int_ext, sc.location, sc.time_of_day].filter(Boolean).join(' · ')
    : '';
  q('sd-formula').textContent = '加载中...';
  q('sd-type-label').textContent = '';
  q('sd-keywords').textContent = '';
  q('sd-classify-detail').textContent = '';
  q('sd-confidence-badge').className = 'dp-badge-method';
  q('sd-confidence-badge').textContent = '';
  q('sd-method-badge').className = 'dp-badge-method';
  q('sd-method-badge').textContent = '';

  openDialog('dlg-scene-detail');

  // 先填充类型选择器（从 _dpParams 或重新获取）
  await _populateTypeOverrideSelect(sceneNum);

  // 获取时长详情
  try {
    const r = await fetch(`/api/scenes/${sceneNum}/duration`);
    if (!r.ok) { q('sd-formula').textContent = '获取失败'; return; }
    const data = await r.json();

    // 类型信息
    const cls = data.classification || {};
    const methodLabels = {manual:'手动指定', keyword:'关键词', cast_count:'演员数量', attribute:'场景属性', default:'默认'};
    const confLabels   = {high:'高置信', medium:'中置信', low:'低置信'};

    q('sd-type-label').textContent = `${data.a_label || data.a_key || ''} (${data.a_key || ''})`;

    const confBadge = q('sd-confidence-badge');
    confBadge.className = `dp-badge-method dp-badge-${cls.confidence || 'low'}`;
    confBadge.textContent = confLabels[cls.confidence] || cls.confidence || '';

    const methBadge = q('sd-method-badge');
    methBadge.className = `dp-badge-method dp-badge-${cls.method || 'default'}`;
    methBadge.textContent = methodLabels[cls.method] || cls.method || '';

    if (cls.matched_keywords && cls.matched_keywords.length > 0) {
      q('sd-keywords').textContent = '匹配关键词：' + cls.matched_keywords.join('、');
    }
    q('sd-classify-detail').textContent = cls.detail || '';

    // 公式
    q('sd-formula').textContent = data.formula || '无';

    // 如果有手动指定类型，同步到下拉框
    const ent = _entityMap[sceneNum] || _entityMap[String(sceneNum)] || {};
    const overrideKey = ent.scene_type_key || '';
    const sel = q('sd-type-override');
    if (sel && overrideKey) {
      sel.value = overrideKey;
    }
  } catch (e) {
    q('sd-formula').textContent = '加载失败: ' + e.message;
  }
}

async function _populateTypeOverrideSelect(sceneNum) {
  const sel = q('sd-type-override');
  if (!sel) return;

  // 获取参数（若已缓存则直接用）
  let params = _dpParams;
  if (!params) {
    try {
      const r = await fetch('/api/schedule/duration-params');
      params = r.ok ? await r.json() : {};
      _dpParams = params;
    } catch (_) { params = {}; }
  }

  // 清空并重建选项
  sel.innerHTML = '<option value="">— 自动识别 —</option>';
  const tableA = params.table_a || {};
  const custom = params.custom_scene_types || {};
  [...Object.entries(tableA), ...Object.entries(custom)].forEach(([key, entry]) => {
    const label = typeof entry === 'object' ? (entry.label || key) : key;
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = `${key} — ${label}`;
    sel.appendChild(opt);
  });

  // 回填当前已指定的类型
  const ent = _entityMap[sceneNum] || _entityMap[String(sceneNum)] || {};
  if (ent.scene_type_key) sel.value = ent.scene_type_key;
}

async function saveSceneTypeOverride() {
  const sceneNum = _sdCurrentSceneNum;
  if (sceneNum == null) return;
  const sel = q('sd-type-override');
  const newKey = sel ? sel.value : '';

  try {
    const r = await fetch(`/api/scenes/llm/classify-types`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      // 空 body = 不触发 LLM，直接通过 save-entities 路径
    });
    // 实际上这个路径是 LLM 批量的，单场覆盖直接用 _save_entities_to_episodes
    // 改为调用一个内联更新：先更新本地 _entityMap，再调用专门的覆盖接口
  } catch (_) {}

  // 使用专用的单场类型覆盖接口（在 app.py 中已有 custom-scene-types 之外，
  // 这里利用 LLM classify route 的 _save_entities_to_episodes 机制）
  // 最简单的方式：POST 一个仅包含该场次结果的 "手动分类" 请求
  try {
    // 直接构造一个伪 LLM classify 响应结构并调用 save-entities 端点
    // 因为后端没有单场覆盖接口，我们先在本地更新 _entityMap，
    // 再触发一次 LLM classify（只针对该场次，空 prompt）跳过 LLM 直接写 scene_type_key
    // 最简实现：发送 POST /api/scenes/llm/classify-types 并在后端等等…
    // 更简洁的方式：后端已有 _save_entities_to_episodes，
    // 但没有直接暴露。添加一个 inline save 接口会更干净。
    // 这里用一个轻量 workaround：把 override 写入本地 _entityMap 并 toast 提示
    // 真正持久化需要后端接口，下面调用后端的专用端点

    const body = { scene_number: sceneNum, scene_type_key: newKey };
    const resp = await fetch('/api/scenes/type-override', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      // 更新本地 entityMap
      if (!_entityMap[sceneNum]) _entityMap[sceneNum] = {};
      _entityMap[sceneNum].scene_type_key = newKey;
      _entityMap[String(sceneNum)] = _entityMap[sceneNum];
      toast(newKey ? `已固定场次 ${sceneNum} 类型为 ${newKey}` : `已清除场次 ${sceneNum} 手动指定类型`);
      closeDialog('dlg-scene-detail');
    } else {
      toast('保存失败');
    }
  } catch (e) {
    toast('保存出错: ' + e.message);
  }
}

// ══════════════════════════════════════════════════════════════════
// Mod 9: LLM 批量识别场景类型
// ══════════════════════════════════════════════════════════════════

let _llmClsTaskId   = null;
let _llmClsTimer    = null;

async function runLLMClassify() {
  // 获取当前 genre_key（若生成对话框有值则使用）
  const genreKey = (q('sched-genre-key') || {}).value || '';

  openDialog('dlg-llm-classify');
  q('llm-cls-status').textContent = '正在启动 LLM 批量识别...';
  q('llm-cls-bar').style.width = '0%';
  q('llm-cls-result').style.display = 'none';

  try {
    const body = {};
    if (genreKey) body.genre_key = genreKey;
    const r = await fetch('/api/scenes/llm/classify-types', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json();
      q('llm-cls-status').textContent = '启动失败: ' + (err.error || r.status);
      return;
    }
    const data = await r.json();
    _llmClsTaskId = data.task_id;
    const total = data.total || 1;
    q('llm-cls-status').textContent = `识别中（共 ${total} 场）...`;

    // 轮询
    _llmClsTimer = setInterval(async () => {
      try {
        const sr = await fetch(`/api/scenes/llm/classify-status/${_llmClsTaskId}`);
        if (!sr.ok) return;
        const sd = await sr.json();
        const pct = Math.round((sd.progress || 0) / Math.max(total, 1) * 100);
        q('llm-cls-bar').style.width = pct + '%';

        if (sd.status === 'done') {
          clearInterval(_llmClsTimer);
          _llmClsTimer = null;
          const cnt = Object.keys(sd.results || {}).length;
          q('llm-cls-status').textContent = `识别完成！共标注 ${cnt} 个场次`;
          q('llm-cls-bar').style.width = '100%';
          const res = q('llm-cls-result');
          res.style.display = '';
          res.textContent = Object.entries(sd.results || {}).slice(0, 20)
            .map(([sn, v]) => `场次${sn}: ${v.scene_type_key}`)
            .join('\n') + (cnt > 20 ? `\n...共 ${cnt} 场` : '');
          // 刷新本地 entityMap
          Object.entries(sd.results || {}).forEach(([sn, v]) => {
            const n = parseInt(sn);
            if (!_entityMap[n]) _entityMap[n] = {};
            _entityMap[n].scene_type_key = v.scene_type_key;
            _entityMap[String(n)] = _entityMap[n];
          });
        } else if (sd.status === 'error') {
          clearInterval(_llmClsTimer);
          _llmClsTimer = null;
          q('llm-cls-status').textContent = '识别出错: ' + (sd.error || '未知错误');
        } else {
          q('llm-cls-status').textContent = `识别中（${sd.progress || 0}/${total}）...`;
        }
      } catch (_) {}
    }, 2000);
  } catch (e) {
    q('llm-cls-status').textContent = '请求失败: ' + e.message;
  }
}

// ══════════════════════════════════════════════════════════════════
// 注册新对话框按钮事件（在 DOMContentLoaded 时调用）
// ══════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  // ── Mod 7: 时长参数 ───────────────────────────────────────────
  q('btn-duration-params') && q('btn-duration-params').addEventListener('click', openDurationParamsDialog);
  q('dp-save')    && q('dp-save').addEventListener('click', saveDurationParams);
  q('dp-cancel')  && q('dp-cancel').addEventListener('click', () => closeDialog('dlg-duration-params'));
  q('dp-reset-defaults') && q('dp-reset-defaults').addEventListener('click', resetDurationParamsToDefaults);
  q('dp-add-custom-type') && q('dp-add-custom-type').addEventListener('click', addCustomSceneType);

  // ── Mod 8: 场次详情对话框 ─────────────────────────────────────
  q('sd-close') && q('sd-close').addEventListener('click', () => closeDialog('dlg-scene-detail'));
  q('sd-save-override') && q('sd-save-override').addEventListener('click', saveSceneTypeOverride);

  // ── Mod 9: LLM 批量识别 ──────────────────────────────────────
  q('btn-llm-classify') && q('btn-llm-classify').addEventListener('click', runLLMClassify);
  q('llm-cls-close') && q('llm-cls-close').addEventListener('click', () => {
    if (_llmClsTimer) { clearInterval(_llmClsTimer); _llmClsTimer = null; }
    closeDialog('dlg-llm-classify');
  });

  // 所有新 overlay 的背景点击关闭
  ['dlg-duration-params', 'dlg-scene-detail', 'dlg-llm-classify'].forEach(id => {
    const ov = q(id);
    if (ov) ov.addEventListener('click', e => { if (e.target === ov) ov.classList.add('hidden'); });
  });
});
