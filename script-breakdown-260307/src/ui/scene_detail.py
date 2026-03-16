"""Right panel: scene detail view and editor."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QLabel, QPushButton, QComboBox, QSpinBox, QGroupBox,
)
from PyQt6.QtCore import pyqtSignal

from ..scene.models import Scene


class SceneDetailPanel(QWidget):
    """Displays and allows editing of scene details."""

    scene_updated = pyqtSignal(int)        # emits scene index after edit
    summarize_requested = pyqtSignal(int)  # emits scene index for LLM summarization

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_scene: Scene | None = None
        self._current_index: int = -1
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.header = QLabel("场次详情")
        self.header.setStyleSheet("font-weight: bold; padding: 6px;")
        layout.addWidget(self.header)

        # Scene info group
        info_group = QGroupBox("基本信息")
        info_layout = QFormLayout()

        self.scene_num_spin = QSpinBox()
        self.scene_num_spin.setRange(1, 9999)
        info_layout.addRow("场次号:", self.scene_num_spin)

        self.heading_edit = QLineEdit()
        self.heading_edit.setPlaceholderText("场景标题")
        info_layout.addRow("标题:", self.heading_edit)

        self.int_ext_combo = QComboBox()
        self.int_ext_combo.addItems(["", "内", "外", "内外", "INT", "EXT", "INT/EXT"])
        self.int_ext_combo.setEditable(True)
        info_layout.addRow("内/外景:", self.int_ext_combo)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("场景地点")
        info_layout.addRow("地点:", self.location_edit)

        self.time_edit = QComboBox()
        self.time_edit.addItems(["", "日", "夜", "晨", "黄昏", "DAY", "NIGHT", "DAWN", "DUSK"])
        self.time_edit.setEditable(True)
        info_layout.addRow("时间:", self.time_edit)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Range info
        range_group = QGroupBox("范围")
        range_layout = QFormLayout()

        self.start_line_label = QLabel("-")
        range_layout.addRow("起始行:", self.start_line_label)

        self.end_line_label = QLabel("-")
        range_layout.addRow("结束行:", self.end_line_label)

        self.confidence_label = QLabel("-")
        range_layout.addRow("置信度:", self.confidence_label)

        self.adjusted_label = QLabel("-")
        range_layout.addRow("人工校准:", self.adjusted_label)

        range_group.setLayout(range_layout)
        layout.addWidget(range_group)

        # Summary
        summary_group = QGroupBox("摘要")
        summary_layout = QVBoxLayout()

        self.summary_edit = QTextEdit()
        self.summary_edit.setMaximumHeight(120)
        self.summary_edit.setPlaceholderText("场次摘要...")
        summary_layout.addWidget(self.summary_edit)

        self.llm_summarize_btn = QPushButton("LLM 凝练")
        self.llm_summarize_btn.clicked.connect(self._on_summarize_clicked)
        summary_layout.addWidget(self.llm_summarize_btn)

        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)

        # Apply button
        self.apply_btn = QPushButton("应用修改")
        self.apply_btn.clicked.connect(self._apply_changes)
        layout.addWidget(self.apply_btn)

        layout.addStretch()

        # Initially disabled
        self._set_enabled(False)

    def set_scene(self, scene: Scene, index: int):
        """Display a scene's details."""
        self._current_scene = scene
        self._current_index = index
        self._set_enabled(True)

        self.header.setText(f"场次详情 - 第{scene.scene_number}场")
        self.scene_num_spin.setValue(scene.scene_number)
        self.heading_edit.setText(scene.heading)

        # Set int_ext combo
        idx = self.int_ext_combo.findText(scene.int_ext)
        if idx >= 0:
            self.int_ext_combo.setCurrentIndex(idx)
        else:
            self.int_ext_combo.setCurrentText(scene.int_ext)

        self.location_edit.setText(scene.location)

        # Set time combo
        idx = self.time_edit.findText(scene.time_of_day)
        if idx >= 0:
            self.time_edit.setCurrentIndex(idx)
        else:
            self.time_edit.setCurrentText(scene.time_of_day)

        self.start_line_label.setText(str(scene.start_line + 1))
        self.end_line_label.setText(str(scene.end_line))
        self.confidence_label.setText(f"{scene.confidence:.0%}")
        self.adjusted_label.setText("是" if scene.is_manually_adjusted else "否")

        self.summary_edit.setPlainText(scene.summary)

    def clear(self):
        """Clear the detail panel."""
        self._current_scene = None
        self._current_index = -1
        self._set_enabled(False)
        self.header.setText("场次详情")
        self.heading_edit.clear()
        self.location_edit.clear()
        self.summary_edit.clear()
        self.start_line_label.setText("-")
        self.end_line_label.setText("-")
        self.confidence_label.setText("-")
        self.adjusted_label.setText("-")

    def _set_enabled(self, enabled: bool):
        self.scene_num_spin.setEnabled(enabled)
        self.heading_edit.setEnabled(enabled)
        self.int_ext_combo.setEnabled(enabled)
        self.location_edit.setEnabled(enabled)
        self.time_edit.setEnabled(enabled)
        self.summary_edit.setEnabled(enabled)
        self.apply_btn.setEnabled(enabled)
        self.llm_summarize_btn.setEnabled(enabled)

    def _apply_changes(self):
        if not self._current_scene:
            return
        self._current_scene.heading = self.heading_edit.text()
        self._current_scene.int_ext = self.int_ext_combo.currentText()
        self._current_scene.location = self.location_edit.text()
        self._current_scene.time_of_day = self.time_edit.currentText()
        self._current_scene.summary = self.summary_edit.toPlainText()
        self._current_scene.is_manually_adjusted = True
        self.adjusted_label.setText("是")
        self.scene_updated.emit(self._current_index)

    def _on_summarize_clicked(self):
        if self._current_index >= 0:
            self.summarize_requested.emit(self._current_index)

    def update_summary(self, summary: str):
        """Update the summary field (called after LLM summarization)."""
        self.summary_edit.setPlainText(summary)
        if self._current_scene:
            self._current_scene.summary = summary
