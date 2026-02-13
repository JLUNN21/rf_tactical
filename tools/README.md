# RF Tactical Monitor - Tools Directory

Place external tool binaries here for automatic detection by the launcher scripts.

## dump1090 (ADS-B Decoder)

The ADS-B tab requires `dump1090` to decode 1090 MHz ADS-B transponder signals from aircraft.

### Windows
1. Download dump1090 for Windows:
   - [dump1090 by MalcolmRobb](https://github.com/MalcolmRobb/dump1090) (Windows fork)
   - Or compile [antirez/dump1090](https://github.com/antirez/dump1090) with MSYS2/MinGW
2. Place `dump1090.exe` in this `tools/` directory
3. Run `start_windows.bat` — it will auto-detect and launch dump1090

### Linux
1. Install via package manager:
   ```bash
   sudo apt install dump1090-mutability
   ```
   Or build from source:
   ```bash
   git clone https://github.com/antirez/dump1090
   cd dump1090 && make
   cp dump1090 /path/to/rf_tactical/tools/
   ```
2. Run `./start_linux.sh` — it will auto-detect and launch dump1090

### Network Mode
If dump1090 is running on another machine (e.g., a Raspberry Pi with an RTL-SDR):
- The app will try to connect to `127.0.0.1:30005` (Beast binary) or `127.0.0.1:30003` (SBS text)
- To connect to a remote host, set the host in `config/settings.yaml` under `adsb.host`

### Supported Protocols
- **Beast binary** (port 30005) — full message decoding via pyModeS
- **SBS BaseStation** (port 30003) — text CSV format, no pyModeS needed
