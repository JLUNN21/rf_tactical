#!/usr/bin/env python3
"""RF Tactical Monitor - Pre-Flight Check

Run this before every launch to verify the build is healthy.
Checks: syntax, imports, signal wiring, SDR availability, config files.

Usage:
    python preflight.py          # Quick check (no SDR hardware needed)
    python preflight.py --full   # Full check (tests SDR hardware)

Exit codes:
    0 = All checks pass
    1 = Critical failures (app won't start)
    2 = Warnings (app starts but some features degraded)
"""

import sys
import os
import ast
import importlib
import traceback

# Ensure we're in the right directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

PASS = 0
WARN = 0
FAIL = 0
RESULTS = []


def log_pass(msg):
    global PASS
    PASS += 1
    RESULTS.append(("PASS", msg))
    print(f"  [PASS] {msg}")


def log_warn(msg):
    global WARN
    WARN += 1
    RESULTS.append(("WARN", msg))
    print(f"  [WARN] {msg}")


def log_fail(msg):
    global FAIL
    FAIL += 1
    RESULTS.append(("FAIL", msg))
    print(f"  [FAIL] {msg}")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# 1. SYNTAX CHECK - All .py files must parse
# ============================================================
def check_syntax():
    section("1. SYNTAX CHECK")
    py_files = []
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'assets', 'tools', 'recordings')]
        for fn in files:
            if fn.endswith('.py') and fn != 'preflight.py':
                py_files.append(os.path.join(root, fn))

    for fp in sorted(py_files):
        rel = os.path.relpath(fp, BASE_DIR)
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                ast.parse(f.read())
            log_pass(f"Syntax OK: {rel}")
        except SyntaxError as e:
            log_fail(f"Syntax ERROR: {rel}: {e}")


# ============================================================
# 2. IMPORT CHECK - All modules must import without error
# ============================================================
def check_imports():
    section("2. IMPORT CHECK")

    # Core modules (MUST work)
    core_modules = [
        ("utils.logger", "Logging system"),
        ("utils.config", "Configuration manager"),
        ("utils.crash_handler", "Crash handler"),
        ("utils.performance", "Performance monitor"),
        ("utils.diagnostic_logger", "Diagnostic logger"),
        ("utils.flow_tracer", "Flow tracer"),
    ]

    # Radio modules
    radio_modules = [
        ("radio.sdr_manager", "SDR manager"),
        ("radio.sdr_worker", "SDR worker"),
        ("radio.iq_recorder", "IQ recorder"),
        ("radio.iq_player", "IQ player"),
    ]

    # Decoder modules
    decoder_modules = [
        ("decoders.adsb_decoder", "ADS-B decoder (network)"),
        ("decoders.adsb_sdr", "ADS-B decoder (SDR direct)"),
        ("decoders.ism_decoder", "ISM decoder"),
        ("decoders.wifi_scanner", "Wi-Fi scanner"),
        ("decoders.ble_scanner", "BLE scanner"),
        ("decoders.cellular_scanner", "Cellular scanner"),
    ]

    # UI modules
    ui_modules = [
        ("ui.waterfall_widget", "Waterfall widget"),
        ("ui.adsb_view", "ADS-B view"),
        ("ui.ism_view", "ISM view"),
        ("ui.wifi_view", "Wi-Fi/BLE view"),
        ("ui.cellular_view", "Cellular view"),
        ("ui.scanner_view", "Scanner view"),
        ("ui.settings_dialog", "Settings dialog"),
        ("ui.log_view", "Log view"),
        ("ui.signal_inspector", "Signal inspector"),
        ("ui.touch_table", "Touch table"),
    ]

    # Utils modules
    utils_modules = [
        ("utils.spectrum_analyzer", "Spectrum analyzer"),
        ("utils.signal_detector", "Signal detector V1"),
        ("utils.signal_detector_v2", "Signal detector V2"),
        ("utils.signal_classifier", "Signal classifier"),
        ("utils.signal_library", "Signal library"),
        ("utils.repetition_detector", "Repetition detector"),
        ("utils.demodulator", "Demodulator V1"),
        ("utils.demodulator_v2", "Demodulator V2"),
        ("utils.ook_demodulator", "OOK demodulator"),
        ("utils.signal_replay", "Signal replay"),
        ("utils.tx_signal_generator", "TX signal generator"),
        ("utils.sweep_engine", "Sweep engine"),
        ("utils.device_presets", "Device presets"),
        ("utils.table_style", "Table styler"),
    ]

    # Network modules
    network_modules = [
        ("network.cot_sender", "CoT sender"),
        ("network.cot_templates", "CoT templates"),
    ]

    all_modules = core_modules + radio_modules + decoder_modules + ui_modules + utils_modules + network_modules

    for mod_name, description in all_modules:
        try:
            importlib.import_module(mod_name)
            log_pass(f"Import OK: {mod_name} ({description})")
        except Exception as e:
            err = str(e).split('\n')[0][:80]
            if mod_name in [m[0] for m in core_modules]:
                log_fail(f"Import FAIL: {mod_name} ({description}): {err}")
            else:
                log_warn(f"Import WARN: {mod_name} ({description}): {err}")


