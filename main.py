import os
import sys

from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Movie Finger Print")

    qss_path = os.path.join(os.path.dirname(__file__), "gui", "style.qss")
    with open(qss_path) as f:
        app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
