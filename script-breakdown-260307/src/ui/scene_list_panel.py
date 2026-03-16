"""Left panel: scene list with context menu actions."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QMenu, QLabel,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from ..scene.models import Scene, SceneList


class SceneListPanel(QWidget):
    """Displays a list of scenes with confidence-based coloring."""

    scene_selected = pyqtSignal(int)       # emits scene index
    merge_requested = pyqtSignal(int, int)  # emits two adjacent scene indices

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene_list: SceneList | None = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.header = QLabel("场次列表")
        self.header.setStyleSheet("font-weight: bold; padding: 6px;")
        layout.addWidget(self.header)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

    def set_scenes(self, scene_list: SceneList):
        """Update the displayed scene list."""
        self._scene_list = scene_list
        self.list_widget.clear()

        for scene in scene_list:
            label = f"{scene.scene_number}. {scene.heading}"
            if len(label) > 40:
                label = label[:37] + "..."
            item = QListWidgetItem(label)

            # Color-code by confidence
            if scene.confidence < 0.5:
                item.setForeground(QColor(220, 50, 50))    # red
            elif scene.confidence < 0.8:
                item.setForeground(QColor(200, 150, 0))    # orange
            if scene.is_manually_adjusted:
                item.setForeground(QColor(50, 130, 50))    # green

            self.list_widget.addItem(item)

        self.header.setText(f"场次列表 ({len(scene_list)})")

    def select_scene(self, index: int):
        """Programmatically select a scene."""
        if 0 <= index < self.list_widget.count():
            self.list_widget.setCurrentRow(index)

    def _on_row_changed(self, row: int):
        if row >= 0:
            self.scene_selected.emit(row)

    def _show_context_menu(self, pos):
        if not self._scene_list:
            return
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        row = self.list_widget.row(item)

        menu = QMenu(self)

        # Merge with next scene
        if row < len(self._scene_list) - 1:
            merge_action = menu.addAction("合并到下一场")
            merge_action.triggered.connect(lambda: self.merge_requested.emit(row, row + 1))

        # Merge with previous scene
        if row > 0:
            merge_prev_action = menu.addAction("合并到上一场")
            merge_prev_action.triggered.connect(lambda: self.merge_requested.emit(row - 1, row))

        if menu.actions():
            menu.exec(self.list_widget.mapToGlobal(pos))