# ============================================================
# 3. CONFIG CHECK - Config files must exist and parse
# ============================================================
def check_config():
    section("3. CONFIG CHECK")

    config_files = {
        "config/bands.yaml": "Band definitions",
        "config/settings.yaml": "App settings",
        "config/device_presets.yaml": "Device presets",
        "config/signal_library.json": "Signal fingerprints",
        "config/theme.qss": "UI theme stylesheet",
    }

    for path, desc in config_files.items():
        fp = os.path.join(BASE_DIR, path)
        if os.path.exists(fp):
            size = os.path.getsize(fp)
            if size > 0:
                log_pass(f"Config OK: {path} ({desc}, {size} bytes)")
            else:
                log_warn(f"Config EMPTY: {path} ({desc})")
        else:
            log_fail(f"Config MISSING: {path} ({desc})")

    # Try loading config
    try:
        from utils.config import ConfigManager
        cfg = ConfigManager()
        bands = ['ism_433', 'cellular_lte']
        for band_key in bands:
            band = cfg.get_band(band_key)
            if band and band.center_freq_hz > 0:
                log_pass(f"Band config OK: {band_key} ({band.center_freq_hz/1e6:.3f} MHz)")
            else:
                log_warn(f"Band config MISSING: {band_key}")
    except Exception as e:
        log_fail(f"Config load FAIL: {e}")


# ============================================================
# 4. DEPENDENCY CHECK - Required Python packages
# ============================================================
def check_dependencies():
    section("4. DEPENDENCY CHECK")

    required = [
        ("PyQt5", "PyQt5.QtCore", "GUI framework"),
        ("pyqtgraph", "pyqtgraph", "Plotting library"),
        ("numpy", "numpy", "Numerical computing"),
        ("yaml", "yaml", "YAML config parser"),
    ]

    optional = [
        ("SoapySDR", "SoapySDR", "SDR hardware interface"),
        ("pyModeS", "pyModeS", "ADS-B message decoder"),
        ("bleak", "bleak", "BLE scanner"),
    ]

    for name, import_name, desc in required:
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, '__version__', getattr(mod, 'PYQT_VERSION_STR', '?'))
            log_pass(f"Required: {name} {ver} ({desc})")
        except ImportError:
            log_fail(f"Required MISSING: {name} ({desc}) -- pip install {name.lower()}")

    for name, import_name, desc in optional:
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, '__version__', '?')
            log_pass(f"Optional: {name} {ver} ({desc})")
        except ImportError:
            log_warn(f"Optional MISSING: {name} ({desc})")


# ============================================================
# 5. SDR CHECK - HackRF hardware availability
# ============================================================
def check_sdr(full=False):
    section("5. SDR CHECK")

    try:
        from radio.sdr_manager import SDR_AVAILABLE
        if SDR_AVAILABLE:
            log_pass("SDR_AVAILABLE = True (SoapySDR loaded)")
        else:
            log_warn("SDR_AVAILABLE = False (SoapySDR not loaded or no driver)")
    except Exception as e:
        log_warn(f"SDR check error: {e}")

    if not full:
        print("  (Skipping hardware probe -- use --full to test)")
        return

    try:
        import SoapySDR
        results = SoapySDR.Device.enumerate("driver=hackrf")
        if len(results) > 0:
            serial = dict(results[0]).get('serial', '?')
            log_pass(f"HackRF found: serial={serial}")
        else:
            log_warn("No HackRF device found (is it plugged in?)")
    except Exception as e:
        log_warn(f"HackRF probe error: {e}")


