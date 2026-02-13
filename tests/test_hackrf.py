"""Quick HackRF diagnostic script"""
import os
import sys

print("=" * 60)
print("HackRF Diagnostic Test")
print("=" * 60)

# Check environment
print("\n1. Environment Variables:")
soapy_path = os.environ.get('SOAPY_SDR_PLUGIN_PATH', 'NOT SET')
print(f"   SOAPY_SDR_PLUGIN_PATH = {soapy_path}")

# Try to import SoapySDR
print("\n2. Importing SoapySDR...")
try:
    import SoapySDR
    print("   [OK] SoapySDR imported successfully")
    print(f"   Module path: {SoapySDR.__file__}")
    print(f"   API version: {SoapySDR.getAPIVersion()}")
    print(f"   ABI version: {SoapySDR.getABIVersion()}")
    print(f"   Lib version: {SoapySDR.getLibVersion()}")
except Exception as e:
    print(f"   [FAIL] Could not import SoapySDR: {e}")
    sys.exit(1)

# Enumerate all devices
print("\n3. Enumerating ALL SoapySDR devices...")
try:
    all_devices = SoapySDR.Device.enumerate()
    print(f"   Found {len(all_devices)} device(s):")
    for i, dev in enumerate(all_devices):
        print(f"   Device {i}: {dev}")
except Exception as e:
    print(f"   [FAIL] Enumeration failed: {e}")
    import traceback
    traceback.print_exc()

# Enumerate HackRF specifically
print("\n4. Enumerating HackRF devices specifically...")
try:
    hackrf_devices = SoapySDR.Device.enumerate("driver=hackrf")
    print(f"   Found {len(hackrf_devices)} HackRF device(s):")
    for i, dev in enumerate(hackrf_devices):
        print(f"   HackRF {i}: {dev}")
except Exception as e:
    print(f"   [FAIL] HackRF enumeration failed: {e}")
    import traceback
    traceback.print_exc()

# Try to open HackRF
print("\n5. Attempting to open HackRF...")
try:
    sdr = SoapySDR.Device(dict(driver="hackrf"))
    print("   [OK] HackRF opened successfully!")
    
    # Get device info
    print(f"   Hardware key: {sdr.getHardwareKey()}")
    print(f"   Driver key: {sdr.getDriverKey()}")
    
    # Close device
    sdr = None
    print("   [OK] Device closed")
except Exception as e:
    print(f"   [FAIL] Could not open HackRF: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Diagnostic complete!")
print("=" * 60)
