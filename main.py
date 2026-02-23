import os
import sys

from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Movie Finger Print")

    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    qss_path = os.path.join(base_dir, "gui", "style.qss")
    with open(qss_path) as f:
        stylesheet = f.read()
    # QSS url() paths are resolved relative to CWD; make them absolute
    # so the icons load correctly inside a PyInstaller bundle.
    stylesheet = stylesheet.replace("url(gui/", f"url({base_dir}/gui/")
    app.setStyleSheet(stylesheet)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