# ============================================================
# 6. SIGNAL WIRING CHECK - Verify key classes have expected signals
# ============================================================
def check_signals():
    section("6. SIGNAL WIRING CHECK")

    checks = [
        ("radio.sdr_manager", "SDRManager", [
            "new_waterfall_row", "spectrum_stats_updated", "signal_event_detected",
            "signal_event_closed", "error_occurred", "device_connected",
            "capture_started", "capture_stopped",
        ]),
        ("decoders.adsb_sdr", "ADSBSDRManager", [
            "aircraft_updated", "error_occurred", "decoder_started",
            "decoder_stopped", "stats_updated",
        ]),
        ("decoders.adsb_sdr", "ADSBSDRDecoder", [
            "aircraft_updated", "error_occurred", "decoder_started",
            "decoder_stopped", "stats_updated",
            "start_decoder", "stop_decoder", "_open_sdr", "_close_sdr",
            "_detect_adsb_messages", "_decode_message",
        ]),
        ("decoders.adsb_decoder", "ADSBDecoderManager", [
            "aircraft_updated", "error_occurred", "decoder_started", "decoder_stopped",
        ]),
        ("network.cot_sender", "CoTSenderManager", [
            "error_occurred", "sender_started", "sender_stopped",
        ]),
    ]

    for mod_name, cls_name, expected_attrs in checks:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            missing = [a for a in expected_attrs if not hasattr(cls, a)]
            if not missing:
                log_pass(f"Signals OK: {cls_name} ({len(expected_attrs)} attrs)")
            else:
                log_fail(f"Signals MISSING: {cls_name} missing: {', '.join(missing)}")
        except Exception as e:
            log_fail(f"Signal check FAIL: {mod_name}.{cls_name}: {e}")


# ============================================================
# 7. MAIN APP CHECK - Verify main.py can construct the window
# ============================================================
def check_main_constructable():
    section("7. MAIN APP CHECK")

    try:
        # Just verify main.py imports work (don't create QApplication)
        import main
        if hasattr(main, 'KioskMainWindow'):
            log_pass("KioskMainWindow class exists")
        else:
            log_fail("KioskMainWindow class NOT FOUND in main.py")

        if hasattr(main, 'main'):
            log_pass("main() entry point exists")
        else:
            log_fail("main() entry point NOT FOUND")

        # Check key methods exist
        klass = main.KioskMainWindow
        key_methods = [
            '_build_ui', '_setup_sdr', '_setup_adsb', '_setup_ism',
            '_setup_wifi', '_setup_ble', '_setup_cellular', '_setup_cot',
            '_on_start', '_on_stop', '_on_tab_changed',
            '_update_button_states', '_render_status_bar',
        ]
        missing = [m for m in key_methods if not hasattr(klass, m)]
        if not missing:
            log_pass(f"Main methods OK ({len(key_methods)} methods)")
        else:
            log_fail(f"Main methods MISSING: {', '.join(missing)}")

    except Exception as e:
        log_fail(f"Main app check FAIL: {e}")
        traceback.print_exc()


