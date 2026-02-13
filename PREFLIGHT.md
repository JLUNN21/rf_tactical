# RF Tactical Monitor - Pre-Flight Check System

## Purpose

`preflight.py` is a build-health checker that runs **before every app launch**. It catches broken imports, missing configs, disconnected signals, and UI wiring bugs before the user sees a crash. The Windows launcher (`start_windows.bat`) runs it automatically with `--full`.

## Usage

```bash
python preflight.py          # Quick check (no hardware, no GUI)
python preflight.py --full   # Full check (probes HackRF, creates window, tests buttons)
```

## Exit Codes

| Code | Meaning | Launcher Behavior |
|------|---------|-------------------|
| `0` | All checks pass | Launches app |
| `1` | Critical failures | **Blocks launch**, shows errors |
| `2` | Warnings only | Launches app with degraded features |

## Check Sections

### 1. Syntax Check (`check_syntax`)
- Walks all `.py` files (excluding `__pycache__`, `.git`, `assets`, `tools`, `recordings`)
- Parses each with `ast.parse()` to catch syntax errors
- **FAIL** if any file has a syntax error

### 2. Import Check (`check_imports`)
- Imports every module in the project via `importlib.import_module()`
- Organized by category: core, radio, decoders, ui, utils, network
- Core modules (utils.logger, utils.config, etc.) → **FAIL** on import error
- Non-core modules → **WARN** on import error (app can still start)

**Module lists to update when adding new files:**
```python
core_modules = [...]      # Must-have utilities
radio_modules = [...]     # SDR hardware interface
decoder_modules = [...]   # Protocol decoders
ui_modules = [...]        # PyQt5 UI widgets
utils_modules = [...]     # Processing utilities
network_modules = [...]   # Network integration
```

### 3. Config Check (`check_config`)
- Verifies these files exist and are non-empty:
  - `config/bands.yaml` — Band definitions
  - `config/settings.yaml` — App settings
  - `config/device_presets.yaml` — Device presets
  - `config/signal_library.json` — Signal fingerprints
  - `config/theme.qss` — UI theme stylesheet
- Loads `ConfigManager` and validates band configs (`ism_433`, `cellular_lte`)

### 4. Dependency Check (`check_dependencies`)
- **Required** (FAIL if missing): PyQt5, pyqtgraph, numpy, yaml
- **Optional** (WARN if missing): SoapySDR, pyModeS, bleak

### 5. SDR Check (`check_sdr`)
- Quick mode: checks `SDR_AVAILABLE` flag from `radio.sdr_manager`
- Full mode (`--full`): probes HackRF via `SoapySDR.Device.enumerate("driver=hackrf")`
- Reports serial number if found

### 6. Signal Wiring Check (`check_signals`)
- Verifies key classes have expected PyQt signals/methods as attributes
- Checks these classes:

| Class | Module | Expected Signals/Methods |
|-------|--------|------------------------|
| `SDRManager` | `radio.sdr_manager` | `new_waterfall_row`, `spectrum_stats_updated`, `signal_event_detected`, `signal_event_closed`, `error_occurred`, `device_connected`, `capture_started`, `capture_stopped` |
| `ADSBSDRManager` | `decoders.adsb_sdr` | `aircraft_updated`, `error_occurred`, `decoder_started`, `decoder_stopped`, `stats_updated` |
| `ADSBSDRDecoder` | `decoders.adsb_sdr` | All signals + `start_decoder`, `stop_decoder`, `_open_sdr`, `_close_sdr`, `_detect_adsb_messages`, `_decode_message` |
| `ADSBDecoderManager` | `decoders.adsb_decoder` | `aircraft_updated`, `error_occurred`, `decoder_started`, `decoder_stopped` |
| `CoTSenderManager` | `network.cot_sender` | `error_occurred`, `sender_started`, `sender_stopped` |

### 7. Main App Check (`check_main_constructable`)
- Imports `main.py` (without creating QApplication)
- Verifies `KioskMainWindow` class exists
- Verifies `main()` entry point exists
- Checks these key methods exist on `KioskMainWindow`:
  - `_build_ui`, `_setup_sdr`, `_setup_adsb`, `_setup_ism`
  - `_setup_wifi`, `_setup_ble`, `_setup_cellular`, `_setup_cot`
  - `_on_start`, `_on_stop`, `_on_tab_changed`
  - `_update_button_states`, `_render_status_bar`

### 8. UI Wiring Check (`check_ui_wiring`) — `--full` only
- Creates actual `KioskMainWindow` instance (requires QApplication)
- Tests:

