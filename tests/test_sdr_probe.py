import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import radio.sdr_manager as sdr_manager


def test_probe_device_false_when_soapy_missing(monkeypatch):
    monkeypatch.setattr(sdr_manager, "SDR_AVAILABLE", False)
    manager = sdr_manager.SDRManager()
    assert manager._probe_device() is False


def test_probe_device_detects_hackrf(monkeypatch):
    monkeypatch.setattr(sdr_manager, "SDR_AVAILABLE", True)

    class DummyDevice:
        @staticmethod
        def enumerate():
            return ["driver=hackrf"]

    class DummySoapy:
        Device = DummyDevice

    monkeypatch.setattr(sdr_manager, "SoapySDR", DummySoapy)
    manager = sdr_manager.SDRManager()
    assert manager._probe_device() is True


def test_probe_device_no_hackrf(monkeypatch):
    monkeypatch.setattr(sdr_manager, "SDR_AVAILABLE", True)

    class DummyDevice:
        @staticmethod
        def enumerate():
            return ["driver=rtlsdr"]

    class DummySoapy:
        Device = DummyDevice

    monkeypatch.setattr(sdr_manager, "SoapySDR", DummySoapy)
    manager = sdr_manager.SDRManager()
    assert manager._probe_device() is False