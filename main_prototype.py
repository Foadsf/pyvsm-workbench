import sys
import os

package_dir = os.path.dirname(os.path.abspath(__file__))
if package_dir not in sys.path:
    sys.path.insert(0, package_dir)
parent_dir = os.path.dirname(package_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PySide6.QtWidgets import QApplication

try:
    from ui.main_window import OpenVSMStudio
except ImportError:
    from OpenVSM.ui.main_window import OpenVSMStudio


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenVSM Studio")
    app.setOrganizationName("OpenVSM")
    studio = OpenVSMStudio()
    studio.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

