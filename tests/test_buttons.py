#!/usr/bin/env python3
"""Quick diagnostic: create the main window and check button states."""
import sys, os, io

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPORT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "button_report.txt")

def report(msg):
    print(msg)
    with open(REPORT_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# Clear report file
with open(REPORT_FILE, "w", encoding="utf-8") as f:
    f.write("")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtTest import QTest

app = QApplication(sys.argv)
app.setApplicationName("RF Tactical Button Test")

# Load theme
from PyQt5.QtCore import QFile, QTextStream
qss_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "theme.qss")
qf = QFile(qss_path)
if qf.open(QFile.ReadOnly | QFile.Text):
    app.setStyleSheet(QTextStream(qf).readAll())
    qf.close()

from main import KioskMainWindow

report("Creating KioskMainWindow...")
window = KioskMainWindow()
window.show()

def run_diagnostics():
    report("\n" + "=" * 60)
    report("BUTTON DIAGNOSTICS")
    report("=" * 60)
    
    # Check active tab
    report(f"Active tab: {window._active_tab!r}")
    report(f"Tab count: {window.tab_widget.count()}")
    report(f"Current index: {window.tab_widget.currentIndex()}")
    report(f"Current tab text: {window.tab_widget.tabText(window.tab_widget.currentIndex())!r}")
    
    # Check all buttons
    for name, btn in window.buttons.items():
        report(f"\nButton: {name}")
        report(f"  Enabled: {btn.isEnabled()}")
        report(f"  Visible: {btn.isVisible()}")
        report(f"  Size: {btn.size().width()}x{btn.size().height()}")
        report(f"  Pos: ({btn.x()}, {btn.y()})")
        report(f"  FocusPolicy: {btn.focusPolicy()}")
        # Check if button is obscured
        parent = btn.parentWidget()
        if parent:
            report(f"  Parent: {parent.objectName()!r} visible={parent.isVisible()} size={parent.size().width()}x{parent.size().height()}")
            gparent = parent.parentWidget()
            if gparent:
                report(f"  GrandParent: {gparent.objectName()!r} visible={gparent.isVisible()}")
    
    # Check SDR state
    report(f"\nSDR manager: {window._sdr_manager is not None}")
    if window._sdr_manager:
        report(f"  is_connected: {window._sdr_manager.is_connected()}")
        report(f"  is_running: {window._sdr_manager.is_running}")
    
    report(f"\nADS-B manager: {window._adsb_manager is not None}")
    if window._adsb_manager:
        report(f"  is_running: {window._adsb_manager.is_running}")
    
    # Check signal connections
    start_btn = window.buttons["startButton"]
    report(f"\nSTART button receivers: {start_btn.receivers(start_btn.clicked)}")
    stop_btn = window.buttons["stopButton"]
    report(f"STOP button receivers: {stop_btn.receivers(stop_btn.clicked)}")
    
    # Try clicking START
    report("\n--- Simulating START click ---")
    if start_btn.isEnabled():
        report("START is ENABLED - clicking...")
        start_btn.click()  # Use click() instead of QTest.mouseClick
        report("Click sent!")
    else:
        report("START is DISABLED - cannot click")
        report("Forcing enable and clicking...")
        start_btn.setEnabled(True)
        start_btn.click()
        report("Force click sent!")
    
    # Wait a moment then check state
    QTimer.singleShot(3000, check_after_start)

def check_after_start():
    report("\n--- After START click (3s) ---")
    if window._adsb_manager:
        report(f"ADS-B running: {window._adsb_manager.is_running}")
    if window._sdr_manager:
        report(f"SDR running: {window._sdr_manager.is_running}")
    
    for name, btn in window.buttons.items():
        report(f"  {name}: enabled={btn.isEnabled()}")
    
    report("\n" + "=" * 60)
    report("DIAGNOSTICS COMPLETE")
    report("=" * 60)
    report(f"\nFull report saved to: {REPORT_FILE}")
    
    # Close after diagnostics
    window._allow_close = True
    window.close()
    app.quit()

# Run diagnostics after window is shown
QTimer.singleShot(1000, run_diagnostics)

sys.exit(app.exec_())
