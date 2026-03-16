"""Main application window."""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QToolBar, QFileDialog,
    QMessageBox, QStatusBar, QApplication,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence

from ..parsers.base import ParseResult
from ..parsers.txt_parser import TxtParser
from ..parsers.docx_parser import DocxParser
from ..parsers.pdf_parser import PdfParser
from ..parsers.fdx_parser import FdxParser
from ..scene.models import SceneList
from ..scene.detector import SceneDetector
from ..scene.llm_detector import LLMSceneDetector
from ..llm.base import LLMConfig
from .scene_list_panel import SceneListPanel
from .script_view import ScriptView
from .scene_detail import SceneDetailPanel
from .llm_settings_dialog import LLMSettingsDialog, create_llm


# File format filter string
FILE_FILTER = (
    "所有支持格式 (*.txt *.text *.pdf *.docx *.fdx);;"
    "文本文件 (*.txt *.text);;"
    "PDF 文件 (*.pdf);;"
    "Word 文件 (*.docx);;"
    "Final Draft (*.fdx);;"
    "所有文件 (*)"
)

# Parser map
PARSERS = {
    ".txt": TxtParser,
    ".text": TxtParser,
    ".pdf": PdfParser,
    ".docx": DocxParser,
    ".fdx": FdxParser,
}


