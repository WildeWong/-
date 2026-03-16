/**
 * panels.js - Panel rendering: scene list, script view, scene detail, analysis, context menus.
 */

const Panels = {
    /** Currently selected scene index (-1 = none). */
    selectedScene: -1,

    /** Selection mode state */
    selectionMode: false,
    selectedIndices: new Set(),

    /** Group-by-location mode */
    groupByLocation: false,
    _collapsedGroups: new Set(),

    /** Group-by-type mode */
    groupByType: false,
    _collapsedTypeGroups: new Set(),

    /** Currently highlighted entity scenes (scene indices) */
    _entityHighlightScenes: new Set(),
    _entityHighlightLink: null,   // The active .entity-link element

    /** Line selection mode */
    lineSelectMode: false,
    _selectedLineIndices: new Set(),
    _lastLineClickIdx: -1,

    /** Last global_analysis string received from the server (used to detect new content). */
    _lastAnalysisFromServer: null,

    /** Set of character names whose per-character analysis is collapsed by the user. */
    _collapsedCharAnalyses: new Set(),

    /** Scene type color palette */
    _typeColors: {
        '对话': '#3b82f6', '情感': '#ec4899', '动作': '#f97316',
        '打斗': '#ef4444', '追逐': '#f59e0b', '特效': '#8b5cf6',
        '过场': '#6b7280', '群戏': '#10b981', '独白': '#a78bfa',
    },

    // ── Scene List (Left Panel) ──────────────────────────────────

    renderSceneList(scenes) {
        const container = document.getElementById('scene-list');
        const title = document.getElementById('scene-list-title');
        container.innerHTML = '';
        title.textContent = `场次列表 (${scenes.length})`;

        if (!this.selectionMode) {
            if (this.groupByLocation) {
                this._renderGroupedSceneList(scenes, container, 'location');
                return;
            }
            if (this.groupByType) {
                this._renderGroupedSceneList(scenes, container, 'type');
                return;
            }
        }

        scenes.forEach((scene, idx) => {
            if (this.selectionMode) {
                // Selection mode: add checkboxes inline
                const item = document.createElement('div');
                item.className = 'scene-item selectable';
                item.dataset.index = idx;

                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'scene-checkbox';
                cb.checked = this.selectedIndices.has(idx);
                cb.addEventListener('change', (e) => {
                    e.stopPropagation();
                    if (cb.checked) this.selectedIndices.add(idx);
                    else this.selectedIndices.delete(idx);
                    this._updateBatchCount();
                });
                item.appendChild(cb);

                let label = `${scene.scene_number}. ${scene.heading}`;
                if (label.length > 42) label = label.substring(0, 39) + '...';
                const labelEl = document.createElement('span');
                labelEl.textContent = label;
                item.appendChild(labelEl);

                if (scene.is_manually_adjusted) item.classList.add('manual-adjusted');
                else if (scene.confidence < 0.5) item.classList.add('confidence-low');
                else if (scene.confidence < 0.8) item.classList.add('confidence-mid');

                if (idx === this.selectedScene) item.classList.add('selected');

                item.addEventListener('click', (e) => {
                    if (e.target !== cb) {
                        cb.checked = !cb.checked;
                        if (cb.checked) this.selectedIndices.add(idx);
                        else this.selectedIndices.delete(idx);
                        this._updateBatchCount();
                    }
                });
                item.addEventListener('contextmenu', (e) => {
                    e.preventDefault();
                    this._showSceneListContextMenu(e, idx, scenes.length);
                });
                container.appendChild(item);
            } else {
                container.appendChild(this._makeSceneItem(scene, idx, scenes.length));
            }
        });
    },

    toggleSelectionMode() {
        this.selectionMode = !this.selectionMode;
        this.selectedIndices.clear();
        const bar = document.getElementById('batch-actions');
        const btn = document.getElementById('btn-select-mode');
        if (this.selectionMode) {
            bar.classList.add('visible');
            btn.textContent = '退出选择';
        } else {
            bar.classList.remove('visible');
            btn.textContent = '选择';
        }
        // Re-render scene list to show/hide checkboxes
        if (App.state.scenes) {
            this.renderSceneList(App.state.scenes);
        }
        this._updateBatchCount();
    },

    _updateBatchCount() {
        const n = this.selectedIndices.size;
        document.getElementById('batch-count').textContent = `已选 ${n} 项`;
        document.getElementById('btn-delete-selected').disabled = n === 0;
    },

    /** Render scene list grouped by location or scene type. */
    _renderGroupedSceneList(scenes, container, mode) {
        const byType = mode === 'type';
        const collapsedSet = byType ? this._collapsedTypeGroups : this._collapsedGroups;

        const groupMap = new Map();
        scenes.forEach((scene, idx) => {
            let key;
            if (byType) {
                key = (scene.scene_type || '').trim() || '（未分类）';
            } else {
                key = (scene.location || '').trim() || '（未知地点）';
            }
            if (!groupMap.has(key)) groupMap.set(key, []);
            groupMap.get(key).push({ scene, idx });
        });

        groupMap.forEach((items, key) => {
            const groupEl = document.createElement('div');
            groupEl.className = 'scene-group';
            if (collapsedSet.has(key)) groupEl.classList.add('collapsed');

            const color = byType ? (this._typeColors[key] || '#6b7280') : null;
            const header = document.createElement('div');
            header.className = 'scene-group-header';
            if (color) header.style.borderLeftColor = color;
            const renameBtn = !byType
                ? `<button class="btn-inline scene-location-rename-btn" data-location="${this._escapeHtml(key)}" title="重命名或合并地点（输入已有地点名可合并）" style="font-size:11px;padding:1px 6px;margin-left:6px;flex-shrink:0">改名/合并</button>`
                : '';
            header.innerHTML = `
                <span class="scene-group-toggle">▼</span>
                <span class="scene-group-name">${this._escapeHtml(key)}</span>
                <span class="scene-group-count">${items.length} 场</span>
                ${renameBtn}
            `;
            header.addEventListener('click', (e) => {
                if (e.target.classList.contains('scene-location-rename-btn')) return;
                const collapsed = groupEl.classList.toggle('collapsed');
                if (collapsed) collapsedSet.add(key);
                else collapsedSet.delete(key);
            });
            header.querySelectorAll('.scene-location-rename-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const oldName = btn.dataset.location;
                    const newName = prompt(`将地点「${oldName}」重命名为（输入已有地点名可合并）:`, oldName);
                    if (newName !== null && newName.trim() && newName.trim() !== oldName) {
                        App.renameLocation(oldName, newName.trim());
                    }
                });
            });
            groupEl.appendChild(header);

            const body = document.createElement('div');
            body.className = 'scene-group-body';
            items.forEach(({ scene, idx }) => {
                body.appendChild(this._makeSceneItem(scene, idx, scenes.length));
            });
            groupEl.appendChild(body);
            container.appendChild(groupEl);
        });
    },

    /** Create a single scene list item element. */
    _makeSceneItem(scene, idx, total) {
        const item = document.createElement('div');
        item.className = 'scene-item';
        item.dataset.index = idx;

        let label = `${scene.scene_number}. ${scene.heading}`;
        if (label.length > 40) label = label.substring(0, 37) + '...';
        const labelEl = document.createElement('span');
        labelEl.style.flex = '1';
        labelEl.style.minWidth = '0';
        labelEl.textContent = label;
        item.appendChild(labelEl);

        // Scene type badge
        if (scene.scene_type) {
            const badge = document.createElement('span');
            badge.className = 'scene-type-badge';
            badge.textContent = scene.scene_type;
            const color = this._typeColors[scene.scene_type] || '#6b7280';
            badge.style.background = color + '22';
            badge.style.color = color;
            badge.style.borderColor = color + '66';
            item.appendChild(badge);
        }

        if (scene.is_manually_adjusted) {
            item.classList.add('manual-adjusted');
        } else if (scene.confidence < 0.5) {
            item.classList.add('confidence-low');
        } else if (scene.confidence < 0.8) {
            item.classList.add('confidence-mid');
        }

        if (idx === this.selectedScene) item.classList.add('selected');

        item.addEventListener('click', () => this.selectScene(idx));
        item.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            this._showSceneListContextMenu(e, idx, total);
        });
        return item;
    },

    selectScene(index) {
        const state = App.state;
        if (!state.scenes || index < 0 || index >= state.scenes.length) return;

        this.selectedScene = index;

        // Update scene list selection (works for both flat and grouped views)
        document.querySelectorAll('.scene-item').forEach((el) => {
            el.classList.toggle('selected', parseInt(el.dataset.index) === index);
        });

        // Update script view highlighting
        this._highlightSceneInScript(index);

        // Show detail
        this.showSceneDetail(state.scenes[index], index);

        // Scroll script view to scene
        this._scrollToScene(index);

        // Update analysis panel for selected scene
        this._updateSceneAnalysis(index);
    },

    _showSceneListContextMenu(e, index, total) {
        const menu = document.getElementById('context-menu');
        const insertItem = document.getElementById('ctx-insert-break');
        const deleteItem = document.getElementById('ctx-delete-break');
        const mergeNext = document.getElementById('ctx-merge-next');
        const mergePrev = document.getElementById('ctx-merge-prev');
        const deleteScene = document.getElementById('ctx-delete-scene');
        const deleteLineItem = document.getElementById('ctx-delete-line');

        insertItem.classList.add('hidden');
        deleteItem.classList.add('hidden');
        deleteLineItem.classList.add('hidden'); // not relevant for scene list
        mergeNext.classList.toggle('hidden', index >= total - 1);
        mergePrev.classList.toggle('hidden', index <= 0);
        deleteScene.classList.toggle('hidden', total <= 1);

        mergeNext.onclick = () => {
            App.mergeScenes(index, index + 1);
            this._hideContextMenu();
        };
        mergePrev.onclick = () => {
            App.mergeScenes(index - 1, index);
            this._hideContextMenu();
        };
        deleteScene.onclick = () => {
            App.deleteScenes([index]);
            this._hideContextMenu();
        };

        this._positionMenu(menu, e.clientX, e.clientY);
    },

    // ── Script View (Center Panel) ───────────────────────────────

    renderScriptView(lines, scenes) {
        const container = document.getElementById('script-view');
        container.innerHTML = '';
        // Reset entity highlight state when script is re-rendered
        this._entityHighlightScenes.clear();
        if (this._entityHighlightLink) {
            this._entityHighlightLink.classList.remove('entity-link-active');
            this._entityHighlightLink = null;
        }

        if (!lines || lines.length === 0) return;

        // Build a lookup: line_index -> scene info
        const lineSceneMap = {};
        const breakLines = new Set();
        scenes.forEach((scene, idx) => {
            breakLines.add(scene.start_line);
            for (let i = scene.start_line; i < scene.end_line; i++) {
                lineSceneMap[i] = { scene, idx };
            }
        });

        const fragment = document.createDocumentFragment();

        lines.forEach((text, lineIdx) => {
            const row = document.createElement('div');
            row.className = 'script-line';
            row.dataset.line = lineIdx;

            // Scene separator
            if (breakLines.has(lineIdx) && lineIdx > 0) {
                row.classList.add('scene-separator');
            }

            // Highlight if in selected scene
            const info = lineSceneMap[lineIdx];
            if (info && info.idx === this.selectedScene) {
                row.classList.add('selected-scene');
            }

            // Line number
            const numEl = document.createElement('span');
            numEl.className = 'line-number';
            numEl.textContent = lineIdx + 1;
            if (breakLines.has(lineIdx)) {
                numEl.classList.add('break-line');
            }

            // Line content
            const contentEl = document.createElement('span');
            contentEl.className = 'line-content';
            const lineText = text || '\u200B'; // zero-width space for empty lines
            contentEl.dataset.originalText = lineText;
            contentEl.textContent = lineText;

            // Scene heading styling
            if (info && info.scene.start_line === lineIdx) {
                contentEl.classList.add('scene-heading');
                if (info.scene.is_manually_adjusted) {
                    contentEl.classList.add('manual-adjusted');
                } else if (info.scene.confidence < 0.5) {
                    contentEl.classList.add('confidence-low');
                } else if (info.scene.confidence < 0.8) {
                    contentEl.classList.add('confidence-mid');
                } else {
                    contentEl.classList.add('confidence-high');
                }
            }

            row.appendChild(numEl);
            row.appendChild(contentEl);

            // Left-click: split mode inserts break; line-select mode toggles selection
            row.addEventListener('click', (e) => {
                if (App._splitMode) {
                    App.insertBreak(lineIdx);
                    App.exitSplitMode();
                } else if (Panels.lineSelectMode) {
                    Panels._toggleLineSelection(lineIdx, e.shiftKey);
                }
            });

            // Right-click context menu on script lines
            row.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                this._showScriptContextMenu(e, lineIdx, breakLines);
            });

            fragment.appendChild(row);
        });

        container.appendChild(fragment);

        document.getElementById('line-info').textContent = `${lines.length} 行`;
    },

    _showScriptContextMenu(e, lineIdx, breakLines) {
        const menu = document.getElementById('context-menu');
        const insertItem = document.getElementById('ctx-insert-break');
        const deleteItem = document.getElementById('ctx-delete-break');
        const mergeNext = document.getElementById('ctx-merge-next');
        const mergePrev = document.getElementById('ctx-merge-prev');
        const deleteLineItem = document.getElementById('ctx-delete-line');

        mergeNext.classList.add('hidden');
        mergePrev.classList.add('hidden');

        if (breakLines.has(lineIdx) && lineIdx > 0) {
            // This line is a scene boundary (not the first) -> can delete break
            insertItem.classList.add('hidden');
            deleteItem.classList.remove('hidden');
            deleteItem.onclick = () => {
                App.deleteBreak(lineIdx);
                this._hideContextMenu();
            };
        } else {
            // Not a boundary -> can insert break
            deleteItem.classList.add('hidden');
            insertItem.classList.remove('hidden');
            insertItem.onclick = () => {
                App.insertBreak(lineIdx);
                this._hideContextMenu();
            };
        }

        // "删除此行" — always available on script lines
        deleteLineItem.classList.remove('hidden');
        deleteLineItem.onclick = () => {
            App.deleteLines([lineIdx]);
            this._hideContextMenu();
        };

        this._positionMenu(menu, e.clientX, e.clientY);
    },

    // ── Line Select Mode (Center Panel) ─────────────────────────

    toggleLineSelectMode() {
        this.lineSelectMode = !this.lineSelectMode;
        this._selectedLineIndices.clear();
        this._lastLineClickIdx = -1;
        const btn = document.getElementById('btn-line-select-mode');
        const banner = document.getElementById('line-select-banner');
        if (this.lineSelectMode) {
            btn.classList.add('btn-active');
            banner.classList.add('visible');
            document.body.classList.add('line-select-mode');
        } else {
            btn.classList.remove('btn-active');
            banner.classList.remove('visible');
            document.body.classList.remove('line-select-mode');
            document.querySelectorAll('.script-line.line-selected').forEach(el => {
                el.classList.remove('line-selected');
            });
        }
        this._updateLineSelectBar();
    },

    _toggleLineSelection(lineIdx, isShift) {
        if (isShift && this._lastLineClickIdx >= 0) {
            // Range select between last clicked and current
            const start = Math.min(this._lastLineClickIdx, lineIdx);
            const end = Math.max(this._lastLineClickIdx, lineIdx);
            for (let i = start; i <= end; i++) {
                this._selectedLineIndices.add(i);
            }
        } else {
            // Toggle single line
            if (this._selectedLineIndices.has(lineIdx)) {
                this._selectedLineIndices.delete(lineIdx);
            } else {
                this._selectedLineIndices.add(lineIdx);
            }
            this._lastLineClickIdx = lineIdx;
        }
        // Sync DOM classes
        document.querySelectorAll('.script-line').forEach(el => {
            const idx = parseInt(el.dataset.line);
            el.classList.toggle('line-selected', this._selectedLineIndices.has(idx));
        });
        this._updateLineSelectBar();
    },

    _updateLineSelectBar() {
        const count = this._selectedLineIndices.size;
        const infoEl = document.getElementById('line-select-info');
        const deleteBtn = document.getElementById('btn-delete-selected-lines');
        if (infoEl) infoEl.textContent = `已选 ${count} 行`;
        if (deleteBtn) deleteBtn.disabled = count === 0;
    },

    selectAllLines() {
        const total = App.state.lines ? App.state.lines.length : 0;
        for (let i = 0; i < total; i++) {
            this._selectedLineIndices.add(i);
        }
        document.querySelectorAll('.script-line').forEach(el => {
            el.classList.add('line-selected');
        });
        this._updateLineSelectBar();
    },

    _highlightSceneInScript(index) {
        document.querySelectorAll('.script-line').forEach(row => {
            const info = App.state.scenes ? App.state.scenes[index] : null;
            if (info) {
                const lineIdx = parseInt(row.dataset.line);
                row.classList.toggle('selected-scene',
                    lineIdx >= info.start_line && lineIdx < info.end_line);
            } else {
                row.classList.remove('selected-scene');
            }
        });
    },

    _scrollToScene(index) {
        const scene = App.state.scenes[index];
        if (!scene) return;
        const row = document.querySelector(`.script-line[data-line="${scene.start_line}"]`);
        if (row) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    },

    // ── Entity Highlight (Center Panel) ─────────────────────────

    /**
     * Highlight occurrences of entityName in script lines for the given scenes.
     * entityType: 'character' → yellow, 'prop' → red, 'location' → blue.
     * Toggle off if the same entity is clicked again.
     */
    highlightEntityScenes(sceneIndices, anchorEl, entityName, entityType) {
        const scenes = App.state.scenes || [];

        // Toggle off: same entity clicked again
        const isSame = anchorEl && anchorEl === this._entityHighlightLink;
        this._clearEntityHighlightDOM();

        if (isSame) {
            this._entityHighlightScenes.clear();
            this._entityHighlightLink = null;
            return;
        }

        // Apply new highlights
        this._entityHighlightScenes = new Set(sceneIndices);
        this._entityHighlightLink = anchorEl || null;

        if (anchorEl) anchorEl.classList.add('entity-link-active');

        // Determine CSS class for inline <mark>
        const hlClassMap = { character: 'text-hl-char', prop: 'text-hl-prop', location: 'text-hl-loc' };
        const hlClass = hlClassMap[entityType] || 'text-hl-char';

        // Build patterns for matching entityName
        let testPattern = null;
        let replacePattern = null;
        if (entityName) {
            const rawEscaped = entityName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            testPattern = new RegExp(rawEscaped, 'i');
            // Pattern to match within HTML-escaped text
            const htmlEscaped = this._escapeHtml(entityName).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            replacePattern = new RegExp(htmlEscaped, 'gi');
        }

        sceneIndices.forEach(sceneIdx => {
            const scene = scenes[sceneIdx];
            if (!scene) return;
            for (let line = scene.start_line; line < scene.end_line; line++) {
                const row = document.querySelector(`.script-line[data-line="${line}"]`);
                if (!row) continue;
                const contentEl = row.querySelector('.line-content');
                if (!contentEl) continue;

                if (replacePattern) {
                    // Try to match in the original (unescaped) text
                    const originalText = contentEl.dataset.originalText || contentEl.textContent;
                    if (testPattern.test(originalText)) {
                        const escapedHtml = this._escapeHtml(originalText);
                        replacePattern.lastIndex = 0;
                        contentEl.innerHTML = escapedHtml.replace(
                            replacePattern, m => `<mark class="${hlClass}">${m}</mark>`
                        );
                        row.classList.add('entity-highlight-line');
                    }
                    testPattern.lastIndex = 0;
                    replacePattern.lastIndex = 0;
                } else {
                    // Fallback: highlight whole line if no entity name provided
                    row.classList.add('entity-highlight');
                }
            }
        });

        // Highlight matching items in the left scene list
        sceneIndices.forEach(idx => {
            const sceneItem = document.querySelector(`.scene-item[data-index="${idx}"]`);
            if (sceneItem) sceneItem.classList.add('entity-highlight');
        });

        // Scroll script to first highlighted scene
        if (sceneIndices.length > 0) {
            const first = scenes[sceneIndices[0]];
            if (first) {
                const lineEl = document.querySelector(`.script-line[data-line="${first.start_line}"]`);
                if (lineEl) lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    },

    clearEntityHighlight() {
        this._clearEntityHighlightDOM();
        this._entityHighlightScenes.clear();
        this._entityHighlightLink = null;
    },

    _clearEntityHighlightDOM() {
        // Clear scene list highlights
        document.querySelectorAll('.scene-item.entity-highlight').forEach(el => {
            el.classList.remove('entity-highlight');
        });

        // Restore inline-highlighted lines
        document.querySelectorAll('.script-line.entity-highlight-line').forEach(row => {
            const contentEl = row.querySelector('.line-content');
            if (contentEl && contentEl.dataset.originalText !== undefined) {
                contentEl.textContent = contentEl.dataset.originalText;
            }
            row.classList.remove('entity-highlight-line');
        });
        // Clear any whole-line fallback highlights
        document.querySelectorAll('.script-line.entity-highlight').forEach(el => {
            el.classList.remove('entity-highlight');
        });
        if (this._entityHighlightLink) {
            this._entityHighlightLink.classList.remove('entity-link-active');
        }
    },

    // ── Scene Detail (Right Panel) ───────────────────────────────

    showSceneDetail(scene, index) {
        document.getElementById('detail-empty').style.display = 'none';
        document.getElementById('detail-episode-summary').style.display = 'none';
        document.getElementById('detail-form').style.display = 'block';

        // Update scene label in nav bar
        const sceneLabel = document.getElementById('detail-scene-label');
        if (sceneLabel) {
            const heading = scene.heading || '';
            const short = heading.length > 28 ? heading.substring(0, 25) + '…' : heading;
            sceneLabel.textContent = `场次 ${scene.scene_number}${short ? '  ' + short : ''}`;
        }

        // Show synopsis section and update its content
        const synopsisEl = document.getElementById('detail-synopsis-section');
        if (synopsisEl) {
            synopsisEl.style.display = 'block';
            const synTa = document.getElementById('synopsis-textarea');
            if (synTa) synTa.value = App.state.episode_synopsis || '';
        }

        document.getElementById('detail-num').value = scene.scene_number;
        document.getElementById('detail-heading').value = scene.heading;
        this._setSelectValue('detail-int-ext', scene.int_ext);
        document.getElementById('detail-location').value = scene.location;
        this._setSelectValue('detail-time', scene.time_of_day);
        this._populateSceneTypeSelect(document.getElementById('detail-scene-type'), scene.scene_type || '');
        document.getElementById('detail-start-line').textContent = scene.start_line + 1;
        document.getElementById('detail-end-line').textContent = scene.end_line;
        document.getElementById('detail-confidence').textContent =
            `${Math.round(scene.confidence * 100)}%`;
        document.getElementById('detail-adjusted').textContent =
            scene.is_manually_adjusted ? '是' : '否';
        document.getElementById('detail-summary').value = scene.summary || '';

        // ── 制作分类（来自 entities）────────────────────────────
        const ent = (App.state.entities || {})[index] || null;
        this._renderDetailClassification(ent);
        // 如果没有分类结果，自动触发规则引擎识别
        if (!ent || !ent.scene_type_key) {
            App.classifySceneType(index);
        }

        // ── 拍摄时长估算 ─────────────────────────────────────────
        const durSection = document.getElementById('detail-duration-section');
        if (durSection) {
            durSection.style.display = 'block';
            // 使用独立缓存（_durationCache 不受 _applyState 影响）
            const cachedDur  = App._durationCache && App._durationCache[index];
            const overrideH  = ent && ent.duration_override_hours;
            const hoursEl    = document.getElementById('detail-duration-hours');
            const breakdownEl = document.getElementById('detail-duration-breakdown');
            hoursEl.value = overrideH != null ? overrideH : (cachedDur ? (cachedDur.total_hours || '') : '');
            if (cachedDur && breakdownEl) {
                breakdownEl.innerHTML = App._renderDurationBreakdown ? App._renderDurationBreakdown(cachedDur, index) : '';
                breakdownEl.style.display = '';
            } else if (breakdownEl) {
                breakdownEl.style.display = 'none';
            }
            // 无缓存时异步获取
            if (!cachedDur) App.refreshSceneDuration(index);
        }
    },

    _renderDetailClassification(ent) {
        const row = document.getElementById('detail-type-key-row');
        if (!row) return;
        const cls = ent && ent.classification;
        if (!cls || !cls.a_key) { row.style.display = 'none'; return; }

        const CONF_STYLE = {
            high:   'background:#dcfce7;color:#166534',
            medium: 'background:#fef9c3;color:#92400e',
            low:    'background:#fee2e2;color:#991b1b',
        };
        const METH_LABEL = {
            manual: '手动', keyword: '关键词', cast_count: '演员数', attribute: '属性', default: '默认'
        };
        row.style.display = '';
        document.getElementById('detail-type-key-label').textContent =
            cls.a_key + (cls.a_label ? `（${cls.a_label}）` : '');
        const confEl = document.getElementById('detail-type-key-confidence');
        confEl.textContent = {high:'高置信', medium:'中置信', low:'低置信'}[cls.confidence] || cls.confidence;
        confEl.style.cssText = CONF_STYLE[cls.confidence] || '';
        const methEl = document.getElementById('detail-type-key-method');
        methEl.textContent = METH_LABEL[cls.method] || cls.method || '';
        methEl.style.cssText = 'background:#e0f2fe;color:#075985';
        document.getElementById('detail-type-key-detail').textContent =
            (cls.matched_keywords && cls.matched_keywords.length)
                ? `匹配关键词：${cls.matched_keywords.join('、')}`
                : (cls.detail || '');
    },

    clearDetail() {
        this.selectedScene = -1;

        // Deselect scene list items
        document.querySelectorAll('.scene-item.selected').forEach(el => el.classList.remove('selected'));

        const state = App.state;
        const summaryEl  = document.getElementById('detail-episode-summary');
        const emptyEl    = document.getElementById('detail-empty');
        const synopsisEl = document.getElementById('detail-synopsis-section');

        if (state.scenes && state.scenes.length > 0) {
            const sceneCount = state.scenes.length;
            const chars = state.global_entities?.characters || [];
            const props = state.global_entities?.props || [];
            const locMap = new Map();
            state.scenes.forEach((s, idx) => {
                const loc = (s.location || '').trim() || '（未知地点）';
                if (!locMap.has(loc)) locMap.set(loc, []);
                locMap.get(loc).push(idx);
            });

            let title = state.filename || '当前集';
            if (state.project) {
                const ep = state.project.episodes?.find(e => e.id === state.project.active_episode_id);
                if (ep) title = ep.name;
            }

            // Build summary DOM
            summaryEl.innerHTML = '';

            // Header row with collapse button
            const header = document.createElement('div');
            header.className = 'ep-summary-header';
            const titleSpan = document.createElement('span');
            titleSpan.className = 'ep-summary-title';
            titleSpan.textContent = title;
            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'btn-inline';
            toggleBtn.id = 'btn-toggle-ep-stats';
            toggleBtn.textContent = '收起';
            header.appendChild(titleSpan);
            header.appendChild(toggleBtn);
            summaryEl.appendChild(header);

            // Stats body (collapsible)
            const body = document.createElement('div');
            body.id = 'ep-stats-body';

            // Stats grid
            const grid = document.createElement('div');
            grid.className = 'episode-summary-grid';
            [
                [sceneCount, '场次'],
                [chars.length, '人物'],
                [props.length, '道具'],
                [locMap.size, '地点'],
            ].forEach(([val, label]) => {
                const stat = document.createElement('div');
                stat.className = 'episode-stat';
                stat.innerHTML = `<div class="episode-stat-value">${val}</div><div class="episode-stat-label">${label}</div>`;
                grid.appendChild(stat);
            });
            body.appendChild(grid);

            // Expandable entity lists — sorted by first scene appearance
            if (chars.length > 0) {
                const sorted = [...chars].sort((a, b) => Math.min(...a.scenes) - Math.min(...b.scenes));
                body.appendChild(this._renderEpisodeEntityList('人物', sorted, 'character'));
            }
            if (props.length > 0) {
                const sorted = [...props].sort((a, b) => Math.min(...a.scenes) - Math.min(...b.scenes));
                body.appendChild(this._renderEpisodeEntityList('道具', sorted, 'prop'));
            }
            if (locMap.size > 0) {
                const locs = [...locMap.entries()]
                    .map(([name, scenes]) => ({ name, scenes }))
                    .sort((a, b) => Math.min(...a.scenes) - Math.min(...b.scenes));
                body.appendChild(this._renderEpisodeEntityList('地点', locs, 'location'));
            }

            summaryEl.appendChild(body);

            const hint = document.createElement('div');
            hint.className = 'episode-summary-hint';
            hint.textContent = '点击左侧场次查看详情';
            summaryEl.appendChild(hint);

            // Toggle stats body
            toggleBtn.addEventListener('click', () => {
                const b = document.getElementById('ep-stats-body');
                if (!b) return;
                const collapsed = b.style.display === 'none';
                b.style.display = collapsed ? '' : 'none';
                toggleBtn.textContent = collapsed ? '收起' : '展开';
            });

            summaryEl.style.display = 'block';
            emptyEl.style.display = 'none';

            // Show synopsis section
            if (synopsisEl) {
                synopsisEl.style.display = 'block';
                const synTa = document.getElementById('synopsis-textarea');
                if (synTa) synTa.value = state.episode_synopsis || '';
            }
        } else {
            summaryEl.style.display = 'none';
            emptyEl.style.display = 'block';
            if (synopsisEl) synopsisEl.style.display = 'none';
        }

        document.getElementById('detail-form').style.display = 'none';

        // Also clear scene-level analysis
        document.getElementById('analysis-scene-section').style.display = 'none';
        document.getElementById('analysis-empty').style.display = 'block';
    },

    /** Render a collapsible entity list section for the episode summary card. */
    _renderEpisodeEntityList(label, items, type) {
        const section = document.createElement('div');
        section.className = 'ep-entity-section';

        const sectionHeader = document.createElement('div');
        sectionHeader.className = 'ep-entity-header';
        sectionHeader.innerHTML = `
            <span class="ep-entity-label">${label} <span class="ep-entity-count">(${items.length})</span></span>
            <span class="ep-entity-toggle">▶</span>
        `;

        const list = document.createElement('div');
        list.className = 'ep-entity-list';
        list.style.display = 'none';  // start collapsed

        items.forEach(item => {
            const tag = document.createElement('span');
            tag.className = 'ep-entity-item entity-link';
            tag.textContent = item.name;
            tag.title = `点击高亮场次（共 ${item.scenes.length} 场）`;
            tag.addEventListener('click', () => {
                this.highlightEntityScenes(item.scenes, tag, item.name, type);
            });
            list.appendChild(tag);
        });

        sectionHeader.addEventListener('click', () => {
            const collapsed = list.style.display === 'none';
            list.style.display = collapsed ? '' : 'none';
            sectionHeader.querySelector('.ep-entity-toggle').textContent = collapsed ? '▼' : '▶';
        });

        section.appendChild(sectionHeader);
        section.appendChild(list);
        return section;
    },

    updateSummaryField(summary) {
        document.getElementById('detail-summary').value = summary;
    },

    getDetailFormData() {
        return {
            heading: document.getElementById('detail-heading').value,
            int_ext: document.getElementById('detail-int-ext').value,
            location: document.getElementById('detail-location').value,
            time_of_day: document.getElementById('detail-time').value,
            scene_type: document.getElementById('detail-scene-type').value,
            summary: document.getElementById('detail-summary').value,
        };
    },

    _setSelectValue(id, value) {
        const select = document.getElementById(id);
        const option = Array.from(select.options).find(o => o.value === value);
        if (option) {
            select.value = value;
        } else {
            // Add custom option
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = value;
            select.appendChild(opt);
            select.value = value;
        }
    },

    // ── Analysis Panel (Right Panel - Analysis Tab) ─────────────

    updateAnalysisPanel(data) {
        // Update global entities
        this._renderGlobalCharacters(data.global_entities || { characters: [], props: [] });
        this._renderGlobalProps(data.global_entities || { characters: [], props: [] });

        // Update location list (built from scene data in state)
        this._renderGlobalLocations();

        // Update global analysis if present
        if (data.global_analysis) {
            const resultEl = document.getElementById('global-analysis-result');
            const ta = document.getElementById('global-analysis-text');
            const toggleBtn = document.getElementById('btn-toggle-analysis');
            const isNewFromServer = data.global_analysis !== this._lastAnalysisFromServer;
            this._lastAnalysisFromServer = data.global_analysis;
            resultEl.style.display = 'block';
            ta.value = data.global_analysis;
            if (isNewFromServer) {
                // New analysis from server: always expand and reset button label
                ta.style.display = '';
                if (toggleBtn) toggleBtn.textContent = '收起';
            }
            // If same content: do NOT touch ta.style.display — preserve the user's
            // collapsed/expanded choice exactly as they left it.
        }

        // Update per-scene entities if a scene is selected
        if (this.selectedScene >= 0) {
            this._updateSceneAnalysis(this.selectedScene);
        }
    },

    _updateSceneAnalysis(index) {
        const sceneSection = document.getElementById('analysis-scene-section');
        const emptySection = document.getElementById('analysis-empty');

        sceneSection.style.display = 'block';
        emptySection.style.display = 'none';

        // Update scene label in analysis nav
        const scene = (App.state.scenes || [])[index];
        const analysisLabel = document.getElementById('analysis-scene-label');
        if (analysisLabel && scene) {
            const h = scene.heading || '';
            const short = h.length > 28 ? h.substring(0, 25) + '…' : h;
            analysisLabel.textContent = `场次 ${scene.scene_number}${short ? '  ' + short : ''}`;
        }

        const entities = App.state.entities || {};
        const sceneEnt = entities[index] || null;

        const charsContainer = document.getElementById('scene-characters');
        const propsContainer = document.getElementById('scene-props');
        const typeContainer = document.getElementById('scene-type');

        if (sceneEnt) {
            charsContainer.innerHTML = this._renderEditableTags(sceneEnt.characters || [], 'character', index);
            propsContainer.innerHTML = this._renderEditableTags(sceneEnt.props || [], 'prop', index);
            const st = sceneEnt.scene_type || '';
            typeContainer.innerHTML = this._renderSceneTypeEditor(st, index);
            this._renderAnalysisClassification(sceneEnt.classification, sceneEnt.scene_type_key);
        } else {
            charsContainer.innerHTML = this._renderEditableTags([], 'character', index);
            propsContainer.innerHTML = this._renderEditableTags([], 'prop', index);
            typeContainer.innerHTML = this._renderSceneTypeEditor('', index);
            this._renderAnalysisClassification(null, null);
        }

        this._bindSceneEntityEvents(index);
    },

    _renderEditableTags(items, type, sceneIdx) {
        let html = '';
        (items || []).forEach(item => {
            html += `<span class="entity-tag entity-tag-editable">
                ${this._escapeHtml(item)}
                <button class="entity-tag-del" data-name="${this._escapeHtml(item)}" data-type="${type}" data-idx="${sceneIdx}" title="删除">×</button>
            </span>`;
        });
        html += `<span class="entity-add-container">
            <input type="text" class="entity-add-input scene-add-input" placeholder="添加..." data-type="${type}" data-idx="${sceneIdx}">
            <button class="btn-inline scene-add-btn" data-type="${type}" data-idx="${sceneIdx}">+</button>
        </span>`;
        return html;
    },

    /** Build unified option list from table_a + custom_scene_types (deduped). */
    _getUnifiedTypeOptions() {
        if (!window._dpParamsCache) return [];
        const tableA = window._dpParamsCache.table_a || {};
        const custom = window._dpParamsCache.custom_scene_types || {};
        const seen = new Set();
        const opts = [];
        [...Object.entries(tableA), ...Object.entries(custom)].forEach(([k, v]) => {
            if (!seen.has(k)) {
                seen.add(k);
                const lbl = typeof v === 'object' ? (v.label || k) : k;
                opts.push({ key: k, label: lbl });
            }
        });
        return opts;
    },

    /** Populate a <select> element with unified scene type options. */
    _populateSceneTypeSelect(selectEl, currentVal) {
        if (!selectEl) return;
        const opts = this._getUnifiedTypeOptions();
        // Keep existing first empty option, rebuild the rest
        selectEl.innerHTML = `<option value="">-- 未分类 --</option>`;
        opts.forEach(({ key, label }) => {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = key === label ? key : `${key} — ${label}`;
            if (key === currentVal) opt.selected = true;
            selectEl.appendChild(opt);
        });
        // If currentVal is not in options, add it as custom entry
        if (currentVal && !opts.find(o => o.key === currentVal)) {
            const opt = document.createElement('option');
            opt.value = currentVal;
            opt.textContent = currentVal;
            opt.selected = true;
            selectEl.appendChild(opt);
        }
    },

    _renderSceneTypeEditor(currentType, sceneIdx) {
        const opts = this._getUnifiedTypeOptions();
        let html = `<select class="scene-type-select" data-idx="${sceneIdx}" style="font-size:12px;padding:2px 4px;border:1px solid #ddd;border-radius:4px">`;
        html += `<option value="">-- 选择类型 --</option>`;
        opts.forEach(({ key, label }) => {
            const sel = key === currentType ? 'selected' : '';
            const txt = key === label ? key : `${key} — ${label}`;
            html += `<option value="${key}" ${sel}>${txt}</option>`;
        });
        // Fallback: if currentType not in list, show it
        if (currentType && !opts.find(o => o.key === currentType)) {
            html += `<option value="${this._escapeHtml(currentType)}" selected>${this._escapeHtml(currentType)}</option>`;
        }
        html += '</select>';
        return html;
    },

    _renderAnalysisClassification(cls, typeKey) {
        const section = document.getElementById('scene-type-key-section');
        const display = document.getElementById('scene-type-key-display');
        if (!section || !display) return;
        if (!cls || !typeKey) { section.style.display = 'none'; return; }
        section.style.display = '';
        const CONF = { high:'#166534;background:#dcfce7', medium:'#92400e;background:#fef9c3', low:'#991b1b;background:#fee2e2' };
        const confStyle = CONF[cls.confidence] || '#475569;background:#f1f5f9';
        const methLabel = {manual:'手动',keyword:'关键词',cast_count:'演员数',attribute:'属性',default:'默认'}[cls.method] || cls.method || '';
        const kwText = (cls.matched_keywords || []).length
            ? `<span style="font-size:10px;color:#888">关键词：${this._escapeHtml(cls.matched_keywords.slice(0,4).join('、'))}</span>` : '';
        display.innerHTML = `
            <span class="entity-tag" style="background:#e0f2fe;color:#075985">${this._escapeHtml(typeKey)}</span>
            <span class="entity-tag" style="color:${confStyle.split(';')[0]};${confStyle.split(';')[1]}">${methLabel}</span>
            ${kwText}`;
    },

    _bindSceneEntityEvents(sceneIdx) {
        const charsEl = document.getElementById('scene-characters');
        const propsEl = document.getElementById('scene-props');
        const typeEl = document.getElementById('scene-type');

        // Delete tag buttons
        [charsEl, propsEl].forEach(container => {
            if (!container) return;
            container.querySelectorAll('.entity-tag-del').forEach(btn => {
                btn.addEventListener('click', () => {
                    const name = btn.dataset.name;
                    const type = btn.dataset.type;
                    const idx = parseInt(btn.dataset.idx);
                    App.removeSceneEntity(idx, type, name);
                });
            });

            // Add input: press Enter or click + button
            const input = container.querySelector('.scene-add-input');
            const addBtn = container.querySelector('.scene-add-btn');
            if (input && addBtn) {
                const doAdd = () => {
                    const val = input.value.trim();
                    if (val) {
                        App.addSceneEntity(parseInt(input.dataset.idx), input.dataset.type, val);
                        input.value = '';
                    }
                };
                addBtn.addEventListener('click', doAdd);
                input.addEventListener('keydown', e => {
                    if (e.key === 'Enter') { e.preventDefault(); doAdd(); }
                });
            }
        });

        // Scene type select
        const typeSelect = typeEl ? typeEl.querySelector('.scene-type-select') : null;
        if (typeSelect) {
            typeSelect.addEventListener('change', () => {
                App.updateSceneType(parseInt(typeSelect.dataset.idx), typeSelect.value);
            });
        }
    },

    _renderGlobalCharacters(globalEntities) {
        const container = document.getElementById('global-characters');
        const characters = globalEntities.characters || [];

        if (characters.length === 0) {
            container.innerHTML = '<div class="entity-empty">请先执行实体提取</div>';
            return;
        }

        let html = '';
        characters.forEach(ch => {
            const analysisText = (App.state.character_analyses || {})[ch.name] || '';
            const hasAnalysis = analysisText.length > 0;
            const eName = this._escapeHtml(ch.name);
            const scenesJson = this._escapeHtml(JSON.stringify(ch.scenes));

            html += `<div class="character-item">`;
            html += `<div class="character-header">`;
            html += `<span class="character-name entity-link" data-scenes="${scenesJson}" data-name="${eName}" title="点击定位到场次">${eName}</span>`;
            html += `<span class="entity-scene-badge" data-scenes="${scenesJson}" data-name="${eName}" title="点击查看出现场次">出现 ${ch.scenes.length} 场 ▾</span>`;
            html += `<div class="entity-edit-actions">`;
            html += `<button class="btn-inline btn-rename-entity" data-name="${eName}" data-type="character" title="重命名">改名</button>`;
            html += `<button class="btn-inline btn-analyze-char" data-name="${eName}" title="LLM 分析">分析</button>`;
            if (hasAnalysis) {
                const collapsed = this._collapsedCharAnalyses.has(ch.name);
                html += `<button class="btn-inline btn-toggle-char-analysis" data-name="${eName}">${collapsed ? '展开' : '收起'}</button>`;
            }
            html += `<button class="btn-inline btn-danger-inline btn-remove-entity" data-name="${eName}" data-type="character" title="删除">删除</button>`;
            html += `</div></div>`;

            if (hasAnalysis) {
                const collapsed = this._collapsedCharAnalyses.has(ch.name);
                html += `<div class="character-analysis"${collapsed ? ' style="display:none"' : ''}>${this._escapeHtml(analysisText)}</div>`;
            }

            html += `</div>`;
        });

        container.innerHTML = html;

        // Clickable name: highlight all scenes in script view
        container.querySelectorAll('.character-name.entity-link').forEach(el => {
            el.addEventListener('click', () => {
                const scenes = JSON.parse(el.dataset.scenes || '[]');
                this.highlightEntityScenes(scenes, el, el.dataset.name, 'character');
            });
        });

        // Scene badge: show popup with all scenes
        container.querySelectorAll('.entity-scene-badge').forEach(badge => {
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                this._showEntityScenesPopup(badge, JSON.parse(badge.dataset.scenes || '[]'));
            });
        });

        container.querySelectorAll('.btn-analyze-char').forEach(btn => {
            btn.addEventListener('click', () => App.analyzeCharacter(btn.dataset.name));
        });
        container.querySelectorAll('.btn-rename-entity').forEach(btn => {
            btn.addEventListener('click', () => {
                const newName = prompt(`将人物「${btn.dataset.name}」重命名为:`, btn.dataset.name);
                if (newName && newName.trim() && newName.trim() !== btn.dataset.name) {
                    App.renameEntity(btn.dataset.name, newName.trim(), 'character');
                }
            });
        });
        container.querySelectorAll('.btn-remove-entity').forEach(btn => {
            btn.addEventListener('click', () => {
                if (confirm(`确认删除人物「${btn.dataset.name}」？将从所有场次中移除。`)) {
                    App.removeEntity(btn.dataset.name, btn.dataset.type);
                }
            });
        });
        container.querySelectorAll('.btn-toggle-char-analysis').forEach(btn => {
            btn.addEventListener('click', () => {
                const name = btn.dataset.name;
                const item = btn.closest('.character-item');
                const analysisEl = item.querySelector('.character-analysis');
                const isHidden = analysisEl.style.display === 'none';
                analysisEl.style.display = isHidden ? '' : 'none';
                btn.textContent = isHidden ? '收起' : '展开';
                if (isHidden) this._collapsedCharAnalyses.delete(name);
                else this._collapsedCharAnalyses.add(name);
            });
        });
    },

    _renderGlobalProps(globalEntities) {
        const container = document.getElementById('global-props');
        const props = globalEntities.props || [];

        if (props.length === 0) {
            container.innerHTML = '<div class="entity-empty">请先执行实体提取</div>';
            return;
        }

        let html = '';
        props.forEach(p => {
            const eName = this._escapeHtml(p.name);
            const scenesJson = this._escapeHtml(JSON.stringify(p.scenes));
            html += `<div class="prop-item">`;
            html += `<span class="prop-name entity-link" data-scenes="${scenesJson}" data-name="${eName}" title="点击定位到场次">${eName}</span>`;
            html += `<span class="entity-scene-badge" data-scenes="${scenesJson}" data-name="${eName}" title="点击查看出现场次">出现 ${p.scenes.length} 场 ▾</span>`;
            html += `<div class="entity-edit-actions">`;
            html += `<button class="btn-inline btn-rename-entity" data-name="${eName}" data-type="prop" title="重命名">改名</button>`;
            html += `<button class="btn-inline btn-danger-inline btn-remove-entity" data-name="${eName}" data-type="prop" title="删除">删除</button>`;
            html += `</div></div>`;
        });

        container.innerHTML = html;

        // Clickable prop name: highlight all scenes in script view
        container.querySelectorAll('.prop-name.entity-link').forEach(el => {
            el.addEventListener('click', () => {
                const scenes = JSON.parse(el.dataset.scenes || '[]');
                this.highlightEntityScenes(scenes, el, el.dataset.name, 'prop');
            });
        });

        // Scene badge: popup
        container.querySelectorAll('.entity-scene-badge').forEach(badge => {
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                this._showEntityScenesPopup(badge, JSON.parse(badge.dataset.scenes || '[]'));
            });
        });

        container.querySelectorAll('.btn-rename-entity').forEach(btn => {
            btn.addEventListener('click', () => {
                const newName = prompt(`将道具「${btn.dataset.name}」重命名为:`, btn.dataset.name);
                if (newName && newName.trim() && newName.trim() !== btn.dataset.name) {
                    App.renameEntity(btn.dataset.name, newName.trim(), 'prop');
                }
            });
        });
        container.querySelectorAll('.btn-remove-entity').forEach(btn => {
            btn.addEventListener('click', () => {
                if (confirm(`确认删除道具「${btn.dataset.name}」？将从所有场次中移除。`)) {
                    App.removeEntity(btn.dataset.name, btn.dataset.type);
                }
            });
        });
    },

    /** Show a popup listing all scenes an entity appears in. */
    _showEntityScenesPopup(anchorEl, sceneIndices) {
        // Remove any existing popup
        document.querySelectorAll('.entity-scenes-popup').forEach(el => el.remove());

        if (!sceneIndices || sceneIndices.length === 0) return;

        const scenes = App.state.scenes || [];
        const popup = document.createElement('div');
        popup.className = 'entity-scenes-popup';

        sceneIndices.forEach(sceneIdx => {
            const scene = scenes[sceneIdx];
            if (!scene) return;
            const item = document.createElement('div');
            item.className = 'entity-scenes-popup-item';
            item.textContent = `场次 ${scene.scene_number}: ${scene.heading || scene.location || '(无标题)'}`;
            item.addEventListener('click', () => {
                App.navigateToScene(sceneIdx);
                popup.remove();
            });
            popup.appendChild(item);
        });

        // Position near anchor
        const rect = anchorEl.getBoundingClientRect();
        popup.style.top = (rect.bottom + 4) + 'px';
        popup.style.left = rect.left + 'px';
        document.body.appendChild(popup);

        // Close on outside click
        const close = (e) => {
            if (!popup.contains(e.target) && e.target !== anchorEl) {
                popup.remove();
                document.removeEventListener('click', close);
            }
        };
        setTimeout(() => document.addEventListener('click', close), 0);
    },

    _renderGlobalLocations() {
        const container = document.getElementById('global-locations');
        if (!container) return;
        const scenes = App.state.scenes || [];

        // Build location map: location -> [scene indices]
        const locMap = new Map();
        scenes.forEach((scene, idx) => {
            const loc = (scene.location || '').trim() || '（未知地点）';
            if (!locMap.has(loc)) locMap.set(loc, []);
            locMap.get(loc).push(idx);
        });

        if (locMap.size === 0) {
            container.innerHTML = '<div class="entity-empty">请先上传并识别剧本</div>';
            return;
        }

        // Sort by scene count descending
        const locs = [...locMap.entries()].sort((a, b) => b[1].length - a[1].length);

        let html = '';
        locs.forEach(([name, indices]) => {
            const eName = this._escapeHtml(name);
            const indicesJson = this._escapeHtml(JSON.stringify(indices));
            html += `<div class="location-item">`;
            html += `<span class="location-name entity-link" data-scenes="${indicesJson}" data-name="${eName}" title="点击高亮该地点所有场次">${eName}</span>`;
            html += `<span class="entity-scene-badge" data-scenes="${indicesJson}" title="点击查看场次列表">${indices.length} 场 ▾</span>`;
            html += `<div class="entity-edit-actions">`;
            html += `<button class="btn-inline btn-rename-location" data-location="${eName}" title="重命名或合并地点">改名/合并</button>`;
            html += `</div></div>`;
        });
        container.innerHTML = html;

        // Highlight all scenes on click
        container.querySelectorAll('.location-name.entity-link').forEach(el => {
            el.addEventListener('click', () => {
                const indices = JSON.parse(el.dataset.scenes || '[]');
                this.highlightEntityScenes(indices, el, el.dataset.name, 'location');
            });
        });

        // Scene popup badge
        container.querySelectorAll('.entity-scene-badge').forEach(badge => {
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                this._showEntityScenesPopup(badge, JSON.parse(badge.dataset.scenes || '[]'));
            });
        });

        // Rename / merge location — inline input editing
        container.querySelectorAll('.btn-rename-location').forEach(btn => {
            btn.addEventListener('click', () => {
                const item = btn.closest('.location-item');
                if (item.querySelector('.location-rename-input')) return; // already editing
                const nameSpan = item.querySelector('.location-name');
                const oldName = btn.dataset.location;

                const input = document.createElement('input');
                input.type = 'text';
                input.value = oldName;
                input.className = 'location-rename-input';
                nameSpan.style.display = 'none';
                item.insertBefore(input, nameSpan);
                input.focus();
                input.select();

                const commit = () => {
                    if (!input.parentNode) return; // already removed
                    const newName = input.value.trim();
                    input.remove();
                    nameSpan.style.display = '';
                    if (newName && newName !== oldName) App.renameLocation(oldName, newName);
                };
                const cancel = () => {
                    if (!input.parentNode) return;
                    input.remove();
                    nameSpan.style.display = '';
                };
                input.addEventListener('keydown', e => {
                    if (e.key === 'Enter') { e.preventDefault(); commit(); }
                    if (e.key === 'Escape') { cancel(); }
                });
                input.addEventListener('blur', commit);
            });
        });
    },

    renderMergeDialog(entities, type) {
        const label = type === 'character' ? '人物' : '道具';
        document.getElementById('merge-type-label').textContent = label;
        document.getElementById('merge-target-input').value = '';

        const list = document.getElementById('merge-source-list');
        if (!entities || entities.length === 0) {
            list.innerHTML = '<div class="entity-empty" style="padding:8px">暂无数据，请先提取实体</div>';
        } else {
            list.innerHTML = entities.map(e => `
                <div class="merge-item">
                    <input type="checkbox" class="merge-check" value="${this._escapeHtml(e.name)}">
                    <span class="merge-item-name">${this._escapeHtml(e.name)}</span>
                    <span class="merge-item-count">出现 ${e.scenes.length} 场</span>
                </div>`).join('');

            // Click on row toggles checkbox
            list.querySelectorAll('.merge-item').forEach(row => {
                row.addEventListener('click', e => {
                    if (e.target.type !== 'checkbox') {
                        const cb = row.querySelector('.merge-check');
                        cb.checked = !cb.checked;
                        // Auto-fill target if only one selected
                        const checked = list.querySelectorAll('.merge-check:checked');
                        if (checked.length === 1) {
                            document.getElementById('merge-target-input').value = checked[0].value;
                        }
                    }
                });
            });
        }

        document.getElementById('merge-dialog-overlay').style.display = 'flex';
    },

    _renderTags(items) {
        if (!items || items.length === 0) {
            return '<span class="entity-empty">无</span>';
        }
        return items.map(item =>
            `<span class="entity-tag">${this._escapeHtml(item)}</span>`
        ).join('');
    },

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // ── Project & Episode Dialogs ────────────────────────────────

    renderProjectList(projects) {
        const container = document.getElementById('project-list');
        if (!projects || projects.length === 0) {
            container.innerHTML = '<div style="color:#aaa;font-size:13px;padding:8px 0;">暂无项目</div>';
            return;
        }

        let html = '';
        projects.forEach(p => {
            const date = p.updated_at ? p.updated_at.slice(0, 10) : '';
            html += `<div class="project-item" data-id="${p.id}">`;
            html += `<span class="project-item-name">${this._escapeHtml(p.name)}</span>`;
            html += `<span class="project-item-meta">${p.episode_count} 集 · ${date}</span>`;
            html += `<button class="btn-inline btn-danger-inline btn-delete-project" data-id="${p.id}" style="color:#dc2626;border-color:#dc2626;">删除</button>`;
            html += `</div>`;
        });
        container.innerHTML = html;

        container.querySelectorAll('.project-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.classList.contains('btn-delete-project')) return;
                App.openProject(item.dataset.id);
            });
        });

        container.querySelectorAll('.btn-delete-project').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                App.deleteProject(btn.dataset.id);
            });
        });
    },

    renderEpisodeList(episodes, activeId) {
        const container = document.getElementById('episode-list');
        if (!episodes || episodes.length === 0) {
            container.innerHTML = '<div style="color:#aaa;font-size:13px;padding:8px 0;">暂无集数，请点击"添加集数"导入剧本文件</div>';
            return;
        }

        container.innerHTML = '';
        let draggingId = null;

        episodes.forEach((ep, i) => {
            const isActive = ep.id === activeId;
            const item = document.createElement('div');
            item.className = 'episode-item' + (isActive ? ' active' : '');
            item.dataset.id = ep.id;
            item.draggable = true;

            // Drag handle
            const handle = document.createElement('span');
            handle.className = 'drag-handle';
            handle.textContent = '⠿';
            handle.title = '拖拽排序';
            item.appendChild(handle);

            // Episode number
            const num = document.createElement('span');
            num.className = 'episode-num';
            num.textContent = i + 1;
            item.appendChild(num);

            // Info block
            const info = document.createElement('div');
            info.style.cssText = 'flex:1;min-width:0';
            const name = document.createElement('div');
            name.className = 'episode-name';
            name.textContent = ep.name;
            const meta = document.createElement('div');
            meta.className = 'episode-meta';
            meta.style.textAlign = 'left';
            meta.textContent = `${ep.filename} · ${ep.scene_count} 场`;
            info.appendChild(name);
            info.appendChild(meta);
            item.appendChild(info);

            // Action buttons
            const actions = document.createElement('div');
            actions.className = 'episode-actions';

            if (!isActive) {
                const switchBtn = document.createElement('button');
                switchBtn.className = 'btn-inline btn-switch-episode';
                switchBtn.dataset.id = ep.id;
                switchBtn.textContent = '切换';
                switchBtn.addEventListener('click', () => App.switchEpisode(ep.id));
                actions.appendChild(switchBtn);
            } else {
                const currentSpan = document.createElement('span');
                currentSpan.className = 'btn-inline';
                currentSpan.style.cssText = 'color:#16a34a;border-color:#16a34a;cursor:default;';
                currentSpan.textContent = '当前';
                actions.appendChild(currentSpan);
            }

            const renameBtn = document.createElement('button');
            renameBtn.className = 'btn-inline btn-rename-episode';
            renameBtn.dataset.id = ep.id;
            renameBtn.dataset.name = ep.name;
            renameBtn.textContent = '重命名';
            renameBtn.addEventListener('click', () => {
                const newName = prompt('请输入新的集数名称:', ep.name);
                if (newName && newName.trim()) {
                    App.renameEpisode(ep.id, newName.trim());
                }
            });
            actions.appendChild(renameBtn);

            if (episodes.length > 1) {
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'btn-inline btn-danger-inline btn-delete-episode';
                deleteBtn.dataset.id = ep.id;
                deleteBtn.textContent = '删除';
                deleteBtn.addEventListener('click', () => App.deleteEpisode(ep.id));
                actions.appendChild(deleteBtn);
            }

            item.appendChild(actions);

            // ── Drag events ──
            item.addEventListener('dragstart', (e) => {
                draggingId = ep.id;
                item.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            });

            item.addEventListener('dragend', () => {
                item.classList.remove('dragging');
                draggingId = null;
                container.querySelectorAll('.episode-item').forEach(el => {
                    el.classList.remove('drag-over-top', 'drag-over-bottom');
                });
            });

            item.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                if (!draggingId || item.dataset.id === draggingId) return;
                const rect = item.getBoundingClientRect();
                const mid = rect.top + rect.height / 2;
                item.classList.remove('drag-over-top', 'drag-over-bottom');
                item.classList.add(e.clientY < mid ? 'drag-over-top' : 'drag-over-bottom');
            });

            item.addEventListener('dragleave', () => {
                item.classList.remove('drag-over-top', 'drag-over-bottom');
            });

            item.addEventListener('drop', (e) => {
                e.preventDefault();
                if (!draggingId || item.dataset.id === draggingId) return;

                const rect = item.getBoundingClientRect();
                const insertBefore = e.clientY < rect.top + rect.height / 2;

                // Find dragging element and reorder DOM
                const dragEl = container.querySelector(`.episode-item[data-id="${draggingId}"]`);
                if (!dragEl) return;

                if (insertBefore) {
                    container.insertBefore(dragEl, item);
                } else {
                    container.insertBefore(dragEl, item.nextSibling);
                }

                // Clean up indicators
                container.querySelectorAll('.episode-item').forEach(el => {
                    el.classList.remove('drag-over-top', 'drag-over-bottom');
                });

                // Read new order from DOM and call API
                const newOrder = Array.from(container.querySelectorAll('.episode-item'))
                    .map(el => el.dataset.id);

                App._apiJson('/api/episodes/reorder', { order: newOrder }).then(data => {
                    if (data) App._applyState(data);
                });
            });

            container.appendChild(item);
        });
    },

    // ── Project Overview Tab ─────────────────────────────────────

    renderProjectSummary(data) {
        const empty = document.getElementById('overview-empty');
        const content = document.getElementById('overview-content');

        if (!data) { empty.style.display = 'block'; content.style.display = 'none'; return; }

        empty.style.display = 'none';
        content.style.display = 'block';

        content.querySelector('.overview-project-title').textContent =
            `项目：${data.project_name}`;
        content.querySelector('.overview-stats').innerHTML =
            `<span class="overview-stat">共 <b>${data.episodes.length}</b> 集</span>` +
            `<span class="overview-stat">共 <b>${data.total_scenes}</b> 场</span>` +
            `<span class="overview-stat"><b>${data.all_characters.length}</b> 个人物</span>` +
            `<span class="overview-stat"><b>${data.all_props.length}</b> 件道具</span>`;

        // Episodes table
        const epEl = document.getElementById('overview-episodes');
        if (data.episodes.length === 0) {
            epEl.innerHTML = '<div class="entity-empty">暂无集数</div>';
        } else {
            epEl.innerHTML = data.episodes.map(ep => `
                <div class="overview-ep-row${ep.is_active ? ' active' : ''}">
                    <span class="overview-ep-name">${this._escapeHtml(ep.name)}</span>
                    <span class="overview-ep-meta">${ep.scene_count} 场 · ${ep.character_count} 人 · ${ep.prop_count} 道具</span>
                </div>`).join('');
        }

        // Characters across episodes
        const chEl = document.getElementById('overview-characters');
        if (data.all_characters.length === 0) {
            chEl.innerHTML = '<div class="entity-empty">请先对各集执行实体提取</div>';
        } else {
            chEl.innerHTML = data.all_characters.map(c => `
                <div class="overview-entity-row">
                    <span class="overview-entity-name">${this._escapeHtml(c.name)}</span>
                    <span class="overview-entity-meta">出现 ${c.total_scenes} 场 · ${c.episode_count} 集（${this._escapeHtml(c.episodes.join('、'))}）</span>
                </div>`).join('');
        }

        // Props across episodes
        const prEl = document.getElementById('overview-props');
        if (data.all_props.length === 0) {
            prEl.innerHTML = '<div class="entity-empty">请先对各集执行实体提取</div>';
        } else {
            prEl.innerHTML = data.all_props.map(p => `
                <div class="overview-entity-row">
                    <span class="overview-entity-name">${this._escapeHtml(p.name)}</span>
                    <span class="overview-entity-meta">出现 ${p.total_scenes} 场 · ${p.episode_count} 集（${this._escapeHtml(p.episodes.join('、'))}）</span>
                </div>`).join('');
        }
    },

    // ── Context Menu Utilities ───────────────────────────────────

    _positionMenu(menu, x, y) {
        menu.style.display = 'block';
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';

        // Adjust if off-screen
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) {
            menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
        }
        if (rect.bottom > window.innerHeight) {
            menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
        }
    },

    _hideContextMenu() {
        document.getElementById('context-menu').style.display = 'none';
    },
};

// Close context menu on click elsewhere
document.addEventListener('click', () => Panels._hideContextMenu());
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') Panels._hideContextMenu();
});
