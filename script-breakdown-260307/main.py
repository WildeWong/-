"""Script Breakdown application entry point."""
import sys

from PyQt6.QtWidgets import QApplication

from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("剧本拆解")
    app.setApplicationDisplayName("剧本拆解 - Script Breakdown")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
