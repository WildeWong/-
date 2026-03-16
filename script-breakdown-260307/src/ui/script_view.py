"""Central panel: script text view with scene boundary markers."""
from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit, QMenu, QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt, QRect
from PyQt6.QtGui import (
    QTextCursor, QTextCharFormat, QColor, QFont,
    QPainter, QTextBlock, QAction, QKeyEvent,
)

from ..scene.models import SceneList


class _LineNumberArea(QWidget):
    """Line number gutter for the script view."""

    def __init__(self, editor: "ScriptView"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return self._editor._line_number_area_size()

    def paintEvent(self, event):
        self._editor._paint_line_numbers(event)


class ScriptView(QPlainTextEdit):
    """Displays script text with scene boundary markers and manual calibration."""

    insert_break_requested = pyqtSignal(int)   # line index
    delete_break_requested = pyqtSignal(int)   # line index
    line_clicked = pyqtSignal(int)             # line index

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene_list: SceneList | None = None
        self._lines: list[str] = []
        self._break_lines: set[int] = set()  # lines that are scene boundaries

        self.setReadOnly(True)
        self.setFont(QFont("Menlo", 13))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Line number area
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_width(0)

    def set_content(self, lines: list[str], scene_list: SceneList):
        """Set the script text and scene boundaries."""
        self._lines = lines
        self._scene_list = scene_list
        self._break_lines = {s.start_line for s in scene_list}

        self._render()

    def highlight_scene(self, scene_index: int):
        """Scroll to and highlight a specific scene."""
        if not self._scene_list or scene_index < 0 or scene_index >= len(self._scene_list):
            return
        scene = self._scene_list[scene_index]
        # Move cursor to the scene's start line
        block = self.document().findBlockByLineNumber(scene.start_line)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()

    def _render(self):
        """Render the script text with scene separators."""
        self.clear()
        if not self._lines:
            return

        # Build the display text (we show line by line, using the line index
        # to match to the original lines list)
        display_text = "\n".join(self._lines)
        self.setPlainText(display_text)

        # Apply formatting for scene heading lines
        self._apply_scene_highlighting()

    def _apply_scene_highlighting(self):
        """Highlight scene heading lines."""
        if not self._scene_list:
            return

        cursor = self.textCursor()
        cursor.beginEditBlock()

        for scene in self._scene_list:
            block = self.document().findBlockByLineNumber(scene.start_line)
            if not block.isValid():
                continue

            cursor.setPosition(block.position())
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)

            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)

            if scene.confidence < 0.5:
                fmt.setBackground(QColor(255, 200, 200))  # light red
            elif scene.confidence < 0.8:
                fmt.setBackground(QColor(255, 240, 200))  # light orange
            else:
                fmt.setBackground(QColor(200, 230, 255))  # light blue

            if scene.is_manually_adjusted:
                fmt.setBackground(QColor(200, 255, 200))  # light green

            cursor.mergeCharFormat(fmt)

        cursor.endEditBlock()

    def _get_line_at_cursor(self) -> int:
        """Get the line index at the current cursor position."""
        return self.textCursor().blockNumber()

    def _show_context_menu(self, pos):
        line = self._get_line_at_cursor()
        menu = QMenu(self)

        if line in self._break_lines:
            action = QAction("删除此场次分隔", self)
            action.triggered.connect(lambda: self.delete_break_requested.emit(line))
            menu.addAction(action)
        else:
            action = QAction("在此处插入场次分隔", self)
            action.triggered.connect(lambda: self.insert_break_requested.emit(line))
            menu.addAction(action)

        menu.exec(self.mapToGlobal(pos))

    def keyPressEvent(self, event: QKeyEvent):
        # Ctrl+B: insert break at cursor
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_B:
            line = self._get_line_at_cursor()
            if line not in self._break_lines:
                self.insert_break_requested.emit(line)
            return
        # Delete: delete break at cursor
        if event.key() == Qt.Key.Key_Delete:
            line = self._get_line_at_cursor()
            if line in self._break_lines:
                self.delete_break_requested.emit(line)
            return
        super().keyPressEvent(event)

    # ── Line number area ──

    def _line_number_area_size(self):
        digits = max(1, len(str(self.blockCount())))
        width = 10 + self.fontMetrics().horizontalAdvance("9") * (digits + 1)
        from PyQt6.QtCore import QSize
        return QSize(width, 0)

    def _update_line_number_width(self, _):
        width = self._line_number_area_size().width()
        self.setViewportMargins(width, 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self._line_number_area_size().width(), cr.height())
        )

    def _paint_line_numbers(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor(245, 245, 245))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number in self._break_lines:
                    painter.setPen(QColor(0, 100, 200))
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(QColor(150, 150, 150))
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)

                painter.drawText(
                    0, top, self._line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number,
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

        painter.end()
