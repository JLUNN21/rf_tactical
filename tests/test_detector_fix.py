"""Test the fixed signal detector."""

import numpy as np

# Simulate what's happening with the fix

# Create a signal: 900 samples of noise + 100 samples of strong signal
noise_samples = 900
signal_samples = 100
total_samples = noise_samples + signal_samples

# Noise: very low amplitude
noise_amplitude = 0.0001
noise = noise_amplitude * (np.random.randn(noise_samples) + 1j * np.random.randn(noise_samples))

# Signal: much stronger amplitude (simulating -50 dBm vs -99 dBm noise)
signal_amplitude = 0.003  # About 30 dB stronger than noise
signal = signal_amplitude * np.exp(1j * 2 * np.pi * 0.1 * np.arange(signal_samples))

# Combine: mostly noise with a burst of signal
iq_samples = np.concatenate([noise, signal])

print("=== Testing Fixed Signal Detector ===\n")
print(f"Simulated data: {noise_samples} noise samples + {signal_samples} signal samples")
print()

# Calculate power
power = np.abs(iq_samples) ** 2
power_db = 10 * np.log10(power + 1e-10)

print(f"Power statistics:")
print(f"  Min: {np.min(power_db):.1f} dB")
print(f"  Max: {np.max(power_db):.1f} dB")
print(f"  Mean: {np.mean(power_db):.1f} dB")
print()

# OLD METHOD: Median of lower 50%
sorted_power = np.sort(power_db)
median_noise_old = np.median(sorted_power[:len(sorted_power)//2])
print(f"OLD noise floor (median of lower 50%): {median_noise_old:.1f} dB")

# NEW METHOD: 10th percentile
noise_estimate_new = np.percentile(sorted_power, 10)
print(f"NEW noise floor (10th percentile): {noise_estimate_new:.1f} dB")
print()

# Test detection with both methods
threshold_db = 10.0

print(f"Detection threshold: +{threshold_db:.1f} dB above noise floor")
print()

# OLD method
absolute_threshold_old = median_noise_old + threshold_db
above_threshold_old = power_db > absolute_threshold_old
detected_old = np.sum(above_threshold_old)
print(f"OLD METHOD:")
print(f"  Absolute threshold: {absolute_threshold_old:.1f} dB")
print(f"  Samples detected: {detected_old} / {total_samples}")
print()

# NEW method
absolute_threshold_new = noise_estimate_new + threshold_db
above_threshold_new = power_db > absolute_threshold_new
detected_new = np.sum(above_threshold_new)
print(f"NEW METHOD:")
print(f"  Absolute threshold: {absolute_threshold_new:.1f} dB")
print(f"  Samples detected: {detected_new} / {total_samples}")
print()

if detected_new > 0:
    print("✅ SUCCESS! Signal detection is now working!")
    print(f"   Expected ~{signal_samples} detections, got {detected_new}")
else:
    print("[X] STILL NOT WORKING - Need further investigation")
