# RF Tactical Monitor - Architecture

## Overview

PyQt5 kiosk application for 800x480 touchscreen that uses HackRF One via SoapySDR for RF monitoring. Purple tactical theme with pyqtgraph waterfall/spectrum display.

## Directory Structure

```
rf_tactical/
├── main.py                          # App entry point, KioskMainWindow
├── preflight.py                     # Pre-flight build checker (run before launch)
├── start_windows.bat                # Windows launcher (radioconda + preflight + app)
├── start_linux.sh                   # Linux launcher
│
├── config/                          # Configuration files
│   ├── bands.yaml                   # Band definitions (ISM, cellular, ADS-B)
│   ├── settings.yaml                # App settings (gains, UI prefs)
│   ├── device_presets.yaml          # Known device frequency presets
│   ├── signal_library.json          # Signal fingerprint database
│   └── theme.qss                    # Purple tactical QSS theme
│
├── radio/                           # SDR hardware interface
│   ├── sdr_manager.py               # SDRManager: QThread wrapper, signal routing
│   ├── sdr_worker.py                # SDRWorker: HackRF IQ capture, FFT, detection, TX
│   ├── iq_recorder.py               # IQRecorder: raw IQ file writer + metadata JSON
│   └── iq_player.py                 # IQPlayer: IQ file playback via HackRF TX
│
├── decoders/                        # Protocol decoders (each runs on own thread)
│   ├── adsb_decoder.py              # ADS-B via dump1090 network (Beast/SBS)
│   ├── adsb_sdr.py                  # ADS-B via HackRF direct IQ decode at 1090 MHz
│   ├── ism_decoder.py               # ISM 433MHz via rtl_433 JSON parser
│   ├── wifi_scanner.py              # Wi-Fi via iwlist/nmcli
│   ├── ble_scanner.py               # BLE via bleak async scanner
│   └── cellular_scanner.py          # Cellular via hackrf_sweep 700-2700 MHz
│
├── ui/                              # PyQt5 UI widgets
│   ├── waterfall_widget.py          # TacticalWaterfall: FFT spectrum + scrolling waterfall
│   ├── adsb_view.py                 # ADSBView: aircraft table
│   ├── ism_view.py                  # ISMView: waterfall + device table + signal inspector
│   ├── wifi_view.py                 # WiFiView: Wi-Fi + BLE tables
│   ├── cellular_view.py             # CellularView: cellular band table + sweep waterfall
│   ├── scanner_view.py              # ScannerView: waterfall + freq/gain controls + TX
│   ├── signal_inspector.py          # SignalInspector: signal detail + classification
│   ├── settings_dialog.py           # SettingsDialog: config editor
│   ├── log_view.py                  # LogView: live log stream
│   └── touch_table.py              # TouchTableView: touch-friendly table
│
├── utils/                           # Processing utilities
│   ├── spectrum_analyzer.py         # FFT averaging, peak detection, baseline, anomaly
│   ├── signal_detector.py           # V1: simple threshold-based detection
│   ├── signal_detector_v2.py        # V2: frequency-domain segmentation + event tracking
│   ├── signal_classifier.py         # Band/modulation/threat classification
│   ├── signal_library.py            # JSON fingerprint database for matching
│   ├── signal_replay.py             # OOK signal reconstruction from detection params
│   ├── tx_signal_generator.py       # 15 TX modes (CW/FM/AM/OOK/Noise/Chirp/Morse/etc)
│   ├── demodulator.py               # V1: FSK/OOK demod with Manchester decoding
│   ├── demodulator_v2.py            # V2: 8-mode demod (NBFM/WBFM/AM/USB/LSB/CW)
│   ├── ook_demodulator.py           # OOK: envelope detection, pulse classification
│   ├── sweep_engine.py              # hackrf_sweep subprocess wrapper
│   ├── device_presets.py            # YAML-based frequency preset database
│   ├── repetition_detector.py       # Groups repeated signal detections
│   ├── performance.py               # CPU/temp/FPS monitoring
│   ├── config.py                    # YAML config loader
│   ├── logger.py                    # Logging setup
│   ├── crash_handler.py             # Crash handler
│   ├── diagnostic_logger.py         # Structured component lifecycle logging
│   ├── flow_tracer.py               # Debug signal flow tracing
│   └── table_style.py               # Table styling helper
│
├── network/                         # Network integration
│   ├── cot_sender.py                # CoT UDP sender for ATAK
│   └── cot_templates.py             # CoT XML builders
│
├── tests/                           # Test files
│   ├── test_hackrf.py               # HackRF hardware test
│   ├── test_sdr_probe.py            # SDR probe test
│   ├── test_platform_guards.py      # Platform guard tests
│   ├── signal_detector_debug.py     # Signal detector debug tool
│   └── test_detector_fix.py         # Detector fix verification
│
├── tools/                           # Development tools
│   ├── adsb_test_feed.py            # Simulated ADS-B feed server
│   ├── check_syntax.py              # Syntax checker
│   ├── fix_unicode_all.py           # Unicode fixer
│   └── test_soapy.bat               # SoapySDR test script
│
├── assets/                          # Static assets (icons, etc.)
└── recordings/                      # IQ recording output directory
```