| Check | What It Verifies | Pass Criteria |
|-------|-----------------|---------------|
| Buttons exist | All 5 buttons in `window.buttons` dict | `startButton`, `stopButton`, `markButton`, `scanButton`, `configButton` |
| Buttons visible | Each button `.isVisible()` and size > 10px | All visible with valid size |
| Buttons connected | Each button `.clicked` has ≥1 receiver | All connected to handlers |
| Initial states | START enabled, STOP disabled on ADS-B tab | Correct initial state |
| Decoder signals | `decoder_started`/`decoder_stopped` signals exist on ADS-B manager | Signals defined (receiver count checked if possible) |
| SDR signals | `running_changed` signal exists on SDR manager | Signal defined |
| Tabs present | All 6 tabs in tab widget | ADS-B, ISM, WI-FI/BLE, CELLULAR, SCANNER, LOGS |
| Waterfalls | All 3 waterfalls in `_waterfalls` dict | ISM, SCANNER, CELLULAR |
| Status bar | `status_label` has text content | Length > 10 chars |

### 9. Unicode Check (`check_unicode`)
- Scans all `.py` files for problematic Unicode characters that break `cp1252` encoding on Windows
- Blocked characters: checkmarks (✓✔), crosses (✗✘❌), lightning (⚡)
- These cause `UnicodeEncodeError` when printed to Windows console

## How to Add a New Check

### Adding a new module
1. Add it to the appropriate list in `check_imports()`:
   ```python
   # In the appropriate category list:
   ("your_package.your_module", "Description"),
   ```

### Adding a new config file
1. Add it to `config_files` dict in `check_config()`:
   ```python
   "config/your_file.yaml": "Description",
   ```

### Adding a new decoder/manager class
1. Add signal checks in `check_signals()`:
   ```python
   ("your_package.your_module", "YourClass", [
       "signal_one", "signal_two", "method_one",
   ]),
   ```

### Adding a new button
1. Add to `expected_buttons` list in `check_ui_wiring()`:
   ```python
   expected_buttons = ["startButton", "stopButton", ..., "yourNewButton"]
   ```
2. Add to `btn_signals` dict with its handler:
   ```python
   "yourNewButton": window._on_your_handler,
   ```

### Adding a new tab
1. Add to `expected_tabs` list in `check_ui_wiring()`:
   ```python
   expected_tabs = ["ADS-B", "ISM", ..., "YOUR TAB"]
   ```
2. If it has a waterfall, add to `expected_waterfalls`:
   ```python
   expected_waterfalls = ["ISM", "SCANNER", "CELLULAR", "YOUR TAB"]
   ```

### Adding a new key method to main.py
1. Add to `key_methods` list in `check_main_constructable()`:
   ```python
   key_methods = [
       '_build_ui', '_setup_sdr', ..., '_your_new_method',
   ]
   ```

### Adding a new dependency
1. Add to `required` or `optional` list in `check_dependencies()`:
   ```python
   # Required (FAIL if missing):
   ("PackageName", "import_name", "Description"),
   # Optional (WARN if missing):
   ("PackageName", "import_name", "Description"),
   ```

### Adding a new signal wiring check
1. If you add a new signal to a manager class, add it to `check_signals()`:
   ```python
   ("module.path", "ClassName", [
       "existing_signal", "your_new_signal",
   ]),
   ```
2. If the signal should be connected in `main.py`, consider adding a receiver check in `check_ui_wiring()`.

## Helper Functions

| Function | Purpose |
|----------|---------|
| `log_pass(msg)` | Record a passing check (green) |
| `log_warn(msg)` | Record a warning (yellow) — app can still start |
| `log_fail(msg)` | Record a failure (red) — blocks launch |
| `section(title)` | Print a section header |

## Integration with Launcher

`start_windows.bat` runs preflight automatically:
```batch
"%RADIOCONDA%\python.exe" preflight.py --full
set PREFLIGHT_RESULT=%ERRORLEVEL%
if %PREFLIGHT_RESULT% EQU 1 (
    echo PRE-FLIGHT FAILED
    pause
    exit /b 1
)
if %PREFLIGHT_RESULT% EQU 2 (
    echo Warnings detected but app can still run. Continuing...
)
```

## Current Stats (as of last run)

- **132 PASS**, 1 WARN (missing `bleak` for BLE), 0 FAIL
- Checks 57 Python files, 42 module imports, 5 config files, 7 dependencies
- Full run with UI wiring takes ~3 seconds
