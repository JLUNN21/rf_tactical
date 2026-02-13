#!/usr/bin/env python3
"""Simulated ADS-B SBS feed for testing.

Runs a TCP server on port 30003 that emits SBS BaseStation format
messages simulating aircraft in the area. Use this to test the
ADS-B tab when no real dump1090/HackRF is available.

Usage:
    python tools/adsb_test_feed.py

Then press START on the ADS-B tab - it will connect to localhost:30003.
"""

import socket
import time
import math
import random
import threading
import sys

# Simulated aircraft definitions
AIRCRAFT = [
    {"icao": "A1B2C3", "callsign": "UAL1234", "lat": 32.90, "lon": -96.80, "alt_ft": 35000, "speed_kts": 450, "heading": 270, "vrate_fpm": 0},
    {"icao": "D4E5F6", "callsign": "AAL567", "lat": 33.10, "lon": -97.00, "alt_ft": 28000, "speed_kts": 380, "heading": 180, "vrate_fpm": -500},
    {"icao": "789ABC", "callsign": "SWA890", "lat": 32.70, "lon": -96.50, "alt_ft": 12000, "speed_kts": 250, "heading": 90, "vrate_fpm": 1500},
    {"icao": "DEF012", "callsign": "DAL42", "lat": 33.00, "lon": -96.90, "alt_ft": 41000, "speed_kts": 520, "heading": 45, "vrate_fpm": 0},
    {"icao": "345678", "callsign": "RCH401", "lat": 32.80, "lon": -97.20, "alt_ft": 22000, "speed_kts": 350, "heading": 315, "vrate_fpm": 2000},  # Military (REACH)
    {"icao": "9ABCDE", "callsign": "N172SP", "lat": 32.95, "lon": -96.70, "alt_ft": 3500, "speed_kts": 110, "heading": 120, "vrate_fpm": 500},   # GA
    {"icao": "F01234", "callsign": "FDX891", "lat": 33.20, "lon": -96.60, "alt_ft": 38000, "speed_kts": 480, "heading": 200, "vrate_fpm": 0},
    {"icao": "567890", "callsign": "JBU223", "lat": 32.60, "lon": -97.10, "alt_ft": 8000, "speed_kts": 200, "heading": 350, "vrate_fpm": -1200},
]


def update_aircraft(ac, dt_sec):
    """Move aircraft based on heading and speed."""
    speed_deg_per_sec = (ac["speed_kts"] / 3600.0) / 60.0  # rough nm->deg
    heading_rad = math.radians(ac["heading"])
    
    ac["lat"] += speed_deg_per_sec * math.cos(heading_rad) * dt_sec
    ac["lon"] += speed_deg_per_sec * math.sin(heading_rad) * dt_sec
    ac["alt_ft"] += ac["vrate_fpm"] / 60.0 * dt_sec
    
    # Add slight heading drift
    ac["heading"] = (ac["heading"] + random.uniform(-0.5, 0.5)) % 360
    
    # Clamp altitude
    ac["alt_ft"] = max(1000, min(45000, ac["alt_ft"]))
    
    # Occasionally change vertical rate
    if random.random() < 0.02:
        ac["vrate_fpm"] = random.choice([0, 0, 0, 500, -500, 1000, -1000, 1500, -1500])


def generate_sbs_messages(ac):
    """Generate SBS BaseStation format messages for one aircraft."""
    now = time.strftime("%Y/%m/%d,%H:%M:%S.000")
    msgs = []
    
    # MSG type 1: callsign
    msgs.append(f"MSG,1,1,1,{ac['icao']},{ac['icao']},{now},{now},{ac['callsign']},,,,,,,,,,\n")
    
    # MSG type 3: position + altitude
    msgs.append(f"MSG,3,1,1,{ac['icao']},{ac['icao']},{now},{now},,{ac['alt_ft']:.0f},,,"
                f"{ac['lat']:.6f},{ac['lon']:.6f},,,0,0,0,0\n")
    
    # MSG type 4: velocity
    msgs.append(f"MSG,4,1,1,{ac['icao']},{ac['icao']},{now},{now},,,{ac['speed_kts']:.0f},"
                f"{ac['heading']:.1f},,,{ac['vrate_fpm']:.0f},,,,\n")
    
    return msgs


def handle_client(conn, addr):
    """Send SBS data to a connected client."""
    print(f"[+] Client connected: {addr}")
    try:
        while True:
            for ac in AIRCRAFT:
                update_aircraft(ac, 1.0)
                msgs = generate_sbs_messages(ac)
                for msg in msgs:
                    conn.sendall(msg.encode("ascii"))
            time.sleep(1.0)
    except (BrokenPipeError, ConnectionResetError, OSError):
        print(f"[-] Client disconnected: {addr}")
    finally:
        conn.close()


def main():
    host = "127.0.0.1"
    port = 30003
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((host, port))
    except OSError as e:
        print(f"ERROR: Cannot bind to {host}:{port} - {e}")
        print("Is dump1090 or another SBS server already running?")
        sys.exit(1)
    
    server.listen(5)
    print(f"=" * 60)
    print(f"  ADS-B Test Feed Server")
    print(f"  SBS BaseStation format on {host}:{port}")
    print(f"  Simulating {len(AIRCRAFT)} aircraft")
    print(f"=" * 60)
    print(f"Now press START on the ADS-B tab in RF Tactical Monitor.")
    print(f"Press Ctrl+C to stop.\n")
    
    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nShutting down test feed server.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