## Tab Functionality

| Tab | Antenna | Frequency | SDR? | Decoder | What It Does |
|-----|---------|-----------|------|---------|-------------|
| **ADS-B** | 1090 MHz | 1090 MHz | Yes (direct IQ) | `adsb_sdr.py` | Decodes aircraft transponders, shows flight table |
| **ISM** | 433 MHz | 390-440 MHz | Yes (waterfall) | `ism_decoder.py` + `sdr_worker.py` | Shows ISM device signals, waterfall, signal detection |
| **WI-FI/BLE** | 2.4 GHz | N/A | No | `wifi_scanner.py` + `ble_scanner.py` | Scans Wi-Fi networks and BLE devices via OS tools |
| **CELLULAR** | Wideband | 700-2700 MHz | No (hackrf_sweep) | `cellular_scanner.py` | Sweeps cellular bands, shows active frequencies |
| **SCANNER** | Any | User-set | Yes (waterfall) | `sdr_worker.py` | Manual frequency tuning, waterfall, TX generator |
| **LOGS** | N/A | N/A | No | N/A | Live system log stream |

## Signal Flow

```
HackRF One
    |
    v
SoapySDR (driver=hackrf)
    |
    v
SDRWorker (radio/sdr_worker.py)
    |-- IQ samples -> FFT -> magnitude_db
    |-- SpectrumAnalyzer -> stats (noise floor, peaks)
    |-- SignalDetectorV2 -> signal events
    |
    v
SDRManager (radio/sdr_manager.py)
    |-- new_waterfall_row -> TacticalWaterfall
    |-- spectrum_stats_updated -> main.py status
    |-- signal_event_detected -> ISMView inspector
    |
    v
KioskMainWindow (main.py)
    |-- Routes data to active tab's waterfall
    |-- Manages tab switching and SDR retuning
    |-- CoT sender for ATAK integration
```

## ADS-B Signal Flow (Direct SDR)

```
HackRF One @ 1090 MHz, 2 Msps
    |
    v
ADSBSDRDecoder (decoders/adsb_sdr.py)
    |-- IQ -> magnitude envelope
    |-- Mode S preamble detection (8 high/low positions)
    |-- PPM bit extraction (112 bits)
    |-- CRC=0 validation (DF17/18 only)
    |-- pyModeS decode (callsign, position, altitude, velocity)
    |
    v
ADSBSDRManager -> aircraft_updated signal
    |
    v
ADSBView (ui/adsb_view.py) -> aircraft table
```

## Key Design Decisions

1. **SDR per tab**: Only one SDR stream at a time. Switching tabs retunes the HackRF.
2. **ADS-B uses separate SDR instance**: `adsb_sdr.py` opens its own SoapySDR device at 1090 MHz, independent of the main SDR manager.
3. **Non-SDR tabs**: Wi-Fi/BLE/Cellular use OS tools or subprocess calls, not the HackRF directly.
4. **Purple theme**: All UI uses `#BB86FC` (primary), `#D4A0FF` (bright), `#2D1B4E` (border), `#0A0A0F` (background).
5. **Kiosk mode**: Frameless window, touch-friendly, swipe to change tabs.

## Pre-Flight Check

Run `python preflight.py --full` before every launch. See **[PREFLIGHT.md](PREFLIGHT.md)** for full documentation.

9 check sections:
1. **Syntax** — All 57 .py files parse without errors
2. **Imports** — All 42 modules import successfully
3. **Config** — 5 config files exist and parse
4. **Dependencies** — Required (PyQt5, pyqtgraph, numpy, yaml) + optional (SoapySDR, pyModeS, bleak)
5. **SDR** — HackRF hardware detection via SoapySDR
6. **Signal Wiring** — PyQt signals exist on key manager classes
7. **Main App** — KioskMainWindow class and 13 key methods exist
8. **UI Wiring** (`--full` only) — Buttons, tabs, waterfalls, signal connections, initial states
9. **Unicode** — No cp1252-breaking characters in source files

When adding new features, update both `preflight.py` and `PREFLIGHT.md`. See the "How to Add a New Check" section in PREFLIGHT.md.
