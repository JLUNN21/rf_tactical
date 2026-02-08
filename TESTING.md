# RF Tactical Testing Checklist

## Windows Testing (No Hardware)

### Launch
- [ ] Double-click launch_rf_tactical.bat
- [ ] Window opens fullscreen
- [ ] No Python errors in console
- [ ] Status bar shows time updating

### UI Elements
- [ ] All 6 tabs visible: ADS-B, ISM, WI-FI/BLE, CELLULAR, SCANNER, LOGS
- [ ] All 5 buttons visible: START, STOP, MARK, SCAN, CONFIG
- [ ] START button disabled (dark green)
- [ ] CONFIG button enabled (bright green)
- [ ] Status bar shows: TIME | GPS: N/A | REC: IDLE | CPU: 0% | SDR: DISCONNECTED

### Tab Navigation
- [ ] Click each tab - no crashes
- [ ] Each tab shows appropriate content
- [ ] LOGS tab shows application logs

### Decoders (Windows)
- [ ] LOGS tab shows "DECODER OFFLINE" for each decoder
- [ ] No crashes from decoder errors

### Settings Dialog
- [ ] Click CONFIG button
- [ ] Dialog opens
- [ ] Brightness slider disabled/grayed
- [ ] Can change other settings
- [ ] Close dialog - no crash

## Windows Testing (With HackRF)

### Hardware Detection
- [ ] HackRF Pro plugged in via USB
- [ ] WinUSB driver installed (via Zadig)
- [ ] Launch app with launch_rf_tactical.bat
- [ ] Status bar shows: SDR: IDLE (not DISCONNECTED)
- [ ] START button enabled (bright green)

### SDR Start
- [ ] Navigate to ISM tab
- [ ] Click START button
- [ ] Status bar: SDR: CONNECTING... → SDR: ACTIVE @ 2.0 MSPS
- [ ] START button disabled
- [ ] STOP button enabled (bright red)
- [ ] MARK button enabled (bright amber)
- [ ] LOGS tab shows "Starting SDR on ISM-433..."

### Waterfall Display
- [ ] Waterfall starts scrolling
- [ ] Shows noise floor (green/yellow pattern)
- [ ] Spectrum plot at top shows signal
- [ ] FPS counter shows ~20-30 FPS

### Signal Detection
- [ ] Press 433 MHz remote (garage door, key fob)
- [ ] Waterfall shows bright line at signal
- [ ] Signal appears in device table below
- [ ] Signal inspector panel updates

### Recording
- [ ] Click REC button (red dot)
- [ ] Status bar: REC: 00:00:05 (counting up)
- [ ] Record for 10 seconds
- [ ] Click STOP button
- [ ] Check recordings/ folder has .iq and .json files
- [ ] File size > 0 bytes

### SDR Stop
- [ ] Click STOP button
- [ ] Status bar: SDR: IDLE
- [ ] Waterfall stops scrolling
- [ ] START button re-enabled

## Raspberry Pi Testing (Full Hardware)

### Initial Setup
- [ ] Git pull latest code
- [ ] Launch: python3 main.py
- [ ] All decoders show "ONLINE" in LOGS
- [ ] Status: SDR: IDLE

### ADS-B Tab
- [ ] Click START
- [ ] Aircraft appear in table
- [ ] Distance calculated correctly
- [ ] Altitude color-coded (green < 10k ft, amber 10-25k ft, cyan > 25k ft)

### ISM Tab
- [ ] Weather sensors appear
- [ ] Signal strength shown
- [ ] Battery status displayed
- [ ] Device type identified

### Wi-Fi/BLE Tab
- [ ] Wi-Fi networks listed
- [ ] BLE devices listed
- [ ] Signal strength bars displayed
- [ ] Can sort by signal/last seen

### Cellular Tab
- [ ] Cell towers detected
- [ ] Band information shown (LTE Band 2, 4, 12, etc.)
- [ ] Power levels displayed
- [ ] Operator identified

### Scanner Tab
- [ ] Set frequency range (start/stop/step)
- [ ] Adjust LNA/VGA gains
- [ ] Start sweep
- [ ] Peaks marked automatically
- [ ] Can tune to peak frequency

## Performance Testing

### CPU Usage
- [ ] SDR running: CPU < 70%
- [ ] Multiple decoders: CPU < 80%
- [ ] Long-term stable (30+ minutes)
- [ ] No thermal throttling

### Memory
- [ ] No memory leaks
- [ ] Memory stable over time
- [ ] RSS < 500 MB

### FPS
- [ ] Waterfall: 20-30 FPS
- [ ] No dropped frames
- [ ] Smooth scrolling

## Error Handling

### Missing Hardware
- [ ] Unplug HackRF
- [ ] Status: SDR: DISCONNECTED
- [ ] Click START - shows error in LOGS
- [ ] No crash

### Invalid Configuration
- [ ] Edit config/bands.yaml with invalid values
- [ ] App shows error message
- [ ] Doesn't crash
- [ ] Falls back to defaults

### Decoder Failures
- [ ] Kill rtl_433 process (Linux)
- [ ] ISM shows "DECODER ERROR"
- [ ] Can restart decoder
- [ ] No app crash

## Button State Testing

### No Hardware Connected
- [ ] START: disabled (dark green #006B1F)
- [ ] STOP: disabled (dark red #660000)
- [ ] MARK: disabled (dark amber #665000)
- [ ] SCAN: disabled (dark cyan #406070)
- [ ] CONFIG: enabled (bright green #00CC33)

### Hardware Connected, Not Running
- [ ] START: enabled (bright green #00FF41)
- [ ] STOP: disabled (dark red)
- [ ] MARK: disabled (dark amber)
- [ ] SCAN: enabled (bright cyan #80E0FF)
- [ ] CONFIG: enabled (bright green)

### SDR Running
- [ ] START: disabled (dark green)
- [ ] STOP: enabled (bright red #FF0000)
- [ ] MARK: enabled (bright amber #FFB000)
- [ ] SCAN: enabled (bright cyan)
- [ ] CONFIG: enabled (bright green)

## Touch/Mouse Interaction

### Touch Gestures
- [ ] Swipe left/right to change tabs
- [ ] Long-press on table row shows details
- [ ] Double-tap waterfall to center frequency
- [ ] Pinch-to-zoom on waterfall (if supported)

### Mouse Interaction
- [ ] Click tabs to switch
- [ ] Click buttons to activate
- [ ] Scroll waterfall with mouse wheel
- [ ] Right-click for context menu (if applicable)

## Logging and Debugging

### LOGS Tab
- [ ] Shows startup messages
- [ ] Shows decoder status changes
- [ ] Shows SDR connection events
- [ ] Shows button press events
- [ ] Shows errors in red
- [ ] Auto-scrolls to bottom

### Console Output
- [ ] No unhandled exceptions
- [ ] Deprecation warnings are acceptable
- [ ] No critical errors

## Known Issues

### Windows
- [ ] Decoders offline (expected - Linux only)
- [ ] GPS unavailable (expected - no gpsd on Windows)
- [ ] Brightness control disabled (expected - no backlight control)

### Linux/Raspberry Pi
- [ ] Document any platform-specific issues
- [ ] Note performance on Pi 4 vs Pi 5

### General
- [ ] Document any bugs found
- [ ] Note workarounds
- [ ] Report to developer

## Test Results Summary

**Date:** _____________  
**Tester:** _____________  
**Platform:** _____________  
**Hardware:** _____________  

**Pass Rate:** _____ / _____ (____%)

**Critical Issues:**
- 

**Minor Issues:**
- 

**Notes:**
- 
