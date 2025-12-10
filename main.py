from PyQt5 import QtWidgets, QtCore, QtGui
from backend import Backend
from PyQt5.QtGui import QFont
from gui.qt_adapter import QtBackendAdapter
from gui.mainwindow import OPCControlPanel
import sys

def main():
    app = QtWidgets.QApplication(sys.argv)

    
    font = app.font()
    font.setPointSize(11)                 
    app.setFont(font)

    # --- Splash-Screen im Vollbild ---
    splash_pix = QtGui.QPixmap(r"C:\Users\ALIS\Desktop\FLAVIA\loading.png")  # Pfad anpassen
    splash = QtWidgets.QSplashScreen(splash_pix)

    # immer im Vordergrund, ohne Fensterrahmen
    splash.setWindowFlags(
        QtCore.Qt.WindowStaysOnTopHint |
        QtCore.Qt.FramelessWindowHint
    )

    splash.showFullScreen()
    app.processEvents()  # sofort anzeigen

    # Klicks und Tasten sollen das Splash NICHT schließen
    splash.mousePressEvent = lambda event: None
    splash.mouseDoubleClickEvent = lambda event: None
    splash.keyPressEvent = lambda event: None   

    # Backend & Hauptfenster vorbereiten (aber noch NICHT zeigen)
    backend = Backend()
    adapter = QtBackendAdapter(backend)
    window = OPCControlPanel(backend, adapter)

    try:
        backend.start()
    except Exception as e:
        print(f"Backend start error: {e}")

    # nach 5 s Splash schließen und GUI zeigen
    def finish_startup():
        splash.close()
        window.showMaximized()
        window.raise_()
        window.activateWindow()

    QtCore.QTimer.singleShot(5000, finish_startup)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