# ============================================================
# 8. UI WIRING CHECK - Verify buttons, signals, and state logic
# ============================================================
def check_ui_wiring():
    section("8. UI WIRING CHECK")

    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt

        # Create or reuse QApplication (needed for widget instantiation)
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
            app.setApplicationName("RF Tactical Preflight")

        # Load theme
        from PyQt5.QtCore import QFile, QTextStream
        qss_path = os.path.join(BASE_DIR, "config", "theme.qss")
        qf = QFile(qss_path)
        if qf.open(QFile.ReadOnly | QFile.Text):
            app.setStyleSheet(QTextStream(qf).readAll())
            qf.close()

        # Create the main window
        from main import KioskMainWindow
        window = KioskMainWindow()
        window.show()

        # --- Check buttons exist ---
        expected_buttons = ["startButton", "stopButton", "markButton", "scanButton", "configButton"]
        missing_buttons = [b for b in expected_buttons if b not in window.buttons]
        if missing_buttons:
            log_fail(f"Missing buttons: {', '.join(missing_buttons)}")
        else:
            log_pass(f"All {len(expected_buttons)} buttons exist")

        # --- Check button visibility and size ---
        all_visible = True
        for name in expected_buttons:
            if name not in window.buttons:
                continue
            btn = window.buttons[name]
            if not btn.isVisible():
                log_fail(f"Button {name} is NOT visible")
                all_visible = False
            if btn.size().width() < 10 or btn.size().height() < 10:
                log_fail(f"Button {name} has zero/tiny size: {btn.size().width()}x{btn.size().height()}")
                all_visible = False
        if all_visible:
            log_pass("All buttons visible with valid size")

        # --- Check button signal connections ---
        btn_signals = {
            "startButton": window._on_start,
            "stopButton": window._on_stop,
            "markButton": window._on_mark,
            "scanButton": window._on_scan,
            "configButton": window._on_config,
        }
        all_connected = True
        for name, handler in btn_signals.items():
            if name not in window.buttons:
                continue
            btn = window.buttons[name]
            receivers = btn.receivers(btn.clicked)
            if receivers < 1:
                log_fail(f"Button {name}.clicked has 0 receivers (not connected!)")
                all_connected = False
        if all_connected:
            log_pass("All button clicked signals connected")

        # --- Check initial button states on ADS-B tab ---
        tab_name = window._active_tab or ""
        if tab_name == "ADS-B":
            start_btn = window.buttons["startButton"]
            stop_btn = window.buttons["stopButton"]
            if start_btn.isEnabled():
                log_pass("START enabled on ADS-B tab (correct)")
            else:
                log_fail("START disabled on ADS-B tab (should be enabled)")
            if not stop_btn.isEnabled():
                log_pass("STOP disabled before start (correct)")
            else:
                log_warn("STOP enabled before start (unexpected)")
        else:
            log_warn(f"Initial tab is '{tab_name}', expected 'ADS-B'")

        # --- Check decoder start/stop updates button states ---
        # Use QObject.receivers() which takes a SIGNAL signature, not pyqtBoundSignal
        if hasattr(window, '_adsb_manager') and window._adsb_manager is not None:
            mgr = window._adsb_manager
            # receivers() is a QObject method that takes a signal's C++ signature
            try:
                from PyQt5.QtCore import SIGNAL
                started_receivers = mgr.receivers(SIGNAL("decoder_started(QString)"))
                stopped_receivers = mgr.receivers(SIGNAL("decoder_stopped()"))
                # decoder_started connects to: adsb_view.set_status + _update_button_states (lambda)
                if started_receivers >= 2:
                    log_pass(f"ADS-B decoder_started has {started_receivers} receivers (includes button update)")
                elif started_receivers >= 1:
                    log_warn(f"ADS-B decoder_started has only {started_receivers} receiver(s) -- button states may not update")
                else:
                    log_fail(f"ADS-B decoder_started has 0 receivers -- signal not connected!")
                # decoder_stopped connects to: lambda set_status + _update_button_states
                if stopped_receivers >= 2:
                    log_pass(f"ADS-B decoder_stopped has {stopped_receivers} receivers (includes button update)")
                elif stopped_receivers >= 1:
                    log_warn(f"ADS-B decoder_stopped has only {stopped_receivers} receiver(s) -- button states may not update")
                else:
                    log_fail(f"ADS-B decoder_stopped has 0 receivers -- signal not connected!")
            except Exception as e:
                # Fallback: just check the manager has the signals defined
                has_started = hasattr(mgr, 'decoder_started')
                has_stopped = hasattr(mgr, 'decoder_stopped')
                if has_started and has_stopped:
                    log_pass("ADS-B decoder signals exist (receiver count unavailable)")
                else:
                    log_fail(f"ADS-B decoder missing signals: started={has_started} stopped={has_stopped}")
        else:
            log_warn("ADS-B manager not initialized")

        # --- Check SDR manager running_changed signal ---
        if hasattr(window, '_sdr_manager') and window._sdr_manager is not None:
            mgr = window._sdr_manager
            try:
                from PyQt5.QtCore import SIGNAL
                running_receivers = mgr.receivers(SIGNAL("running_changed(bool)"))
                if running_receivers >= 1:
                    log_pass(f"SDR running_changed has {running_receivers} receiver(s)")
                else:
                    log_fail("SDR running_changed has 0 receivers -- button states won't update on SDR start/stop!")
            except Exception:
                if hasattr(mgr, 'running_changed'):
                    log_pass("SDR running_changed signal exists (receiver count unavailable)")
                else:
                    log_fail("SDR running_changed signal missing!")
        else:
            log_warn("SDR manager not initialized")

        # --- Check tab widget ---
        tab_count = window.tab_widget.count()
        expected_tabs = ["ADS-B", "ISM", "WI-FI/BLE", "CELLULAR", "SCANNER", "LOGS"]
        actual_tabs = [window.tab_widget.tabText(i) for i in range(tab_count)]
        missing_tabs = [t for t in expected_tabs if t not in actual_tabs]
        if missing_tabs:
            log_fail(f"Missing tabs: {', '.join(missing_tabs)}")
        else:
            log_pass(f"All {len(expected_tabs)} tabs present")

        # --- Check waterfalls exist for SDR tabs ---
        expected_waterfalls = ["ISM", "SCANNER", "CELLULAR"]
        missing_wf = [w for w in expected_waterfalls if w not in window._waterfalls]
        if missing_wf:
            log_fail(f"Missing waterfalls: {', '.join(missing_wf)}")
        else:
            log_pass(f"All {len(expected_waterfalls)} waterfalls initialized")

        # --- Check status bar ---
        if hasattr(window, 'status_label') and window.status_label is not None:
            text = window.status_label.text()
            if len(text) > 10:
                log_pass("Status bar has content")
            else:
                log_warn("Status bar appears empty")
        else:
            log_fail("Status bar label not found")

        # Cleanup
        window._allow_close = True
        window.close()

    except Exception as e:
        log_fail(f"UI wiring check FAIL: {e}")
        traceback.print_exc()


