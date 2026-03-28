"""DiskExplorer – entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Launch the DiskExplorer GUI application."""
    try:
        from PyQt6.QtWidgets import QApplication
        from src.ui.main_window import MainWindow
    except ImportError as exc:
        print(
            f"Error: Could not import required packages.\n{exc}\n"
            "Please install dependencies: pip install PyQt6 psutil",
            file=sys.stderr,
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("DiskExplorer")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("DiskExplorer")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