class _LLMWorker(QThread):
    """Background thread for LLM operations."""
    finished = pyqtSignal(object)  # result
    error = pyqtSignal(str)

    def __init__(self, func, *args):
        super().__init__()
        self._func = func
        self._args = args

    def run(self):
        try:
            result = self._func(*self._args)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window with three-panel layout."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("剧本拆解 - Script Breakdown")
        self.setMinimumSize(1200, 700)

        self._parse_result: ParseResult | None = None
        self._scene_list: SceneList | None = None
        self._llm_config = LLMConfig()
        self._worker: _LLMWorker | None = None

        self._init_ui()
        self._init_toolbar()
        self._init_statusbar()
        self._connect_signals()

    def _init_ui(self):
        # Three-panel splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.scene_list_panel = SceneListPanel()
        self.script_view = ScriptView()
        self.scene_detail = SceneDetailPanel()

        self.splitter.addWidget(self.scene_list_panel)
        self.splitter.addWidget(self.script_view)
        self.splitter.addWidget(self.scene_detail)

        # Set proportions: left 20%, center 55%, right 25%
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setStretchFactor(2, 3)

        self.setCentralWidget(self.splitter)

    def _init_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.import_action = QAction("导入剧本", self)
        self.import_action.setShortcut(QKeySequence("Ctrl+O"))
        self.import_action.triggered.connect(self._import_script)
        toolbar.addAction(self.import_action)

        toolbar.addSeparator()

        self.detect_action = QAction("自动识别", self)
        self.detect_action.setShortcut(QKeySequence("Ctrl+D"))
        self.detect_action.setEnabled(False)
        self.detect_action.triggered.connect(self._auto_detect)
        toolbar.addAction(self.detect_action)

        self.llm_detect_action = QAction("LLM 辅助", self)
        self.llm_detect_action.setShortcut(QKeySequence("Ctrl+L"))
        self.llm_detect_action.setEnabled(False)
        self.llm_detect_action.triggered.connect(self._llm_detect)
        toolbar.addAction(self.llm_detect_action)

        toolbar.addSeparator()

        self.export_action = QAction("导出", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self._export)
        toolbar.addAction(self.export_action)

        toolbar.addSeparator()

        self.settings_action = QAction("LLM 设置", self)
        self.settings_action.triggered.connect(self._open_llm_settings)
        toolbar.addAction(self.settings_action)

    def _init_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("就绪 - 请导入剧本文件")

    def _connect_signals(self):
        # Scene list → detail panel and script view
        self.scene_list_panel.scene_selected.connect(self._on_scene_selected)
        self.scene_list_panel.merge_requested.connect(self._merge_scenes)

        # Script view → manual calibration
        self.script_view.insert_break_requested.connect(self._insert_break)
        self.script_view.delete_break_requested.connect(self._delete_break)

        # Scene detail → update
        self.scene_detail.scene_updated.connect(self._on_scene_updated)
        self.scene_detail.summarize_requested.connect(self._summarize_scene)

    # ── Import ────────────────────────────────────────────────────

    def _import_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入剧本", "", FILE_FILTER,
        )
        if not file_path:
            return

        ext = os.path.splitext(file_path)[1].lower()
        parser_cls = PARSERS.get(ext)
        if parser_cls is None:
            QMessageBox.warning(self, "不支持的格式", f"不支持的文件格式: {ext}")
            return

        try:
            parser = parser_cls()
            self._parse_result = parser.parse(file_path)
            self.statusbar.showMessage(
                f"已导入: {os.path.basename(file_path)} ({len(self._parse_result.lines)} 行)"
            )
            self.detect_action.setEnabled(True)
            self.llm_detect_action.setEnabled(True)
            self.export_action.setEnabled(True)

            # Auto-detect scenes
            self._auto_detect()

        except Exception as e:
            QMessageBox.critical(self, "导入错误", f"导入文件失败:\n{e}")

    # ── Auto Detect ───────────────────────────────────────────────

    def _auto_detect(self):
        if not self._parse_result:
            return
        detector = SceneDetector()
        self._scene_list = detector.detect(self._parse_result)
        self._refresh_ui()
        self.statusbar.showMessage(f"自动识别完成: {len(self._scene_list)} 个场次")

    # ── LLM Detect ────────────────────────────────────────────────

    def _llm_detect(self):
        if not self._parse_result:
            return
        if not self._llm_config.provider:
            QMessageBox.information(self, "提示", "请先在 LLM 设置中配置 LLM 提供方。")
            self._open_llm_settings()
            return

        self.statusbar.showMessage("LLM 场次识别中...")
        self.llm_detect_action.setEnabled(False)

        try:
            llm = create_llm(self._llm_config)
            llm_detector = LLMSceneDetector(llm)

            def do_detect():
                return llm_detector.detect(self._parse_result)

            self._worker = _LLMWorker(do_detect)
            self._worker.finished.connect(self._on_llm_detect_done)
            self._worker.error.connect(self._on_llm_error)
            self._worker.start()

        except Exception as e:
            self.statusbar.showMessage(f"LLM 错误: {e}")
            self.llm_detect_action.setEnabled(True)

    def _on_llm_detect_done(self, result):
        self._scene_list = result
        self._refresh_ui()
        self.llm_detect_action.setEnabled(True)
        self.statusbar.showMessage(f"LLM 识别完成: {len(self._scene_list)} 个场次")

    def _on_llm_error(self, error_msg):
        self.llm_detect_action.setEnabled(True)
        self.statusbar.showMessage(f"LLM 错误: {error_msg}")
        QMessageBox.warning(self, "LLM 错误", f"LLM 调用失败:\n{error_msg}")

    # ── Manual Calibration ────────────────────────────────────────

    def _insert_break(self, line_index: int):
        if not self._scene_list or not self._parse_result:
            return
        self._scene_list.insert_break(line_index, self._parse_result.lines)
        self._refresh_ui()
        self.statusbar.showMessage(f"已在第 {line_index + 1} 行插入场次分隔")

    def _delete_break(self, line_index: int):
        if not self._scene_list:
            return
        # Find the scene starting at this line and remove it
        for i, scene in enumerate(self._scene_list):
            if scene.start_line == line_index and i > 0:
                self._scene_list.remove_scene(i)
                self._refresh_ui()
                self.statusbar.showMessage(f"已删除第 {line_index + 1} 行的场次分隔")
                return

    def _merge_scenes(self, idx1: int, idx2: int):
        if not self._scene_list:
            return
        self._scene_list.merge_scenes(idx1, idx2)
        self._refresh_ui()
        self.statusbar.showMessage(f"已合并场次 {idx1 + 1} 和 {idx2 + 1}")

    def _on_scene_selected(self, index: int):
        if not self._scene_list or index < 0 or index >= len(self._scene_list):
            return
        scene = self._scene_list[index]
        self.scene_detail.set_scene(scene, index)
        self.script_view.highlight_scene(index)

    def _on_scene_updated(self, index: int):
        """Called when scene details are edited."""
        self._refresh_ui()
        self.scene_list_panel.select_scene(index)
        self.statusbar.showMessage(f"场次 {index + 1} 已更新")

    # ── LLM Summarize ─────────────────────────────────────────────

    def _summarize_scene(self, index: int):
        if not self._scene_list or not self._llm_config.provider:
            QMessageBox.information(self, "提示", "请先配置 LLM。")
            return

        scene = self._scene_list[index]
        self.statusbar.showMessage(f"正在为场次 {index + 1} 生成摘要...")

        try:
            llm = create_llm(self._llm_config)
            llm_detector = LLMSceneDetector(llm)

            def do_summarize():
                return llm_detector.summarize_single_scene(scene)

            self._worker = _LLMWorker(do_summarize)
            self._worker.finished.connect(
                lambda summary: self._on_summarize_done(summary, index)
            )
            self._worker.error.connect(self._on_llm_error)
            self._worker.start()

        except Exception as e:
            self.statusbar.showMessage(f"摘要生成失败: {e}")

    def _on_summarize_done(self, summary, index):
        self.scene_detail.update_summary(summary)
        self.statusbar.showMessage(f"场次 {index + 1} 摘要已生成")

    # ── Export ─────────────────────────────────────────────────────

    def _export(self):
        if not self._scene_list:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出场次表", "", "文本文件 (*.txt);;CSV 文件 (*.csv)",
        )
        if not file_path:
            return

        try:
            if file_path.endswith(".csv"):
                self._export_csv(file_path)
            else:
                self._export_txt(file_path)
            self.statusbar.showMessage(f"已导出到: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出错误", f"导出失败:\n{e}")

    def _export_txt(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            for scene in self._scene_list:
                f.write(f"{'=' * 60}\n")
                f.write(f"场次 {scene.scene_number}: {scene.heading}\n")
                f.write(f"内外景: {scene.int_ext}  地点: {scene.location}  时间: {scene.time_of_day}\n")
                f.write(f"行范围: {scene.start_line + 1}-{scene.end_line}\n")
                if scene.summary:
                    f.write(f"摘要: {scene.summary}\n")
                f.write(f"{'=' * 60}\n\n")

    def _export_csv(self, path: str):
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["场次号", "标题", "内外景", "地点", "时间", "起始行", "结束行", "置信度", "人工校准", "摘要"])
            for scene in self._scene_list:
                writer.writerow([
                    scene.scene_number, scene.heading, scene.int_ext,
                    scene.location, scene.time_of_day,
                    scene.start_line + 1, scene.end_line,
                    f"{scene.confidence:.0%}",
                    "是" if scene.is_manually_adjusted else "否",
                    scene.summary,
                ])

    # ── Settings ───────────────────────────────────────────────────

    def _open_llm_settings(self):
        dialog = LLMSettingsDialog(self, self._llm_config)
        if dialog.exec():
            self._llm_config = dialog.get_config()
            self.statusbar.showMessage(f"LLM 设置已更新: {self._llm_config.provider}")

    # ── Refresh ────────────────────────────────────────────────────

    def _refresh_ui(self):
        """Refresh all panels after scene list changes."""
        if not self._parse_result or not self._scene_list:
            return
        self.scene_list_panel.set_scenes(self._scene_list)
        self.script_view.set_content(self._parse_result.lines, self._scene_list)
        self.scene_detail.clear()
