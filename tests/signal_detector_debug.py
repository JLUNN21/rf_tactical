"""Debug script to understand signal detection issue."""

import numpy as np

# Simulate what's happening in signal_detector.py

# Example IQ samples (simulating a signal at -50 dBm)
# Real signal would have amplitude around 0.003 for -50 dBm
signal_amplitude = 0.003
iq_samples = signal_amplitude * np.exp(1j * 2 * np.pi * 0.1 * np.arange(1000))

# Add some noise
noise = 0.0001 * (np.random.randn(1000) + 1j * np.random.randn(1000))
iq_samples = iq_samples + noise

print("=== Signal Detector Debug ===\n")

# Step 1: Calculate power (LINEAR)
power = np.abs(iq_samples) ** 2
print(f"1. Linear power calculation:")
print(f"   power = np.abs(iq_samples) ** 2")
print(f"   Min power: {np.min(power):.2e}")
print(f"   Max power: {np.max(power):.2e}")
print(f"   Mean power: {np.mean(power):.2e}")
print()

# Step 2: Convert to dB
power_db = 10 * np.log10(power + 1e-10)
print(f"2. Convert to dB:")
print(f"   power_db = 10 * np.log10(power + 1e-10)")
print(f"   Min power_db: {np.min(power_db):.1f} dB")
print(f"   Max power_db: {np.max(power_db):.1f} dB")
print(f"   Mean power_db: {np.mean(power_db):.1f} dB")
print()

# Step 3: Estimate noise floor
sorted_power = np.sort(power_db)
median_noise = np.median(sorted_power[:len(sorted_power)//2])
print(f"3. Noise floor estimation:")
print(f"   median_noise = {median_noise:.1f} dB")
print()

# Step 4: Set threshold
threshold_db = 10.0
absolute_threshold = median_noise + threshold_db
print(f"4. Threshold calculation:")
print(f"   threshold_db = {threshold_db:.1f} dB (relative)")
print(f"   absolute_threshold = {absolute_threshold:.1f} dB")
print()

# Step 5: Detect signals
above_threshold = power_db > absolute_threshold
num_above = np.sum(above_threshold)
print(f"5. Signal detection:")
print(f"   above_threshold = power_db > absolute_threshold")
print(f"   Samples above threshold: {num_above} / {len(power_db)}")
print()

print("=== ISSUE IDENTIFIED ===")
print("The power_db values are in dB relative to 1 (dB scale), NOT dBm!")
print("Waterfall shows dBm values (referenced to 1 milliwatt)")
print("Signal detector uses dB values (referenced to 1 watt)")
print()
print("Example:")
print(f"  - Waterfall might show: -50 dBm (actual RF power)")
print(f"  - Signal detector sees: {np.max(power_db):.1f} dB (arbitrary reference)")
print()
print("These are DIFFERENT scales and cannot be directly compared!")
