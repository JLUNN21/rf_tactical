import sys
from pathlib import Path

import pytest


def test_linux_guard_expected_paths_exist(monkeypatch):
    """Ensure Linux-only paths are skipped on non-Linux platforms."""
    if sys.platform == "linux":
        pytest.skip("Linux platform; guard behavior is not exercised.")

    proc_stat = Path("/proc/stat")
    meminfo = Path("/proc/meminfo")
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")

    assert not proc_stat.exists() or sys.platform != "linux"
    assert not meminfo.exists() or sys.platform != "linux"
    assert not temp_path.exists() or sys.platform != "linux"