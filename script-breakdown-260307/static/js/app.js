/**
 * app.js - Core logic: state management, API calls, event bindings, keyboard shortcuts.
 */

const App = {
    /** Current application state from server. */
    state: { lines: [], scenes: [], filename: '', status: '', can_undo: false, can_redo: false },

    /** LLM polling interval ID. */
    _pollTimer: null,

    /** Split mode: when true, clicking a script line inserts a break there. */
    _splitMode: false,

    /** Edit mode: when true, line-content spans are contenteditable. */
    _editMode: false,

    // ── Initialization ───────────────────────────────────────────

    init() {
        this._bindToolbar();
        this._bindDetail();
        this._bindLLMDialog();
        this._bindPrefsDialog();
        this._bindKeyboard();
        this._bindResize();
        this._bindTabs();
        this._bindAnalysis();
        this._bindSummaryExport();
        this._loadState();
        // 预加载时长参数供分析面板下拉框使用
        fetch('/api/schedule/duration-params').then(r => r.ok ? r.json() : null)
            .then(d => { if (d) window._dpParamsCache = d; }).catch(() => {});
    },

    // ── API Helpers ──────────────────────────────────────────────

    async _api(url, options = {}) {
        try {
            const resp = await fetch(url, options);
            const data = await resp.json();
            if (!resp.ok) {
                this._setStatus(data.error || `请求失败 (${resp.status})`);
                return null;
            }
            return data;
        } catch (err) {
            this._setStatus(`网络错误: ${err.message}`);
            return null;
        }
    },

    async _apiJson(url, body) {
        return this._api(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    },

    // ── State Management ─────────────────────────────────────────

    async _loadState() {
        const data = await this._api('/api/state');
        if (data) this._applyState(data);
    },

    _applyState(data) {
        this.state = data;
        this._setStatus(data.status);
        this._updateToolbar();
        this._updateProjectUI(data.project);

        // Don't re-render script view while user is actively editing
        if (!this._editMode) {
            this.exitSplitMode();
            Panels.renderSceneList(data.scenes || []);
            Panels.renderScriptView(data.lines || [], data.scenes || []);

            // Re-select if a scene was selected
            if (Panels.selectedScene >= 0 && data.scenes && Panels.selectedScene < data.scenes.length) {
                Panels.selectScene(Panels.selectedScene);
            } else {
                Panels.clearDetail();
            }
        }

        // Update analysis panel if visible
        Panels.updateAnalysisPanel(data);
    },

    _setStatus(msg) {
        document.getElementById('status-text').textContent = msg;
    },

    _showSpinner(show) {
        document.getElementById('status-spinner').style.display = show ? '' : 'none';
    },

    _updateToolbar() {
        const hasData = this.state.lines && this.state.lines.length > 0;
        const isPdf = hasData && this.state.filename &&
            this.state.filename.toLowerCase().endsWith('.pdf');
        const isLocked = !!this.state.content_locked;
        const inEdit = this._editMode;
        document.getElementById('btn-detect').disabled = !hasData || inEdit;
        document.getElementById('btn-llm-detect').disabled = !hasData || inEdit;
        document.getElementById('btn-pdf-llm').disabled = !isPdf || inEdit;
        document.getElementById('btn-export-txt').disabled = !hasData;
        document.getElementById('btn-export-csv').disabled = !hasData;
        document.getElementById('btn-split-mode').disabled = !hasData || isLocked || inEdit;
        document.getElementById('btn-undo').disabled = !this.state.can_undo || inEdit;
        document.getElementById('btn-redo').disabled = !this.state.can_redo || inEdit;
        const lineSelectBtn = document.getElementById('btn-line-select-mode');
        if (lineSelectBtn) lineSelectBtn.disabled = inEdit;

        // Edit content controls
        const lockBtn = document.getElementById('btn-content-lock');
        const editBtn = document.getElementById('btn-edit-content');
        if (lockBtn) {
            lockBtn.textContent = isLocked ? '🔒' : '🔓';
            lockBtn.title = isLocked ? '内容已锁定，点击解锁' : '点击锁定，防止误编辑';
            lockBtn.classList.toggle('locked', isLocked);
        }
        if (editBtn) {
            editBtn.disabled = !hasData || isLocked || this._editMode;
        }
    },

    _updateProjectUI(project) {
        const hasProject = !!project;
        document.getElementById('btn-episodes').disabled = !hasProject;
        document.getElementById('btn-save-project').disabled = !hasProject;
        ['btn-export-project', 'btn-export-project-quick'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = !hasProject;
        });

        const indicator = document.getElementById('episode-indicator');
        const title = document.querySelector('title');

        if (project) {
            const ep = project.episodes.find(e => e.id === project.active_episode_id);
            const epName = ep ? ep.name : '';
            title.textContent = `${project.name}${epName ? ' · ' + epName : ''} - 剧本拆解`;
            if (epName) {
                indicator.textContent = `📁 ${project.name} · ${epName}`;
                indicator.style.display = '';
                indicator.title = `项目: ${project.name}  集数: ${epName}（点击管理集数）`;
            } else {
                indicator.textContent = `📁 ${project.name}`;
                indicator.style.display = '';
                indicator.title = `项目: ${project.name}（点击管理集数）`;
            }
        } else {
            title.textContent = '剧本拆解 - Script Breakdown';
            indicator.style.display = 'none';
        }
    },

    // ── Upload ───────────────────────────────────────────────────

    /** File pending import (shown in import dialog when project is open). */
    _pendingImportFile: null,

    async uploadFile(file) {
        // If project is open, ask whether to add as episode or replace
        if (this.state.project) {
            this._pendingImportFile = file;
            const episodeNameInput = document.getElementById('import-episode-name');
            episodeNameInput.value = file.name.replace(/\.[^.]+$/, '');
            document.getElementById('import-dialog-overlay').style.display = 'flex';
            return;
        }
        await this._doUpload(file, false, '');
    },

    async _doUpload(file, addAsEpisode, episodeName) {
        this._setStatus('正在上传...');
        this._showSpinner(true);

        const formData = new FormData();
        formData.append('file', file);
        if (addAsEpisode) {
            formData.append('add_as_episode', 'true');
            formData.append('episode_name', episodeName);
        }

        const data = await this._api('/api/upload', {
            method: 'POST',
            body: formData,
        });

        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
        }
    },

    _closeImportDialog() {
        document.getElementById('import-dialog-overlay').style.display = 'none';
        this._pendingImportFile = null;
    },

    // ── Detect ───────────────────────────────────────────────────

    async autoDetect() {
        this._setStatus('正在自动识别...');
        this._showSpinner(true);
        const data = await this._apiJson('/api/detect', {});
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
        }
    },

    // ── Undo / Redo ──────────────────────────────────────────────

    async undo() {
        const data = await this._apiJson('/api/undo', {});
        if (data) this._applyState(data);
    },

    async redo() {
        const data = await this._apiJson('/api/redo', {});
        if (data) this._applyState(data);
    },

    // ── LLM Detect ──────────────────────────────────────────────

    async llmDetect() {
        this._showSpinner(true);
        const data = await this._apiJson('/api/llm/detect', {});
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
        }
    },

    // ── Content Edit & Lock ──────────────────────────────────────

    async toggleLock() {
        const data = await this._apiJson('/api/lines/toggle-lock', {});
        if (data) this._applyState(data);
    },

    enterEditMode() {
        // Exit conflicting modes first
        if (Panels.lineSelectMode) Panels.toggleLineSelectMode();
        this.exitSplitMode();

        const scriptView = document.getElementById('script-view');
        const banner = document.getElementById('edit-mode-banner');

        // Make every line-content span directly editable.
        // Restore plain text first (clears any entity-highlight <mark> tags).
        scriptView.querySelectorAll('.line-content').forEach(span => {
            const plain = span.dataset.originalText !== undefined
                ? span.dataset.originalText
                : span.textContent;
            span.textContent = plain;
            span.contentEditable = 'true';
            span.spellcheck = false;
        });

        // Intercept Enter (split line) and Backspace-at-start (merge with prev)
        scriptView.addEventListener('keydown', this._editKeyHandler = (e) => {
            this._handleEditKey(e);
        });

        // Strip HTML from pasted content; handle multi-line paste
        scriptView.addEventListener('paste', this._editPasteHandler = (e) => {
            this._handleEditPaste(e);
        });

        scriptView.classList.add('editing');
        banner.style.display = 'flex';
        this._editMode = true;
        this._updateToolbar();
    },

    _exitEditMode() {
        const scriptView = document.getElementById('script-view');
        const banner = document.getElementById('edit-mode-banner');

        scriptView.querySelectorAll('.line-content').forEach(span => {
            span.removeAttribute('contenteditable');
        });

        if (this._editKeyHandler) {
            scriptView.removeEventListener('keydown', this._editKeyHandler);
            this._editKeyHandler = null;
        }
        if (this._editPasteHandler) {
            scriptView.removeEventListener('paste', this._editPasteHandler);
            this._editPasteHandler = null;
        }

        scriptView.classList.remove('editing');
        banner.style.display = 'none';
        this._editMode = false;
    },

    async saveEditMode() {
        const scriptView = document.getElementById('script-view');
        const lines = [];
        scriptView.querySelectorAll('.line-content').forEach(span => {
            lines.push(span.textContent);
        });
        this._exitEditMode();
        this._showSpinner(true);
        const data = await this._apiJson('/api/lines/replace', { lines });
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
        }
    },

    cancelEditMode() {
        this._exitEditMode();
        this._updateToolbar();
        Panels.renderScriptView(this.state.lines || [], this.state.scenes || []);
    },

    // ── Edit mode key/paste helpers ──────────────────────────────

    _handleEditKey(e) {
        const span = e.target.closest('.line-content');
        if (!span) return;
        if (e.key === 'Enter') {
            e.preventDefault();
            this._splitLine(span);
        } else if (e.key === 'Backspace' && this._isCaretAtStart(span)) {
            e.preventDefault();
            this._mergeWithPrevLine(span);
        }
    },

    /** Returns true when the caret is at the very start of the given element. */
    _isCaretAtStart(el) {
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount || !sel.getRangeAt(0).collapsed) return false;
        const r = document.createRange();
        r.selectNodeContents(el);
        r.setEnd(sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset);
        return r.toString().length === 0;
    },

    /** Returns caret character offset within el. */
    _caretOffset(el) {
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount) return 0;
        const r = document.createRange();
        r.selectNodeContents(el);
        r.setEnd(sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset);
        return r.toString().length;
    },

    /** Split span at caret: text before stays, text after goes to a new line below. */
    _splitLine(span) {
        const offset = this._caretOffset(span);
        const full = span.textContent;
        span.textContent = full.slice(0, offset);

        const row = span.closest('.script-line');
        const newRow = document.createElement('div');
        newRow.className = 'script-line';

        const numSpan = document.createElement('span');
        numSpan.className = 'line-number';
        numSpan.textContent = '·';

        const newContent = document.createElement('span');
        newContent.className = 'line-content';
        newContent.contentEditable = 'true';
        newContent.spellcheck = false;
        newContent.textContent = full.slice(offset);

        newRow.appendChild(numSpan);
        newRow.appendChild(newContent);
        row.parentNode.insertBefore(newRow, row.nextSibling);

        // Move caret to start of new span
        const range = document.createRange();
        range.setStart(newContent.firstChild || newContent, 0);
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        newContent.focus();
    },

    /** Backspace at line start: append current line text to end of previous line. */
    _mergeWithPrevLine(span) {
        const row = span.closest('.script-line');
        const prevRow = row.previousElementSibling;
        if (!prevRow) return;
        const prevSpan = prevRow.querySelector('.line-content');
        if (!prevSpan) return;

        const junction = prevSpan.textContent.length;
        prevSpan.textContent = prevSpan.textContent + span.textContent;
        row.parentNode.removeChild(row);

        // Place caret at junction point
        const range = document.createRange();
        const node = prevSpan.firstChild;
        if (node) {
            range.setStart(node, Math.min(junction, node.length));
        } else {
            range.setStart(prevSpan, 0);
        }
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        prevSpan.focus();
    },

    /** Paste handler: strip HTML and handle multi-line paste correctly. */
    _handleEditPaste(e) {
        const span = e.target.closest('.line-content');
        if (!span) return;
        e.preventDefault();

        const text = (e.clipboardData || window.clipboardData).getData('text/plain');
        if (!text) return;

        const pasteLines = text.split('\n');
        const offset = this._caretOffset(span);
        const before = span.textContent.slice(0, offset);
        const after  = span.textContent.slice(offset);

        if (pasteLines.length === 1) {
            // Single-line paste: just insert inline
            span.textContent = before + text + after;
            const range = document.createRange();
            const node = span.firstChild;
            const pos = before.length + text.length;
            range.setStart(node || span, node ? Math.min(pos, node.length) : 0);
            range.collapse(true);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            return;
        }

        // Multi-line paste: first pasted line merges into current span,
        // remaining lines become new script-line rows.
        span.textContent = before + pasteLines[0];
        let prevRow = span.closest('.script-line');
        for (let i = 1; i < pasteLines.length; i++) {
            const isLast = i === pasteLines.length - 1;
            const newRow = document.createElement('div');
            newRow.className = 'script-line';

            const numSpan = document.createElement('span');
            numSpan.className = 'line-number';
            numSpan.textContent = '·';

            const newSpan = document.createElement('span');
            newSpan.className = 'line-content';
            newSpan.contentEditable = 'true';
            newSpan.spellcheck = false;
            newSpan.textContent = pasteLines[i] + (isLast ? after : '');

            newRow.appendChild(numSpan);
            newRow.appendChild(newSpan);
            prevRow.parentNode.insertBefore(newRow, prevRow.nextSibling);
            prevRow = newRow;
        }

        // Place caret at end of last pasted content (before the original "after")
        const lastSpan = prevRow.querySelector('.line-content');
        const insertedLen = pasteLines[pasteLines.length - 1].length;
        const range = document.createRange();
        const node = lastSpan.firstChild;
        range.setStart(node || lastSpan, node ? Math.min(insertedLen, node.length) : 0);
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        lastSpan.focus();
    },

    // ── LLM PDF Clean ────────────────────────────────────────────

    async llmPdfClean() {
        this._showSpinner(true);
        const data = await this._apiJson('/api/llm/pdf-clean', {});
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
        }
    },

    // ── LLM Summarize ───────────────────────────────────────────

    async llmSummarize(index) {
        this._showSpinner(true);
        const data = await this._apiJson(`/api/llm/summarize/${index}`, {});
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
        }
    },

    // ── Entity Extraction ───────────────────────────────────────

    async extractScene(index) {
        const useLLM = document.getElementById('chk-use-llm')?.checked || false;
        this._showSpinner(true);
        const data = await this._apiJson(`/api/extract/${index}`, { use_llm: useLLM });
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
            if (data) this._applyState(data);
        }
    },

    async extractAll() {
        const useLLM = document.getElementById('chk-use-llm')?.checked || false;
        this._showSpinner(true);
        const data = await this._apiJson('/api/extract/all', { use_llm: useLLM });
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
            if (data) this._applyState(data);
        }
    },

    // ── Entity Editing ───────────────────────────────────────────

    /** Add an entity to a specific scene's entity list. */
    async addSceneEntity(idx, type, name) {
        const entities = this.state.entities || {};
        const sceneEnt = Object.assign({ characters: [], props: [], scene_type: '' },
            entities[idx] || {});
        const key = type === 'character' ? 'characters' : 'props';
        if (!sceneEnt[key].includes(name)) {
            sceneEnt[key] = [...sceneEnt[key], name];
        }
        const data = await this._api(`/api/entities/${idx}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sceneEnt),
        });
        if (data) this._applyState(data);
    },

    /** Remove an entity from a specific scene's entity list. */
    async removeSceneEntity(idx, type, name) {
        const entities = this.state.entities || {};
        const sceneEnt = Object.assign({ characters: [], props: [], scene_type: '' },
            entities[idx] || {});
        const key = type === 'character' ? 'characters' : 'props';
        sceneEnt[key] = sceneEnt[key].filter(x => x !== name);
        const data = await this._api(`/api/entities/${idx}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sceneEnt),
        });
        if (data) this._applyState(data);
    },

    /** Update the scene_type (and scene_type_key) for a scene's entity. */
    async updateSceneType(idx, sceneType) {
        const entities = this.state.entities || {};
        const sceneEnt = Object.assign({ characters: [], props: [], scene_type: '' },
            entities[idx] || {});
        sceneEnt.scene_type = sceneType;
        // Sync scene_type_key: if the selected value is a known structured key, use it
        if (sceneType && window._dpParamsCache) {
            const tableA = window._dpParamsCache.table_a || {};
            const custom = window._dpParamsCache.custom_scene_types || {};
            if (tableA[sceneType] || custom[sceneType]) {
                sceneEnt.scene_type_key = sceneType;
            }
        }
        const data = await this._api(`/api/entities/${idx}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sceneEnt),
        });
        if (data) this._applyState(data);
    },

    /** Rename an entity globally (character or prop). */
    async renameEntity(oldName, newName, type) {
        const data = await this._api('/api/entities/rename', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_name: oldName, new_name: newName, type }),
        });
        if (data) this._applyState(data);
    },

    /** Remove an entity globally from all scenes. */
    async removeEntity(name, type) {
        const data = await this._api('/api/entities/remove', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, type }),
        });
        if (data) this._applyState(data);
    },

    /** Open the merge dialog for characters or props. */
    _openMergeDialog(type) {
        const global = this.state.global_entities || {};
        const entities = type === 'character'
            ? (global.characters || [])
            : (global.props || []);
        this._mergeDialogType = type;
        Panels.renderMergeDialog(entities, type);
    },

    _closeMergeDialog() {
        document.getElementById('merge-dialog-overlay').style.display = 'none';
    },

    async _confirmMerge() {
        const targetName = document.getElementById('merge-target-input').value.trim();
        if (!targetName) { alert('请输入合并目标名称'); return; }

        const checked = document.querySelectorAll('#merge-source-list .merge-check:checked');
        const sourceNames = Array.from(checked).map(cb => cb.value);
        if (sourceNames.length === 0) { alert('请选择至少一个要合并的名称'); return; }

        this._closeMergeDialog();
        const data = await this._apiJson('/api/entities/merge', {
            target_name: targetName,
            source_names: sourceNames,
            type: this._mergeDialogType || 'character',
        });
        if (data) this._applyState(data);
    },

    // ── Character Analysis ──────────────────────────────────────

    async analyzeCharacter(name) {
        this._showSpinner(true);
        const data = await this._apiJson('/api/llm/analyze_character', { name });
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
        }
    },

    async analyzeAllCharacters() {
        this._showSpinner(true);
        const data = await this._apiJson('/api/llm/analyze_all', {});
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
        }
    },

    // ── LLM Polling ─────────────────────────────────────────────

    _startPolling() {
        if (this._pollTimer) return;
        this._pollTimer = setInterval(() => this._pollLLMStatus(), 1500);
    },

    _stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
        this._showSpinner(false);
    },

    async _pollLLMStatus() {
        const data = await this._api('/api/llm/status');
        if (!data) return;

        if (data.status === 'done') {
            this._stopPolling();
            if (data.state) {
                this._applyState(data.state);
            }
            // If it was a summarize task and we have the selected scene, update detail
            if (data.task_type === 'summarize' && data.scene_index >= 0) {
                const scene = this.state.scenes[data.scene_index];
                if (scene && Panels.selectedScene === data.scene_index) {
                    Panels.updateSummaryField(scene.summary);
                }
            }
        } else if (data.status === 'error') {
            this._stopPolling();
            this._setStatus(`LLM 错误: ${data.error}`);
        }
        // If still running, continue polling
    },

    // ── Calibration ─────────────────────────────────────────────

    async insertBreak(lineIndex) {
        const data = await this._apiJson('/api/calibrate/insert_break', { line_index: lineIndex });
        if (data) this._applyState(data);
    },

    async deleteBreak(lineIndex) {
        const data = await this._apiJson('/api/calibrate/delete_break', { line_index: lineIndex });
        if (data) this._applyState(data);
    },

    async mergeScenes(idx1, idx2) {
        const data = await this._apiJson('/api/calibrate/merge', { index1: idx1, index2: idx2 });
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
        }
    },

    // ── Scene Delete ─────────────────────────────────────────────

    async deleteScenes(indices) {
        if (!indices || indices.length === 0) return;
        const total = this.state.scenes ? this.state.scenes.length : 0;
        if (indices.length >= total) {
            this._setStatus('不允许删除全部场次');
            return;
        }
        const confirmed = confirm(`确认删除 ${indices.length} 个场次？其内容将合并到相邻场次，此操作可撤销。`);
        if (!confirmed) return;

        const data = await this._apiJson('/api/scenes/delete', { indices });
        if (data) {
            // If deleted scene was selected, clear selection
            if (indices.includes(Panels.selectedScene)) {
                Panels.selectedScene = -1;
            }
            // Exit selection mode after batch delete
            if (Panels.selectionMode) {
                Panels.selectionMode = false;
                Panels.selectedIndices.clear();
                document.getElementById('batch-actions').classList.remove('visible');
                document.getElementById('btn-select-mode').textContent = '选择';
            }
            this._applyState(data);
        }
    },

    // ── Project Management ────────────────────────────────────────

    async listProjects() {
        const data = await this._api('/api/projects');
        return data ? data.projects : [];
    },

    async createProject(name) {
        const data = await this._apiJson('/api/projects', { name });
        if (data) {
            this._applyState(data);
            this._closeProjectDialog();
        }
    },

    async openProject(id) {
        this._showSpinner(true);
        const data = await this._api(`/api/projects/${id}/open`, { method: 'POST' });
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
            this._closeProjectDialog();
        }
    },

    async deleteProject(id) {
        // Only delete if it's not the current project, or handle accordingly
        if (!confirm('确认删除此项目？所有数据将被永久删除。')) return;

        // If deleting current project, use the current endpoint
        const currentId = this.state.project ? this.state.project.id : null;
        if (id === currentId) {
            const data = await this._api('/api/projects/current', { method: 'DELETE' });
            if (data) {
                Panels.selectedScene = -1;
                this._applyState(data);
            }
        } else {
            // Load and immediately delete
            const resp = await this._api(`/api/projects/${id}/open`, { method: 'POST' });
            if (resp) {
                const data = await this._api('/api/projects/current', { method: 'DELETE' });
                if (data) {
                    Panels.selectedScene = -1;
                    this._applyState(data);
                }
            }
        }
        // Refresh project list
        const projects = await this.listProjects();
        Panels.renderProjectList(projects);
    },

    async saveProject() {
        const data = await this._apiJson('/api/projects/current/save', {});
        if (data) this._setStatus(data.status || '已保存');
    },

    _openProjectDialog() {
        const overlay = document.getElementById('project-dialog-overlay');
        overlay.style.display = 'flex';
        this.listProjects().then(projects => Panels.renderProjectList(projects));
    },

    _closeProjectDialog() {
        document.getElementById('project-dialog-overlay').style.display = 'none';
    },

    // ── Episode Management ────────────────────────────────────────

    async switchEpisode(id) {
        this._showSpinner(true);
        const data = await this._apiJson(`/api/episodes/${id}/switch`, {});
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
            // Refresh episode list in dialog
            if (data.project) {
                Panels.renderEpisodeList(data.project.episodes, data.project.active_episode_id);
            }
        }
    },

    async renameEpisode(id, name) {
        const data = await this._api(`/api/episodes/${id}/rename`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (data && data.project) {
            this._applyState(data);
            Panels.renderEpisodeList(data.project.episodes, data.project.active_episode_id);
        }
    },

    async deleteEpisode(id) {
        if (!confirm('确认删除此集？此操作不可撤销。')) return;
        this._showSpinner(true);
        const data = await this._api(`/api/episodes/${id}`, { method: 'DELETE' });
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
            if (data.project) {
                Panels.renderEpisodeList(data.project.episodes, data.project.active_episode_id);
            }
        }
    },

    async addEpisode(file) {
        this._showSpinner(true);
        const name = prompt('请输入集数名称:', file.name.replace(/\.[^.]+$/, ''));
        if (!name) { this._showSpinner(false); return; }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('name', name);

        const data = await this._api('/api/episodes/add', { method: 'POST', body: formData });
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
            if (data.project) {
                Panels.renderEpisodeList(data.project.episodes, data.project.active_episode_id);
            }
        }
    },

    _openEpisodeDialog() {
        const overlay = document.getElementById('episode-dialog-overlay');
        overlay.style.display = 'flex';
        if (this.state.project) {
            document.getElementById('episode-dialog-title').textContent =
                `集数管理 - ${this.state.project.name}`;
            Panels.renderEpisodeList(this.state.project.episodes, this.state.project.active_episode_id);
        }
    },

    _closeEpisodeDialog() {
        document.getElementById('episode-dialog-overlay').style.display = 'none';
    },

    // ── Scene Heading Reparse ─────────────────────────────────────

    async reparseHeading() {
        if (Panels.selectedScene < 0) return;
        const heading = document.getElementById('detail-heading').value.trim();
        const data = await this._api(`/api/scenes/${Panels.selectedScene}/reparse`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ heading }),
        });
        if (data) {
            // Update form fields with parsed values
            if (data.fields) {
                const f = data.fields;
                Panels._setSelectValue('detail-int-ext', f.int_ext || '');
                document.getElementById('detail-location').value = f.location || '';
                Panels._setSelectValue('detail-time', f.time_of_day || '');
            }
            this._applyState(data);
        }
    },

    // ── Scene Update ────────────────────────────────────────────

    async applyDetailChanges() {
        if (Panels.selectedScene < 0) return;
        const formData = Panels.getDetailFormData();
        const data = await this._api(`/api/scenes/${Panels.selectedScene}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
        });
        if (data) this._applyState(data);
    },

    // ── Export ───────────────────────────────────────────────────

    exportFile(format) {
        window.location.href = `/api/export/${format}`;
    },

    _openExportDialog() {
        document.getElementById('export-dialog-overlay').style.display = 'flex';
    },

    _closeExportDialog() {
        document.getElementById('export-dialog-overlay').style.display = 'none';
    },

    exportXlsx() {
        const chars    = document.getElementById('export-opt-characters').checked ? '1' : '0';
        const props    = document.getElementById('export-opt-props').checked      ? '1' : '0';
        const entities = document.getElementById('export-opt-entities').checked   ? '1' : '0';
        const colors   = document.getElementById('export-opt-colors').checked     ? '1' : '0';
        const params = new URLSearchParams({ chars, props, entities, colors });
        window.location.href = `/api/export/xlsx?${params}`;
        this._closeExportDialog();
    },

    // ── LLM Settings Dialog ─────────────────────────────────────

    // ── LLM Presets (all major services) ────────────────────────
    // base_url = full API base (adapter appends /chat/completions automatically)
    // Anthropic is auto-detected by URL: calls /v1/messages instead
    _LLM_PRESETS: {
        // ── 国内服务 ──────────────────────────────────
        deepseek: {
            base_url: 'https://api.deepseek.com/v1',
            models:   ['deepseek-chat', 'deepseek-reasoner'],
            hint:     '获取 API Key：platform.deepseek.com',
        },
        moonshot: {
            base_url: 'https://api.moonshot.cn/v1',
            models:   ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
            hint:     '获取 API Key：platform.moonshot.cn',
        },
        qwen: {
            base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            models:   ['qwen-turbo', 'qwen-plus', 'qwen-max', 'qwen-long', 'qwen2.5-72b-instruct'],
            hint:     '获取 API Key：dashscope.aliyun.com',
        },
        zhipu: {
            base_url: 'https://open.bigmodel.cn/api/paas/v4',
            models:   ['glm-4', 'glm-4-flash', 'glm-4-air', 'glm-3-turbo'],
            hint:     '获取 API Key：open.bigmodel.cn',
        },
        minimax: {
            base_url: 'https://api.minimax.chat/v1',
            models:   ['MiniMax-Text-01', 'abab6.5-chat', 'abab6.5s-chat'],
            hint:     '获取 API Key：platform.minimaxi.com',
        },
        yi: {
            base_url: 'https://api.lingyiwanwu.com/v1',
            models:   ['yi-lightning', 'yi-large', 'yi-medium'],
            hint:     '获取 API Key：platform.lingyiwanwu.com',
        },
        stepfun: {
            base_url: 'https://api.stepfun.com/v1',
            models:   ['step-2-16k', 'step-1-8k', 'step-1-flash'],
            hint:     '获取 API Key：platform.stepfun.com',
        },
        siliconflow: {
            base_url: 'https://api.siliconflow.cn/v1',
            models:   ['deepseek-ai/DeepSeek-V3', 'Qwen/Qwen2.5-72B-Instruct', 'meta-llama/Meta-Llama-3.1-70B-Instruct'],
            hint:     '硅基流动：聚合多家模型，按量计费。获取 API Key：cloud.siliconflow.cn',
        },
        // ── 国际服务 ──────────────────────────────────
        openai_official: {
            base_url: 'https://api.openai.com/v1',
            models:   ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o1', 'o3-mini'],
            hint:     '获取 API Key：platform.openai.com',
        },
        claude: {
            base_url: 'https://api.anthropic.com',
            models:   ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'],
            hint:     '自动使用 Anthropic 原生接口（/v1/messages）。获取 API Key：console.anthropic.com',
        },
        gemini: {
            base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
            models:   ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
            hint:     'Google Gemini OpenAI 兼容接口。获取 API Key：aistudio.google.com',
        },
        groq: {
            base_url: 'https://api.groq.com/openai/v1',
            models:   ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
            hint:     '超快推理速度。获取 API Key：console.groq.com',
        },
        mistral: {
            base_url: 'https://api.mistral.ai/v1',
            models:   ['mistral-large-latest', 'mistral-small-latest', 'open-mistral-nemo'],
            hint:     '获取 API Key：console.mistral.ai',
        },
        // ── 本地服务 ──────────────────────────────────
        ollama: {
            base_url: 'http://localhost:11434/v1',
            models:   ['llama3', 'llama3:8b', 'qwen2.5', 'deepseek-r1:7b', 'mistral', 'phi3'],
            hint:     'Ollama 本地服务（支持 OpenAI 格式 /v1）。先运行: ollama serve',
        },
    },

    _openLLMSettings() {
        const overlay = document.getElementById('llm-dialog-overlay');
        overlay.style.display = 'flex';

        const resultEl = document.getElementById('llm-test-result');
        if (resultEl) { resultEl.textContent = ''; resultEl.className = 'llm-test-result'; }

        this._api('/api/llm/config').then(cfg => {
            if (!cfg) return;
            // provider field is legacy — ignore, only use base_url/model/key
            document.getElementById('llm-api-key').value = '';
            document.getElementById('llm-model').value    = cfg.model_name || '';
            document.getElementById('llm-base-url').value = cfg.base_url   || '';
            document.getElementById('llm-temperature').value = cfg.temperature ?? 0.3;
            document.getElementById('llm-max-tokens').value  = cfg.max_tokens  || 4096;
            this._updateEndpointPreview();

            // Try to match saved base_url to a preset → populate model dropdown
            const savedUrl = (cfg.base_url || '').replace(/\/$/, '');
            let matchedPreset = null;
            if (savedUrl) {
                for (const [key, preset] of Object.entries(this._LLM_PRESETS)) {
                    if (preset.base_url.replace(/\/$/, '') === savedUrl) {
                        matchedPreset = key;
                        break;
                    }
                }
            }
            if (matchedPreset) {
                // Highlight matching preset button and populate its models
                document.querySelectorAll('.llm-preset-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.preset === matchedPreset);
                });
                this._populateModelSelect(this._LLM_PRESETS[matchedPreset].models);
                const hint = document.getElementById('llm-hint');
                if (hint) hint.textContent = '当前已保存配置，API 密钥已加密存储（留空则保留原密钥）';
            } else {
                // No preset match — show a combined common model list as fallback
                document.querySelectorAll('.llm-preset-btn').forEach(b => b.classList.remove('active'));
                const fallbackModels = [
                    'deepseek-chat', 'deepseek-reasoner',
                    'gpt-4o', 'gpt-4o-mini', 'o1', 'o3-mini',
                    'claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001',
                    'moonshot-v1-8k', 'moonshot-v1-128k',
                    'qwen-turbo', 'qwen-plus', 'qwen-max',
                    'glm-4', 'glm-4-flash',
                    'gemini-2.0-flash', 'gemini-1.5-pro',
                ];
                this._populateModelSelect(fallbackModels);
                const hint = document.getElementById('llm-hint');
                if (hint) hint.textContent = cfg.base_url
                    ? '当前已保存配置，API 密钥已加密存储（留空则保留原密钥）'
                    : '选择上方预设或手动填写 API 地址';
            }
        });
    },

    _closeLLMSettings() {
        document.getElementById('llm-dialog-overlay').style.display = 'none';
    },

    _populateModelSelect(models) {
        const sel = document.getElementById('llm-model-select');
        if (!sel) return;
        sel.innerHTML = '<option value="">常用模型 ↓</option>';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m; opt.textContent = m;
            sel.appendChild(opt);
        });
    },

    _updateEndpointPreview() {
        const preview = document.getElementById('llm-endpoint-preview');
        if (!preview) return;
        const base = (document.getElementById('llm-base-url').value || '').trim().replace(/\/$/, '');
        if (!base) { preview.textContent = ''; return; }

        let endpoint;
        if (base.toLowerCase().includes('anthropic.com')) {
            // Anthropic auto-detection: show /v1/messages endpoint
            const b = base.endsWith('/v1') ? base : base + '/v1';
            endpoint = b + '/messages';
        } else {
            endpoint = base.endsWith('/chat/completions') ? base : base + '/chat/completions';
        }
        preview.textContent = `将请求 POST ${endpoint}`;
    },

    _applyLLMPreset(presetKey) {
        const preset = this._LLM_PRESETS[presetKey];
        if (!preset) return;

        document.querySelectorAll('.llm-preset-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.preset === presetKey);
        });

        document.getElementById('llm-base-url').value = preset.base_url;
        this._updateEndpointPreview();
        this._populateModelSelect(preset.models);

        // Auto-fill first model if field is empty
        if (!document.getElementById('llm-model').value && preset.models.length) {
            document.getElementById('llm-model').value = preset.models[0];
        }

        const hint = document.getElementById('llm-hint');
        if (hint) hint.textContent = preset.hint;

        const resultEl = document.getElementById('llm-test-result');
        if (resultEl) { resultEl.textContent = ''; resultEl.className = 'llm-test-result'; }
    },

    _getLLMDialogData() {
        return {
            provider:    'openai',   // always universal adapter
            api_key:     document.getElementById('llm-api-key').value,
            model_name:  document.getElementById('llm-model').value.trim(),
            base_url:    document.getElementById('llm-base-url').value.trim().replace(/\/$/, ''),
            temperature: parseFloat(document.getElementById('llm-temperature').value) || 0.3,
            max_tokens:  parseInt(document.getElementById('llm-max-tokens').value)   || 4096,
        };
    },

    async _saveLLMConfig() {
        const data = this._getLLMDialogData();
        if (!data.base_url) {
            alert('API 地址不能为空，请选择预设服务或手动填写地址。');
            return;
        }
        if (!data.model_name) {
            alert('模型名称不能为空。');
            return;
        }
        const result = await this._api('/api/llm/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (result && result.ok) {
            this._setStatus(`LLM 已配置 · ${data.base_url}`);
            this._closeLLMSettings();
        }
    },

    async _testLLMConnection() {
        const btn = document.getElementById('llm-test-btn');
        const resultEl = document.getElementById('llm-test-result');

        btn.disabled = true;
        btn.textContent = '测试中...';
        if (resultEl) { resultEl.textContent = ''; resultEl.className = 'llm-test-result'; }

        const data = this._getLLMDialogData();
        const result = await this._apiJson('/api/llm/test', data);

        btn.disabled = false;
        btn.textContent = '测试连接';

        if (!result) return;
        if (resultEl) {
            if (result.ok) {
                resultEl.textContent = '✓ 连接成功';
                resultEl.className = 'llm-test-result llm-test-ok';
            } else {
                resultEl.textContent = `✗ ${result.error || '连接失败，请检查配置'}`;
                resultEl.className = 'llm-test-result llm-test-error';
            }
        }
    },

    // ── Split Mode ───────────────────────────────────────────────

    toggleSplitMode() {
        this._splitMode = !this._splitMode;
        const btn = document.getElementById('btn-split-mode');
        const banner = document.getElementById('split-mode-banner');

        if (this._splitMode) {
            btn.classList.add('btn-active');
            btn.textContent = '退出拆分';
            banner.style.display = 'block';
            document.body.classList.add('split-mode');
        } else {
            btn.classList.remove('btn-active');
            btn.textContent = '拆分';
            banner.style.display = 'none';
            document.body.classList.remove('split-mode');
        }
    },

    exitSplitMode() {
        if (this._splitMode) this.toggleSplitMode();
    },

    // ── Navigate to scene ────────────────────────────────────────

    async deleteLines(lineIndices) {
        if (!lineIndices || lineIndices.length === 0) return;
        const data = await this._apiJson('/api/lines/delete', { line_indices: lineIndices });
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
        }
    },

    navigateToScene(sceneIdx) {
        Panels.selectScene(sceneIdx);
        // Scroll scene list item into view
        const sceneItem = document.querySelector(`.scene-item[data-index="${sceneIdx}"]`);
        if (sceneItem) sceneItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    // ── Location Rename ───────────────────────────────────────────

    async renameLocation(oldName, newName) {
        const data = await this._api('/api/scenes/location/rename', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_name: oldName, new_name: newName }),
        });
        if (data) this._applyState(data);
    },

    // ── Location Group Toggle ─────────────────────────────────────

    toggleGroupByLocation() {
        Panels.groupByLocation = !Panels.groupByLocation;
        Panels._collapsedGroups.clear();
        if (Panels.groupByLocation) Panels.groupByType = false;
        document.getElementById('btn-group-location').classList.toggle('btn-active', Panels.groupByLocation);
        document.getElementById('btn-group-type').classList.remove('btn-active');
        if (this.state.scenes) Panels.renderSceneList(this.state.scenes);
    },

    // ── Type Group Toggle ─────────────────────────────────────────

    toggleGroupByType() {
        Panels.groupByType = !Panels.groupByType;
        Panels._collapsedTypeGroups.clear();
        if (Panels.groupByType) Panels.groupByLocation = false;
        document.getElementById('btn-group-type').classList.toggle('btn-active', Panels.groupByType);
        document.getElementById('btn-group-location').classList.remove('btn-active');
        if (this.state.scenes) Panels.renderSceneList(this.state.scenes);
    },

    // ── Project Overview Tab ──────────────────────────────────────

    async loadProjectSummary() {
        if (!this.state.project) {
            Panels.renderProjectSummary(null);
            return;
        }
        this._showSpinner(true);
        const data = await this._api('/api/projects/summary');
        this._showSpinner(false);
        if (data) Panels.renderProjectSummary(data);
    },

    // ── Project Archive ───────────────────────────────────────────

    async exportProjectArchive() {
        try {
            const resp = await fetch('/api/projects/current/archive');
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                alert(err.error || '导出失败');
                return;
            }
            const cd = resp.headers.get('Content-Disposition') || '';
            const match = cd.match(/filename\*?=(?:UTF-8'')?(.+)/i);
            const filename = match ? decodeURIComponent(match[1].replace(/"/g, '')) : 'project.sbp';
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = filename; a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            alert('导出失败: ' + e.message);
        }
    },

    async importProjectArchive(file) {
        this._showSpinner(true);
        const formData = new FormData();
        formData.append('file', file);
        const data = await this._api('/api/projects/import', { method: 'POST', body: formData });
        this._showSpinner(false);
        if (data) {
            Panels.selectedScene = -1;
            this._applyState(data);
            this._closeProjectDialog();
        }
    },

    // ── Event Bindings ──────────────────────────────────────────

    _bindToolbar() {
        document.getElementById('btn-import').addEventListener('click', () => {
            document.getElementById('file-input').click();
        });

        document.getElementById('file-input').addEventListener('change', (e) => {
            if (e.target.files[0]) {
                this.uploadFile(e.target.files[0]);
                e.target.value = '';
            }
        });

        // Import dialog (shown when project is open)
        document.getElementById('import-as-episode-btn').addEventListener('click', async () => {
            const file = this._pendingImportFile;
            const name = document.getElementById('import-episode-name').value.trim()
                || (file ? file.name.replace(/\.[^.]+$/, '') : '');
            this._closeImportDialog();
            if (file) await this._doUpload(file, true, name);
        });
        document.getElementById('import-standalone-btn').addEventListener('click', async () => {
            const file = this._pendingImportFile;
            this._closeImportDialog();
            if (file) await this._doUpload(file, false, '');
        });
        document.getElementById('import-cancel-btn').addEventListener('click', () => {
            this._closeImportDialog();
        });
        document.getElementById('import-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'import-dialog-overlay') this._closeImportDialog();
        });

        // Episode indicator click → open episode dialog
        document.getElementById('episode-indicator').addEventListener('click', () => {
            if (this.state.project) this._openEpisodeDialog();
        });

        document.getElementById('btn-detect').addEventListener('click', () => this.autoDetect());
        document.getElementById('btn-llm-detect').addEventListener('click', () => this.llmDetect());
        document.getElementById('btn-pdf-llm').addEventListener('click', () => this.llmPdfClean());
        document.getElementById('btn-content-lock').addEventListener('click', () => this.toggleLock());
        document.getElementById('btn-edit-content').addEventListener('click', () => this.enterEditMode());
        document.getElementById('btn-save-edit').addEventListener('click', () => this.saveEditMode());
        document.getElementById('btn-cancel-edit').addEventListener('click', () => this.cancelEditMode());
        document.getElementById('btn-undo').addEventListener('click', () => this.undo());
        document.getElementById('btn-redo').addEventListener('click', () => this.redo());
        document.getElementById('btn-export-txt').addEventListener('click', () => this.exportFile('txt'));
        // CSV button now opens export dialog (user can choose CSV-only or multi-sheet xlsx)
        document.getElementById('btn-export-csv').addEventListener('click', () => this._openExportDialog());

        // Export dialog buttons
        document.getElementById('export-csv-simple-btn').addEventListener('click', () => {
            this._closeExportDialog();
            this.exportFile('csv');
        });
        document.getElementById('export-xlsx-btn').addEventListener('click', () => this.exportXlsx());
        document.getElementById('export-dialog-cancel-btn').addEventListener('click', () => this._closeExportDialog());
        document.getElementById('export-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'export-dialog-overlay') this._closeExportDialog();
        });
        document.getElementById('btn-split-mode').addEventListener('click', () => this.toggleSplitMode());

        // Line select mode buttons (center panel)
        document.getElementById('btn-line-select-mode').addEventListener('click', () => Panels.toggleLineSelectMode());
        document.getElementById('btn-select-all-lines').addEventListener('click', () => Panels.selectAllLines());
        document.getElementById('btn-delete-selected-lines').addEventListener('click', async () => {
            const indices = Array.from(Panels._selectedLineIndices);
            if (indices.length > 0) {
                Panels.toggleLineSelectMode();
                await this.deleteLines(indices);
            }
        });
        document.getElementById('btn-cancel-line-select').addEventListener('click', () => {
            if (Panels.lineSelectMode) Panels.toggleLineSelectMode();
        });
        document.getElementById('btn-group-location').addEventListener('click', () => this.toggleGroupByLocation());
        document.getElementById('btn-group-type').addEventListener('click', () => this.toggleGroupByType());
        document.getElementById('btn-llm-settings').addEventListener('click', () => this._openLLMSettings());

        // Project / Episode buttons
        document.getElementById('btn-project').addEventListener('click', () => this._openProjectDialog());
        document.getElementById('btn-episodes').addEventListener('click', () => this._openEpisodeDialog());
        document.getElementById('btn-save-project').addEventListener('click', () => this.saveProject());

        // Project dialog
        document.getElementById('btn-create-project').addEventListener('click', () => {
            const name = document.getElementById('new-project-name').value.trim();
            if (name) this.createProject(name);
        });
        document.getElementById('new-project-name').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const name = document.getElementById('new-project-name').value.trim();
                if (name) this.createProject(name);
            }
        });
        document.getElementById('project-close-btn').addEventListener('click', () => this._closeProjectDialog());
        document.getElementById('project-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'project-dialog-overlay') this._closeProjectDialog();
        });

        // Project archive: export + import
        document.getElementById('btn-export-project').addEventListener('click', () => this.exportProjectArchive());
        document.getElementById('btn-import-project').addEventListener('click', () => {
            document.getElementById('project-archive-input').click();
        });
        document.getElementById('project-archive-input').addEventListener('change', (e) => {
            if (e.target.files[0]) {
                this.importProjectArchive(e.target.files[0]);
                e.target.value = '';
            }
        });

        // Episode dialog
        document.getElementById('episode-close-btn').addEventListener('click', () => this._closeEpisodeDialog());
        document.getElementById('episode-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'episode-dialog-overlay') this._closeEpisodeDialog();
        });
        document.getElementById('btn-add-episode').addEventListener('click', () => {
            document.getElementById('episode-file-input').click();
        });
        document.getElementById('episode-file-input').addEventListener('change', (e) => {
            if (e.target.files[0]) {
                this.addEpisode(e.target.files[0]);
                e.target.value = '';
            }
        });

        // Scene selection mode
        document.getElementById('btn-select-mode').addEventListener('click', () => {
            Panels.toggleSelectionMode();
        });
        document.getElementById('btn-select-all').addEventListener('click', () => {
            if (this.state.scenes) {
                this.state.scenes.forEach((_, i) => Panels.selectedIndices.add(i));
                Panels.renderSceneList(this.state.scenes);
                Panels.selectedIndices = new Set(this.state.scenes.map((_, i) => i));
                Panels._updateBatchCount();
            }
        });
        document.getElementById('btn-deselect-all').addEventListener('click', () => {
            Panels.selectedIndices.clear();
            if (this.state.scenes) Panels.renderSceneList(this.state.scenes);
            Panels._updateBatchCount();
        });
        document.getElementById('btn-cancel-select').addEventListener('click', () => {
            if (Panels.selectionMode) Panels.toggleSelectionMode();
        });
        document.getElementById('btn-delete-selected').addEventListener('click', () => {
            const indices = Array.from(Panels.selectedIndices);
            this.deleteScenes(indices);
        });

        // Toolbar quick project archive buttons
        document.getElementById('btn-export-project-quick').addEventListener('click', () => this.exportProjectArchive());
        document.getElementById('btn-import-project-quick').addEventListener('click', () => {
            document.getElementById('project-archive-input-quick').click();
        });
        document.getElementById('project-archive-input-quick').addEventListener('change', (e) => {
            if (e.target.files[0]) {
                this.importProjectArchive(e.target.files[0]);
                e.target.value = '';
            }
        });
    },

    // ── Episode Synopsis ─────────────────────────────────────────

    async saveSynopsis() {
        const ta = document.getElementById('synopsis-textarea');
        if (!ta) return;
        const synopsis = ta.value;
        await this._api('/api/episodes/current/synopsis', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ synopsis }),
        });
        this.state.episode_synopsis = synopsis;
        this._setStatus('梗概已保存');
    },

    async generateSynopsis() {
        this._showSpinner(true);
        const data = await this._apiJson('/api/episodes/current/synopsis/generate', {});
        if (data && data.status === 'running') {
            this._startPolling();
        } else {
            this._showSpinner(false);
        }
    },

    _bindDetail() {
        document.getElementById('btn-apply').addEventListener('click', () => this.applyDetailChanges());
        document.getElementById('btn-reparse').addEventListener('click', () => this.reparseHeading());
        document.getElementById('btn-back-to-episode').addEventListener('click', () => {
            Panels.clearDetail();
        });
        document.getElementById('btn-summarize').addEventListener('click', () => {
            if (Panels.selectedScene >= 0) {
                this.llmSummarize(Panels.selectedScene);
            }
        });

        // 拍摄时长
        document.getElementById('btn-refresh-duration').addEventListener('click', () => {
            if (Panels.selectedScene >= 0) this.refreshSceneDuration(Panels.selectedScene);
        });
        document.getElementById('btn-save-duration').addEventListener('click', () => {
            if (Panels.selectedScene >= 0) this.saveDurationOverride(Panels.selectedScene);
        });
        // Synopsis section
        document.getElementById('btn-generate-synopsis').addEventListener('click', () => this.generateSynopsis());
        document.getElementById('btn-save-synopsis').addEventListener('click', () => this.saveSynopsis());

        // Auto-save synopsis on blur
        document.getElementById('synopsis-textarea').addEventListener('blur', () => this.saveSynopsis());

        // Toggle synopsis body
        document.getElementById('btn-toggle-synopsis').addEventListener('click', () => {
            const body = document.getElementById('synopsis-body');
            const btn  = document.getElementById('btn-toggle-synopsis');
            if (!body || !btn) return;
            const collapsed = body.style.display === 'none';
            body.style.display = collapsed ? '' : 'none';
            btn.textContent = collapsed ? '收起' : '展开';
        });
    },

    _bindLLMDialog() {
        // Live endpoint preview while user types the base URL
        document.getElementById('llm-base-url').addEventListener('input', () => {
            this._updateEndpointPreview();
        });

        // Preset buttons (delegated on container)
        document.getElementById('llm-preset-section').addEventListener('click', (e) => {
            const btn = e.target.closest('.llm-preset-btn');
            if (btn) this._applyLLMPreset(btn.dataset.preset);
        });

        // Model dropdown → fill text input
        document.getElementById('llm-model-select').addEventListener('change', (e) => {
            if (e.target.value) {
                document.getElementById('llm-model').value = e.target.value;
                e.target.value = '';
            }
        });

        document.getElementById('llm-ok-btn').addEventListener('click', () => this._saveLLMConfig());
        document.getElementById('llm-cancel-btn').addEventListener('click', () => this._closeLLMSettings());
        document.getElementById('llm-test-btn').addEventListener('click', () => this._testLLMConnection());

        document.getElementById('llm-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'llm-dialog-overlay') this._closeLLMSettings();
        });
    },

    _bindPrefsDialog() {
        document.getElementById('btn-prefs-settings').addEventListener('click', () => this._openPrefsDialog());
        document.getElementById('prefs-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'prefs-dialog-overlay') this._closePrefsDialog();
        });
        document.getElementById('dp2-save').addEventListener('click', () => this._saveDurationParamsFromDialog());
        document.getElementById('dp2-cancel').addEventListener('click', () => this._closePrefsDialog());
        document.getElementById('dp2-reset').addEventListener('click', async () => {
            if (!confirm('恢复所有时长参数为系统默认值？')) return;
            await fetch('/api/schedule/duration-params', {
                method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})
            });
            window._dpParamsCache = null;
            await this._loadDurationParamsToDialog();
            document.dispatchEvent(new CustomEvent('scene-types-updated'));
        });
        document.getElementById('dp2-add-custom-type').addEventListener('click', () => this._addPrefsCustomType());

        // 自定义类型变更后，刷新场景类型下拉框选项
        document.addEventListener('scene-types-updated', () => {
            // 刷新详情面板的 scene-type 选项
            if (Panels.selectedScene >= 0) {
                const scene = (this.state.scenes || [])[Panels.selectedScene];
                const sceneType = scene ? (scene.scene_type || '') : '';
                Panels._populateSceneTypeSelect(document.getElementById('detail-scene-type'), sceneType);
                // 同步刷新分析面板
                const ent = (this.state.entities || {})[Panels.selectedScene];
                if (ent) Panels._renderAnalysisClassification(ent.classification, ent.scene_type_key);
                Panels._updateSceneAnalysis(Panels.selectedScene);
            }
        });
    },

    _openPrefsDialog() {
        document.getElementById('prefs-dialog-overlay').style.display = 'flex';
        this._loadDurationParamsToDialog();
    },

    _closePrefsDialog() {
        document.getElementById('prefs-dialog-overlay').style.display = 'none';
    },

    async _loadDurationParamsToDialog() {
        try {
            const r = await fetch('/api/schedule/duration-params');
            if (!r.ok) return;
            const p = await r.json();
            window._dpParamsCache = p;

            const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
            set('dp2-lines-per-page',   p.lines_per_page   || 30);
            set('dp2-min-pages',        p.min_pages        || 0.125);
            set('dp2-transition-base',  p.transition_base  || 40);

            // 项目类型（genre_key）选择
            const genreSel = document.getElementById('dp2-genre-key');
            const genreFactorEl = document.getElementById('dp2-genre-factor');
            if (genreSel) {
                genreSel.innerHTML = '';
                Object.entries(p.table_b || {}).forEach(([key, entry]) => {
                    const lbl = typeof entry === 'object' ? (entry.label || key) : key;
                    const fac = typeof entry === 'object' ? (entry.factor || 1) : 1;
                    const opt = document.createElement('option');
                    opt.value = key;
                    opt.textContent = `${lbl}（×${fac}）`;
                    if (key === (p.genre_key || 'B1_现代都市')) opt.selected = true;
                    genreSel.appendChild(opt);
                });
                const updateFactor = () => {
                    const cur = p.table_b && p.table_b[genreSel.value];
                    if (genreFactorEl) genreFactorEl.textContent = cur ? `系数 ×${cur.factor}` : '';
                };
                genreSel.onchange = updateFactor;
                updateFactor();
            }

            // 表A
            const bodyA = document.getElementById('dp2-table-a-body');
            if (bodyA) {
                bodyA.innerHTML = '';
                Object.entries(p.table_a || {}).forEach(([key, entry]) => {
                    const lbl  = typeof entry === 'object' ? (entry.label || key) : key;
                    const mins = typeof entry === 'object' ? (entry.minutes || 0) : entry;
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid #f0f4f8';
                    tr.innerHTML = `
                        <td style="padding:4px 8px;font-size:11px;color:#6b7280;white-space:nowrap">${lbl.replace(/&/g,'&amp;')}</td>
                        <td style="padding:4px 8px;font-size:11px;color:#374151">${key}</td>
                        <td style="padding:4px 8px;text-align:center">
                            <input type="number" value="${mins}" min="1" max="300" step="1"
                                data-a-key="${key}" style="width:60px;text-align:center;padding:2px 4px;border:1px solid #e2e8f0;border-radius:3px;font-size:12px">
                        </td>`;
                    bodyA.appendChild(tr);
                });
            }

            // 表B
            const bodyB = document.getElementById('dp2-table-b-body');
            if (bodyB) {
                bodyB.innerHTML = '';
                Object.entries(p.table_b || {}).forEach(([key, entry]) => {
                    const lbl    = typeof entry === 'object' ? (entry.label || key) : key;
                    const factor = typeof entry === 'object' ? (entry.factor || 1) : entry;
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid #f0f4f8';
                    tr.innerHTML = `
                        <td style="padding:4px 8px;font-size:11px;color:#6b7280;white-space:nowrap">${lbl.replace(/&/g,'&amp;')}</td>
                        <td style="padding:4px 8px;font-size:11px;color:#374151">${key}</td>
                        <td style="padding:4px 8px;text-align:center">
                            <input type="number" value="${factor}" min="0.1" max="5" step="0.05"
                                data-b-key="${key}" style="width:60px;text-align:center;padding:2px 4px;border:1px solid #e2e8f0;border-radius:3px;font-size:12px">
                        </td>`;
                    bodyB.appendChild(tr);
                });
            }

            // 表C
            const bodyC = document.getElementById('dp2-table-c-body');
            if (bodyC) {
                bodyC.innerHTML = '';
                Object.entries(p.table_c || {}).forEach(([key, entry]) => {
                    const lbl  = typeof entry === 'object' ? (entry.label || key)  : key;
                    const mins = typeof entry === 'object' ? (entry.minutes || 0)  : entry;
                    const note = typeof entry === 'object' ? (entry.note   || '')  : '';
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid #f0f4f8';
                    tr.innerHTML = `
                        <td style="padding:4px 8px;font-size:11px;color:#6b7280;white-space:nowrap">${key}</td>
                        <td style="padding:4px 8px;font-size:11px;color:#374151">${lbl.replace(/&/g,'&amp;')}</td>
                        <td style="padding:4px 8px;text-align:center">
                            <input type="number" value="${mins}" min="0" max="600" step="5"
                                data-c-key="${key}" style="width:60px;text-align:center;padding:2px 4px;border:1px solid #e2e8f0;border-radius:3px;font-size:12px">
                        </td>
                        <td style="padding:4px 8px;font-size:11px;color:#9ca3af">${note.replace(/&/g,'&amp;')}</td>`;
                    bodyC.appendChild(tr);
                });
            }
            // 自定义类型列表
            this._renderPrefsCustomTypes(p);
        } catch (e) {
            console.warn('load duration params failed', e);
        }
    },

    _renderPrefsCustomTypes(p) {
        const list = document.getElementById('dp2-custom-types-list');
        if (!list) return;
        const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const custom = p.custom_scene_types || {};
        list.innerHTML = '';
        if (!Object.keys(custom).length) {
            list.innerHTML = '<div style="font-size:12px;color:#aaa;padding:4px 0">暂无自定义类型，可在下方添加</div>';
            return;
        }
        Object.entries(custom).forEach(([key, entry]) => {
            const lbl  = typeof entry === 'object' ? (entry.label || key) : key;
            const mins = typeof entry === 'object' ? (entry.minutes || 0) : entry;
            const kws  = typeof entry === 'object' ? (entry.keywords || []).join('、') : '';
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #f3f4f6;font-size:12px';
            row.innerHTML = `
                <span style="color:#6b7280;white-space:nowrap;min-width:90px;font-size:11px">${esc(key)}</span>
                <span style="flex:1;color:#374151">${esc(lbl)}</span>
                <span style="color:#888;white-space:nowrap">${mins} 分</span>
                ${kws ? `<span style="color:#9ca3af;font-size:11px;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(kws)}">${esc(kws)}</span>` : ''}
                <button data-del-key="${esc(key)}" style="padding:1px 8px;font-size:11px;border:1px solid #fca5a5;background:#fff;color:#ef4444;border-radius:3px;cursor:pointer;white-space:nowrap">删除</button>`;
            row.querySelector('[data-del-key]').addEventListener('click', async () => {
                await fetch('/api/schedule/custom-scene-types', {
                    method: 'DELETE', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({key}),
                });
                await this._loadDurationParamsToDialog();
                document.dispatchEvent(new CustomEvent('scene-types-updated'));
            });
            list.appendChild(row);
        });
    },

    async _addPrefsCustomType() {
        const esc = s => String(s || '');
        const key   = (document.getElementById('dp2-new-type-key')?.value || '').trim();
        const label = (document.getElementById('dp2-new-type-label')?.value || '').trim();
        const mins  = parseInt(document.getElementById('dp2-new-type-minutes')?.value) || 20;
        const kwStr = (document.getElementById('dp2-new-type-keywords')?.value || '').trim();
        if (!key) { this._showStatus('请填写类型键（如 AX_水下戏）'); return; }
        const body = { key, label: label || key, minutes: mins };
        if (kwStr) body.keywords = kwStr.split(/[,，\s]+/).filter(Boolean);
        try {
            const r = await fetch('/api/schedule/custom-scene-types', {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
            });
            if (r.ok) {
                document.getElementById('dp2-new-type-key').value = '';
                document.getElementById('dp2-new-type-label').value = '';
                document.getElementById('dp2-new-type-keywords').value = '';
                await this._loadDurationParamsToDialog();
                document.dispatchEvent(new CustomEvent('scene-types-updated'));
                this._showStatus(`已添加自定义类型: ${key}`);
            } else {
                const err = await r.json().catch(() => ({}));
                this._showStatus('添加失败: ' + (err.error || r.status));
            }
        } catch (e) {
            this._showStatus('添加出错: ' + e.message);
        }
    },

    async _saveDurationParamsFromDialog() {
        const p = window._dpParamsCache ? JSON.parse(JSON.stringify(window._dpParamsCache)) : {};
        const g = id => { const el = document.getElementById(id); return el ? el.value : null; };
        p.lines_per_page  = parseFloat(g('dp2-lines-per-page'))  || 30;
        p.min_pages       = parseFloat(g('dp2-min-pages'))       || 0.125;
        p.transition_base = parseInt(g('dp2-transition-base'))   || 40;
        // 项目类型
        const genreSel = document.getElementById('dp2-genre-key');
        if (genreSel && genreSel.value) p.genre_key = genreSel.value;

        // 读取表A修改
        document.querySelectorAll('#dp2-table-a-body input[data-a-key]').forEach(inp => {
            const key = inp.dataset.aKey;
            if (p.table_a && p.table_a[key]) p.table_a[key].minutes = parseInt(inp.value) || p.table_a[key].minutes;
        });
        // 读取表B修改
        document.querySelectorAll('#dp2-table-b-body input[data-b-key]').forEach(inp => {
            const key = inp.dataset.bKey;
            if (p.table_b && p.table_b[key]) p.table_b[key].factor = parseFloat(inp.value) || p.table_b[key].factor;
        });
        // 读取表C修改
        document.querySelectorAll('#dp2-table-c-body input[data-c-key]').forEach(inp => {
            const key = inp.dataset.cKey;
            if (p.table_c && p.table_c[key]) p.table_c[key].minutes = parseInt(inp.value) || p.table_c[key].minutes;
        });

        try {
            const r = await fetch('/api/schedule/duration-params', {
                method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(p)
            });
            if (r.ok) {
                window._dpParamsCache = p;
                document.dispatchEvent(new CustomEvent('scene-types-updated'));
                this._closePrefsDialog();
                this._showStatus('时长参数已保存');
            }
        } catch (e) {
            this._showStatus('保存失败: ' + e.message);
        }
    },

    _bindTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;

                // "总览" opens as a separate page
                if (tab === 'overview') {
                    window.open('/overview', '_blank');
                    return;
                }

                // Update button states
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Show/hide tab content
                document.querySelectorAll('.tab-content').forEach(tc => {
                    tc.style.display = tc.dataset.tab === tab ? '' : 'none';
                });
            });
        });
    },

    _bindSummaryExport() {
        document.getElementById('btn-export-summary').addEventListener('click', () => {
            window.location.href = '/api/export/xlsx?chars=1&props=1&entities=1&colors=1';
        });
    },

    _bindAnalysis() {
        document.getElementById('btn-extract-scene').addEventListener('click', () => {
            if (Panels.selectedScene >= 0) {
                this.extractScene(Panels.selectedScene);
            }
        });

        document.getElementById('btn-extract-all').addEventListener('click', () => {
            this.extractAll();
        });

        // 场景制作类型识别
        document.getElementById('btn-classify-scene').addEventListener('click', () => {
            if (Panels.selectedScene >= 0) this.classifySceneType(Panels.selectedScene);
        });
        document.getElementById('btn-classify-scene-inline') && document.getElementById('btn-classify-scene-inline').addEventListener('click', () => {
            if (Panels.selectedScene >= 0) this.classifySceneType(Panels.selectedScene);
        });
        document.getElementById('btn-classify-all').addEventListener('click', () => {
            this.classifyAllScenes();
        });

        // 手动覆盖制作分类（分析面板下拉）
        document.getElementById('scene-type-key-display') && document.getElementById('scene-type-key-display').addEventListener('change', (e) => {
            if (e.target.classList.contains('scene-type-key-override')) {
                if (Panels.selectedScene >= 0) this.saveTypeKeyOverride(Panels.selectedScene, e.target.value);
            }
        });

        document.getElementById('btn-analyze-all').addEventListener('click', () => {
            this.analyzeAllCharacters();
        });

        // Return to global overview from per-scene view
        document.getElementById('btn-back-analysis').addEventListener('click', () => {
            document.getElementById('analysis-scene-section').style.display = 'none';
            document.getElementById('analysis-empty').style.display = 'block';
        });

        // Collapse/expand global analysis text
        document.getElementById('btn-toggle-analysis').addEventListener('click', () => {
            const ta  = document.getElementById('global-analysis-text');
            const btn = document.getElementById('btn-toggle-analysis');
            const isHidden = ta.style.display === 'none';
            ta.style.display = isHidden ? '' : 'none';
            btn.textContent  = isHidden ? '收起' : '展开';
        });

        // Merge dialogs
        document.getElementById('btn-merge-chars').addEventListener('click', () => {
            this._openMergeDialog('character');
        });
        document.getElementById('btn-merge-props').addEventListener('click', () => {
            this._openMergeDialog('prop');
        });
        document.getElementById('merge-confirm-btn').addEventListener('click', () => {
            this._confirmMerge();
        });
        document.getElementById('merge-cancel-btn').addEventListener('click', () => {
            this._closeMergeDialog();
        });
        document.getElementById('merge-dialog-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'merge-dialog-overlay') this._closeMergeDialog();
        });
    },

    _bindKeyboard() {
        document.addEventListener('keydown', (e) => {
            // Escape: exit edit mode / split mode / line-select mode
            if (e.key === 'Escape') {
                if (this._editMode) {
                    this.cancelEditMode();
                    return;
                }
                this.exitSplitMode();
                if (Panels.lineSelectMode) Panels.toggleLineSelectMode();
            }

            // Don't intercept when typing in inputs
            const tag = e.target.tagName;
            const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

            if (e.ctrlKey || e.metaKey) {
                switch (e.key.toLowerCase()) {
                    case 'o':
                        e.preventDefault();
                        document.getElementById('file-input').click();
                        break;
                    case 'd':
                        if (!isInput) {
                            e.preventDefault();
                            if (!document.getElementById('btn-detect').disabled) this.autoDetect();
                        }
                        break;
                    case 'l':
                        if (!isInput) {
                            e.preventDefault();
                            if (!document.getElementById('btn-llm-detect').disabled) this.llmDetect();
                        }
                        break;
                    case 'e':
                        if (!isInput) {
                            e.preventDefault();
                            if (!document.getElementById('btn-export-txt').disabled) this.exportFile('txt');
                        }
                        break;
                    case 'b':
                        if (!isInput) {
                            e.preventDefault();
                            if (!document.getElementById('btn-split-mode').disabled) this.toggleSplitMode();
                        }
                        break;
                    case 'z':
                        if (!isInput) {
                            e.preventDefault();
                            if (e.shiftKey) {
                                if (!document.getElementById('btn-redo').disabled) this.redo();
                            } else {
                                if (!document.getElementById('btn-undo').disabled) this.undo();
                            }
                        }
                        break;
                    case 's':
                        e.preventDefault();
                        if (!document.getElementById('btn-save-project').disabled) this.saveProject();
                        break;
                }
            }

            // Arrow keys to navigate scenes (when not in input)
            if (!isInput && this.state.scenes && this.state.scenes.length > 0) {
                if (e.key === 'ArrowUp' && Panels.selectedScene > 0) {
                    e.preventDefault();
                    Panels.selectScene(Panels.selectedScene - 1);
                } else if (e.key === 'ArrowDown' && Panels.selectedScene < this.state.scenes.length - 1) {
                    e.preventDefault();
                    Panels.selectScene(Panels.selectedScene + 1);
                }
            }
        });
    },

    // ── Panel Resize ────────────────────────────────────────────

    _bindResize() {
        const handles = document.querySelectorAll('.resize-handle');
        handles.forEach(handle => {
            let startX, leftW, rightW, leftPanel, rightPanel;

            const onMouseMove = (e) => {
                const dx = e.clientX - startX;
                const container = document.getElementById('main');
                const totalW = container.offsetWidth;
                const newLeftW = Math.max(120, Math.min(leftW + dx, totalW - 120));
                const newRightW = Math.max(120, rightW - dx);

                leftPanel.style.width = newLeftW + 'px';
                leftPanel.style.flex = 'none';
                rightPanel.style.width = newRightW + 'px';
                if (rightPanel.id !== 'panel-center') {
                    rightPanel.style.flex = 'none';
                }
            };

            const onMouseUp = () => {
                handle.classList.remove('active');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            };

            handle.addEventListener('mousedown', (e) => {
                e.preventDefault();
                startX = e.clientX;
                leftPanel = document.getElementById(handle.dataset.left);
                rightPanel = document.getElementById(handle.dataset.right);
                leftW = leftPanel.offsetWidth;
                rightW = rightPanel.offsetWidth;
                handle.classList.add('active');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });
        });
    },

    // ── 拍摄时长估算 ──────────────────────────────────────────────

    async refreshSceneDuration(idx) {
        const hoursEl     = document.getElementById('detail-duration-hours');
        const breakdownEl = document.getElementById('detail-duration-breakdown');
        if (!hoursEl) return;
        hoursEl.placeholder = '计算中...';
        try {
            const r = await fetch(`/api/scenes/${idx}/duration-by-index`);
            if (!r.ok) return;
            const d = await r.json();
            const override = d.duration_override_hours;
            const displayH = override != null ? override : (d.total_hours || '');
            hoursEl.value = displayH;
            // 使用独立缓存（避免 _applyState 覆盖实体时丢失）
            if (!App._durationCache) App._durationCache = {};
            // 保留用户已编辑的 override 值
            const prevCached = App._durationCache[idx] || {};
            App._durationCache[idx] = Object.assign({}, d, {
                custom_factors: d.custom_factors || prevCached.custom_factors || [],
                _ov_a_minutes:   prevCached._ov_a_minutes,
                _ov_genre_factor: prevCached._ov_genre_factor,
                _ov_transition:  prevCached._ov_transition,
            });
            if (breakdownEl) {
                breakdownEl.innerHTML = this._renderDurationBreakdown(App._durationCache[idx], idx);
                breakdownEl.style.display = '';
                // 同步内联输入
                const inlineEl = document.getElementById('dur-total-hours-input');
                if (inlineEl) inlineEl.value = displayH;
            }
        } catch (e) {
            console.warn('duration fetch failed', e);
        } finally {
            hoursEl.placeholder = '0.0';
        }
    },

    _renderDurationBreakdown(d, idx) {
        const esc = s => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const row = (label, value) => `
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:5px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">${esc(label)}</td>
                <td style="padding:5px 10px;color:#374151">${value}</td>
            </tr>`;
        const inStyle = 'width:52px;padding:1px 4px;border:1px solid #d1d5db;border-radius:3px;font-size:11px;text-align:center;background:#fff';

        const cfIdx = idx != null ? idx : (typeof Panels !== 'undefined' && Panels.selectedScene >= 0 ? Panels.selectedScene : 0);
        const cached = (App._durationCache || {})[cfIdx] || {};

        const { pages, line_count, lines_per_page, a_minutes, a_label, a_key,
                genre_factor, genre_key, base_minutes, after_genre,
                c_factors, c_total, transition_minutes, total_minutes, total_hours,
                duration_override_hours } = d;

        // 使用缓存中的 override 值（用户可能已手动修改过）
        const dispAMin  = cached._ov_a_minutes  != null ? cached._ov_a_minutes  : a_minutes;
        const dispGFact = cached._ov_genre_factor != null ? cached._ov_genre_factor : genre_factor;
        const dispTrans = cached._ov_transition   != null ? cached._ov_transition   : (transition_minutes || 0);

        // ── 额外因子（可编辑）────────────────────────────────────────
        // 首次渲染时，将引擎计算的 c_factors 写入缓存作为初始值
        if (!cached._ov_c_factors) {
            cached._ov_c_factors = (c_factors || []).map(c => ({
                key: c.key || '', label: c.label || c.key || '', minutes: c.minutes || 0,
            }));
            App._durationCache[cfIdx] = cached;
        }
        const ovCFactors = cached._ov_c_factors;
        const ovCTotal   = ovCFactors.reduce((s, c) => s + (parseFloat(c.minutes) || 0), 0);
        const cEditRows  = ovCFactors.map((c, i) => `
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:4px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">
                    <input type="text" value="${esc(c.label || c.key)}" placeholder="名称"
                        style="width:72px;padding:1px 4px;border:1px solid #d1d5db;border-radius:3px;font-size:11px"
                        onchange="App._updateCFactor(${cfIdx}, ${i}, 'label', this.value)">
                </td>
                <td style="padding:4px 10px;color:#374151">
                    +<input type="number" value="${c.minutes}" step="1" min="0"
                        style="${inStyle}"
                        onchange="App._updateCFactor(${cfIdx}, ${i}, 'minutes', parseFloat(this.value) || 0); App._recalcDuration(${cfIdx})"
                        oninput="App._recalcDurationFromCF(${cfIdx}, ${i}, this.value)">
                    分
                    <button onclick="App._removeCFactor(${cfIdx}, ${i})"
                        style="margin-left:4px;padding:1px 5px;font-size:11px;background:#fee2e2;color:#dc2626;border:none;border-radius:3px;cursor:pointer">✕</button>
                </td>
            </tr>`).join('');
        const cHeader = `
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:4px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">额外因子</td>
                <td style="padding:4px 10px">
                    <b id="dur-c-total">${ovCTotal}</b> 分
                    <button onclick="App._addCFactor(${cfIdx})"
                        style="margin-left:8px;padding:1px 8px;font-size:11px;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;border-radius:3px;cursor:pointer">+ 添加</button>
                </td>
            </tr>${cEditRows}`;

        // ── 自定义因子（乘数，可编辑）────────────────────────────────
        const customFactors = cached.custom_factors || d.custom_factors || [];
        const cfRows = customFactors.map((f, i) => `
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:4px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">　乘数 ${i + 1}</td>
                <td style="padding:4px 10px">
                    <input type="text" value="${esc(f.name || '')}" placeholder="名称"
                        style="width:68px;padding:1px 4px;border:1px solid #d1d5db;border-radius:3px;font-size:11px"
                        onchange="App._updateCustomFactor(${cfIdx}, ${i}, 'name', this.value)">
                    <span style="color:#666;margin:0 4px">×</span>
                    <input type="number" value="${f.value != null ? f.value : 1}" step="0.01" min="0.01"
                        style="${inStyle}"
                        onchange="App._updateCustomFactor(${cfIdx}, ${i}, 'value', parseFloat(this.value)); App._recalcDuration(${cfIdx})">
                    <button onclick="App._recalcDuration(${cfIdx})"
                        style="margin-left:4px;padding:1px 6px;font-size:11px;background:#fef3c7;color:#92400e;border:1px solid #fde68a;border-radius:3px;cursor:pointer"
                        title="确认并重算合计">确认</button>
                    <button onclick="App._removeCustomFactor(${cfIdx}, ${i})"
                        style="margin-left:2px;padding:1px 5px;font-size:11px;background:#fee2e2;color:#dc2626;border:none;border-radius:3px;cursor:pointer">✕</button>
                </td>
            </tr>`).join('');
        const cfHeaderRow = `
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:4px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">自定义乘数</td>
                <td style="padding:4px 10px">
                    <button onclick="App._addCustomFactor(${cfIdx})"
                        style="padding:1px 8px;font-size:11px;background:#e0f2fe;color:#0369a1;border:none;border-radius:3px;cursor:pointer">+ 添加</button>
                    ${customFactors.length > 0
                        ? `<button onclick="App._recalcDuration(${cfIdx})"
                            style="margin-left:6px;padding:1px 8px;font-size:11px;background:#fef3c7;color:#92400e;border:1px solid #fde68a;border-radius:3px;cursor:pointer">重算合计</button>`
                        : ''}
                </td>
            </tr>${cfRows}`;

        // 合计行
        const displayHours = duration_override_hours != null ? duration_override_hours : total_hours;
        const totalRowHtml = `
            <tr style="background:#f0f7ff">
                <td style="padding:6px 10px;color:#555;white-space:nowrap;background:#dbeafe;width:90px;font-weight:600">合　计</td>
                <td style="padding:6px 10px">
                    <span id="dur-total-minutes-display" style="color:#374151;font-size:11px">${total_minutes} 分 ≈ </span>
                    <input type="number" id="dur-total-hours-input" value="${displayHours}" step="0.05" min="0" max="24"
                        style="width:62px;padding:2px 5px;border:1px solid #93c5fd;border-radius:4px;font-size:13px;font-weight:700;color:#1e40af;text-align:center"
                        oninput="document.getElementById('detail-duration-hours').value=this.value"
                        title="可直接修改覆盖估算值（保存后生效）">
                    <span style="color:#1e40af;font-weight:600;margin-left:2px">小时</span>
                    <button onclick="App.saveDurationOverride(Panels.selectedScene)"
                        style="margin-left:8px;padding:2px 10px;font-size:11px;background:#3b82f6;color:#fff;border:none;border-radius:4px;cursor:pointer">
                        保存
                    </button>
                    ${duration_override_hours != null ? `<span style="font-size:10px;color:#f59e0b;margin-left:4px">已覆盖</span>` : ''}
                </td>
            </tr>`;

        return `<table style="width:100%;border-collapse:collapse;font-size:11px;line-height:1.6">
            ${row('页数计算', `${line_count} 行 ÷ ${lines_per_page} 行/页 = <b><span id="dur-pages" data-val="${pages}">${pages}</span></b> 页`)}
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:5px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">基础时长</td>
                <td style="padding:5px 10px;color:#374151">
                    ${pages} 页 ×
                    <input type="number" id="dur-a-minutes" value="${dispAMin}" step="0.5" min="0"
                        style="${inStyle}" oninput="App._recalcDuration(${cfIdx})"
                        title="分钟/页（可修改）">
                    分/页（${esc(a_label || a_key)}）= <b id="dur-base-minutes">${base_minutes}</b> 分
                </td>
            </tr>
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:5px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">类型系数</td>
                <td style="padding:5px 10px;color:#374151">
                    ×
                    <input type="number" id="dur-genre-factor" value="${dispGFact}" step="0.05" min="0"
                        style="${inStyle}" oninput="App._recalcDuration(${cfIdx})"
                        title="项目类型系数（可修改）">
                    （${esc(genre_key)}）→ <b id="dur-after-genre">${after_genre}</b> 分
                </td>
            </tr>
            ${cHeader}
            <tr style="border-bottom:1px solid #f0f4f8">
                <td style="padding:5px 10px;color:#888;white-space:nowrap;background:#f8fafc;width:90px">转场时间</td>
                <td style="padding:5px 10px;color:#374151">
                    +<input type="number" id="dur-transition" value="${dispTrans}" step="1" min="0"
                        style="${inStyle}" oninput="App._recalcDuration(${cfIdx})"
                        title="转场时间（分钟，可修改）"> 分
                </td>
            </tr>
            ${cfHeaderRow}
            ${totalRowHtml}
        </table>`;
    },

    async saveDurationOverride(idx) {
        // 优先读取表格内联输入，回退到独立输入框
        const inlineEl = document.getElementById('dur-total-hours-input');
        const hoursEl  = document.getElementById('detail-duration-hours');
        if (!hoursEl && !inlineEl) return;
        const val = (inlineEl || hoursEl).value.trim();
        // 同步两个输入
        if (inlineEl) inlineEl.value = val;
        if (hoursEl)  hoursEl.value  = val;
        const hours = val === '' ? null : parseFloat(val);
        // 读取当前缓存中的自定义因子和用户编辑值
        this._saveDurEdits(idx);
        const cached = (App._durationCache || {})[idx] || {};
        const custom_factors = cached.custom_factors || [];
        const data = await this._api(`/api/scenes/${idx}/duration-override`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration_override_hours: hours, custom_factors }),
        });
        if (data) {
            this._applyState(data);
            await this.refreshSceneDuration(idx);
            this._showStatus(hours != null ? `时长已设为 ${hours}h` : '已清除手动时长');
        }
    },

    // ── 自定义因子 + 实时重算 ─────────────────────────────────────

    /** 客户端实时重算时长（读取表格中的可编辑输入值）。*/
    _recalcDuration(idx) {
        const pagesEl = document.getElementById('dur-pages');
        const aMinEl  = document.getElementById('dur-a-minutes');
        const gFctEl  = document.getElementById('dur-genre-factor');
        const transEl = document.getElementById('dur-transition');
        if (!aMinEl) return;

        const pages  = parseFloat(pagesEl?.dataset.val || 0);
        const aMin   = parseFloat(aMinEl.value) || 0;
        const gFact  = parseFloat(gFctEl?.value) || 1;
        const trans  = parseFloat(transEl?.value) || 0;

        // 保存 override 到缓存（下次重渲染时保留用户值）
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        cached._ov_a_minutes    = aMin;
        cached._ov_genre_factor = gFact;
        cached._ov_transition   = trans;
        App._durationCache[idx] = cached;

        // 额外因子：优先用缓存中的可编辑版本
        const ovCF   = cached._ov_c_factors || cached.c_factors || [];
        const cTotal = ovCF.reduce((s, c) => s + (parseFloat(c.minutes) || 0), 0);
        // 同步更新额外因子合计显示
        const cTotalEl = document.getElementById('dur-c-total');
        if (cTotalEl) cTotalEl.textContent = Math.round(cTotal * 100) / 100;

        const baseMin  = Math.round(pages * aMin * 100) / 100;
        const afterGen = Math.round(baseMin * gFact * 100) / 100;
        const beforeCf = afterGen + cTotal + trans;

        // 自定义乘数因子：修复 ||1 bug（0 是有效值）
        const factors = cached.custom_factors || [];
        const cfMult  = factors.reduce((acc, f) => {
            const v = parseFloat(f.value);
            return (!isNaN(v) && v > 0) ? acc * v : acc;
        }, 1);

        const totalMin = Math.round(beforeCf * cfMult * 100) / 100;
        const totalHrs = Math.round(totalMin / 60 * 100) / 100;

        // 更新各显示元素
        const baseEl = document.getElementById('dur-base-minutes');
        const agEl   = document.getElementById('dur-after-genre');
        const tmEl   = document.getElementById('dur-total-minutes-display');
        const thEl   = document.getElementById('dur-total-hours-input');
        const hEl    = document.getElementById('detail-duration-hours');
        if (baseEl) baseEl.textContent = baseMin;
        if (agEl)   agEl.textContent   = afterGen;
        if (tmEl)   tmEl.textContent   = `${totalMin} 分 ≈ `;
        if (thEl)   thEl.value         = totalHrs;
        if (hEl)    hEl.value          = totalHrs;
    },

    /** 额外因子分钟 oninput 实时预览（先更新缓存再重算，避免等 onchange）。*/
    _recalcDurationFromCF(idx, cfI, rawVal) {
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const ovCF = cached._ov_c_factors ? [...cached._ov_c_factors] : [];
        if (ovCF[cfI]) {
            const v = parseFloat(rawVal);
            ovCF[cfI] = Object.assign({}, ovCF[cfI], { minutes: isNaN(v) ? 0 : v });
            cached._ov_c_factors = ovCF;
            App._durationCache[idx] = cached;
        }
        this._recalcDuration(idx);
    },

    /** 保存当前可编辑值到缓存（重渲染前调用以保留用户编辑）。*/
    _saveDurEdits(idx) {
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const aMin  = document.getElementById('dur-a-minutes');
        const gFact = document.getElementById('dur-genre-factor');
        const trans = document.getElementById('dur-transition');
        if (aMin)  cached._ov_a_minutes    = parseFloat(aMin.value);
        if (gFact) cached._ov_genre_factor = parseFloat(gFact.value);
        if (trans) cached._ov_transition   = parseFloat(trans.value);
        // 额外因子的分钟编辑值已由 _recalcDurationFromCF 实时写入缓存，无需再读 DOM
        App._durationCache[idx] = cached;
    },

    /** 重新渲染 breakdown 表格（保留用户编辑）。*/
    _rerenderBreakdown(idx) {
        const breakdownEl = document.getElementById('detail-duration-breakdown');
        if (!breakdownEl) return;
        const d = (App._durationCache || {})[idx];
        if (!d) return;
        breakdownEl.innerHTML = this._renderDurationBreakdown(d, idx);
        this._recalcDuration(idx);
    },

    _updateCustomFactor(idx, factorIdx, field, value) {
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const factors = Array.isArray(cached.custom_factors) ? [...cached.custom_factors] : [];
        if (factors[factorIdx]) {
            factors[factorIdx] = Object.assign({}, factors[factorIdx], { [field]: value });
        }
        cached.custom_factors = factors;
        App._durationCache[idx] = cached;
    },

    _addCustomFactor(idx) {
        this._saveDurEdits(idx);
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const factors = Array.isArray(cached.custom_factors) ? [...cached.custom_factors] : [];
        factors.push({ name: '新因子', value: 1.0 });
        cached.custom_factors = factors;
        App._durationCache[idx] = cached;
        this._rerenderBreakdown(idx);
    },

    _removeCustomFactor(idx, factorIdx) {
        this._saveDurEdits(idx);
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const factors = Array.isArray(cached.custom_factors) ? [...cached.custom_factors] : [];
        factors.splice(factorIdx, 1);
        cached.custom_factors = factors;
        App._durationCache[idx] = cached;
        this._rerenderBreakdown(idx);
    },

    // ── 额外因子（c_factors）管理 ─────────────────────────────────

    _addCFactor(idx) {
        this._saveDurEdits(idx);
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const ovCF = Array.isArray(cached._ov_c_factors) ? [...cached._ov_c_factors] : [];
        ovCF.push({ key: '', label: '自定义', minutes: 0 });
        cached._ov_c_factors = ovCF;
        App._durationCache[idx] = cached;
        this._rerenderBreakdown(idx);
    },

    _removeCFactor(idx, cfI) {
        this._saveDurEdits(idx);
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const ovCF = Array.isArray(cached._ov_c_factors) ? [...cached._ov_c_factors] : [];
        ovCF.splice(cfI, 1);
        cached._ov_c_factors = ovCF;
        App._durationCache[idx] = cached;
        this._rerenderBreakdown(idx);
    },

    _updateCFactor(idx, cfI, field, value) {
        if (!App._durationCache) App._durationCache = {};
        const cached = App._durationCache[idx] || {};
        const ovCF = Array.isArray(cached._ov_c_factors) ? [...cached._ov_c_factors] : [];
        if (ovCF[cfI]) {
            ovCF[cfI] = Object.assign({}, ovCF[cfI], { [field]: value });
        }
        cached._ov_c_factors = ovCF;
        App._durationCache[idx] = cached;
    },

    // ── 场景制作类型识别 ──────────────────────────────────────────

    async classifySceneType(idx) {
        this._showSpinner(true);
        try {
            const data = await this._apiJson(`/api/scenes/${idx}/classify-type`);
            if (data) {
                this._applyState(data);
                // 同步刷新详情面板分类显示
                if (Panels.selectedScene === idx) {
                    const ent = (this.state.entities || {})[idx];
                    Panels._renderDetailClassification(ent);
                    Panels._updateSceneAnalysis(idx);
                }
            }
        } finally {
            this._showSpinner(false);
        }
    },

    async classifyAllScenes() {
        const useLLM = document.getElementById('chk-use-llm-classify')?.checked || false;
        if (useLLM) {
            // 走 LLM 异步路径
            this.llmClassifyEpisode();
            return;
        }
        this._showSpinner(true);
        this._showStatus('批量识别场景类型...');
        try {
            const data = await this._apiJson('/api/scenes/classify-all');
            if (data) {
                this._applyState(data);
                if (Panels.selectedScene >= 0) Panels._updateSceneAnalysis(Panels.selectedScene);
                this._showStatus('全集类型识别完成');
            }
        } finally {
            this._showSpinner(false);
        }
    },

    async saveTypeKeyOverride(idx, newKey) {
        const ent = Object.assign({ characters: [], props: [], scene_type: '' },
            this.state.entities[idx] || {});
        if (ent.classification) ent.classification = Object.assign({}, ent.classification, {
            a_key: newKey, method: 'manual', confidence: 'high', detail: '用户手动指定',
        });
        ent.scene_type_key = newKey;
        const data = await this._api(`/api/entities/${idx}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(ent),
        });
        if (data) {
            this._applyState(data);
            this._showStatus(`已手动指定制作分类: ${newKey}`);
        }
    },

    // ── LLM 批量识别场景类型（全集）────────────────────────────────

    _llmClsTaskId: null,
    _llmClsTimer: null,

    async llmClassifyEpisode() {
        const progWrap = document.getElementById('classify-progress-bar-wrap');
        const progBar  = document.getElementById('classify-progress-bar');
        const progText = document.getElementById('classify-progress-text');

        if (progWrap) { progWrap.style.display = ''; progBar.style.width = '0%'; }
        if (progText) progText.textContent = '启动中...';

        try {
            const r = await fetch('/api/scenes/llm/classify-types', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            if (!r.ok) {
                const err = await r.json();
                if (progText) progText.textContent = '启动失败: ' + (err.error || r.status);
                return;
            }
            const { task_id, total } = await r.json();
            this._llmClsTaskId = task_id;
            if (progText) progText.textContent = `识别中（0/${total}）...`;

            this._llmClsTimer = setInterval(async () => {
                try {
                    const sr = await fetch(`/api/scenes/llm/classify-status/${task_id}`);
                    if (!sr.ok) return;
                    const sd = await sr.json();
                    const pct = Math.round((sd.progress || 0) / Math.max(total, 1) * 100);
                    if (progBar) progBar.style.width = pct + '%';
                    if (progText) progText.textContent = `识别中（${sd.progress || 0}/${total}）...`;

                    if (sd.status === 'done' || sd.status === 'error') {
                        clearInterval(this._llmClsTimer);
                        if (sd.status === 'done') {
                            if (progText) progText.textContent = `识别完成，共标注 ${Object.keys(sd.results || {}).length} 场`;
                            // 把结果同步到本地 state.entities
                            Object.entries(sd.results || {}).forEach(([sn, v]) => {
                                // 找到对应的本地 index
                                const scenes = this.state.scenes || [];
                                const localIdx = scenes.findIndex(s => String(s.scene_number) === String(sn));
                                if (localIdx >= 0) {
                                    const ent = this.state.entities[localIdx] || {};
                                    ent.scene_type_key = v.scene_type_key;
                                    this.state.entities[localIdx] = ent;
                                }
                            });
                            if (Panels.selectedScene >= 0) Panels._updateSceneAnalysis(Panels.selectedScene);
                        } else {
                            if (progText) progText.textContent = '识别出错: ' + (sd.error || '');
                        }
                    }
                } catch (_) {}
            }, 2000);
        } catch (e) {
            if (progText) progText.textContent = '请求失败: ' + e.message;
        }
    },
};

// ── Boot ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => App.init());