# ============================================================
# 9. UNICODE CHECK - No problematic Unicode in .py files
# ============================================================
def check_unicode():
    section("9. UNICODE CHECK")

    bad_chars = {
        '\u2713': 'checkmark', '\u2714': 'checkmark',
        '\u2717': 'cross', '\u2718': 'cross', '\u274C': 'cross',
        '\u26A1': 'lightning',
    }

    issues = 0
    checked = 0
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'assets', 'tools')]
        for fn in files:
            if not fn.endswith('.py'):
                continue
            fp = os.path.join(root, fn)
            checked += 1
            with open(fp, 'r', encoding='utf-8') as f:
                content = f.read()
            for char, name in bad_chars.items():
                if char in content:
                    rel = os.path.relpath(fp, BASE_DIR)
                    log_warn(f"Unicode {name} (U+{ord(char):04X}) in {rel}")
                    issues += 1

    if issues == 0:
        log_pass(f"Unicode clean ({checked} files checked)")


# ============================================================
# SUMMARY
# ============================================================
def print_summary():
    print(f"\n{'='*60}")
    print(f"  PREFLIGHT SUMMARY")
    print(f"{'='*60}")
    print(f"  PASS: {PASS}")
    print(f"  WARN: {WARN}")
    print(f"  FAIL: {FAIL}")
    print(f"{'='*60}")

    if FAIL > 0:
        print("\n  RESULT: FAILED -- Fix critical issues before launching")
        print("  Failed items:")
        for status, msg in RESULTS:
            if status == "FAIL":
                print(f"    - {msg}")
        return 1
    elif WARN > 0:
        print("\n  RESULT: PASS WITH WARNINGS -- App will start but some features may be degraded")
        return 2
    else:
        print("\n  RESULT: ALL CLEAR -- Ready to launch!")
        return 0


def main():
    full = "--full" in sys.argv

    print("=" * 60)
    print("  RF TACTICAL MONITOR - PRE-FLIGHT CHECK")
    print("=" * 60)
    print(f"  Base dir: {BASE_DIR}")
    print(f"  Python:   {sys.executable}")
    print(f"  Version:  {sys.version.split()[0]}")
    print(f"  Mode:     {'FULL (with hardware)' if full else 'QUICK (no hardware)'}")

    check_syntax()
    check_imports()
    check_config()
    check_dependencies()
    check_sdr(full=full)
    check_signals()
    check_main_constructable()
    if full:
        check_ui_wiring()
    else:
        print("\n" + "=" * 60)
        print("  8. UI WIRING CHECK")
        print("=" * 60)
        print("  (Skipping UI wiring check -- use --full to test buttons/signals)")
    check_unicode()

    exit_code = print_summary()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
