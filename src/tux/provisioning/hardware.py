"""Transparent host hardware probes used by provisioning."""

import os
import subprocess
from pathlib import Path

from tux.provisioning.models import HardwareInfo

def probe_hardware() -> HardwareInfo:
    """Return the host's hardware snapshot from simple, transparent sources."""
    return HardwareInfo(
        cpu_count=_probe_cpu_count(),
        ram_mb=_probe_ram_mb(),
        gpu_vendor=_probe_gpu_vendor(),
        vram_mb=_probe_vram_mb(),
    )

def _probe_cpu_count() -> int:
    """Return the usable CPU count, falling back to ``1`` when unknown."""
    return os.cpu_count() or 1

def _probe_ram_mb() -> int:
    """Return total system RAM in MB from ``/proc/meminfo`` (``0`` if unreadable).

    A missing or unparsable ``/proc/meminfo`` means the RAM signal is unknown,
    which the tier decision treats as low — the safe (lookup-only) direction.
    """
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return 0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) // 1024  # MemTotal is reported in kB
    return 0

def _nvidia_vram_mb() -> int | None:
    """Return NVIDIA VRAM in MB via ``nvidia-smi``, or ``None`` when absent.

    A missing ``nvidia-smi`` (``FileNotFoundError``) or a non-zero exit means no
    usable NVIDIA GPU, which is reported as ``None`` rather than an error.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    first = result.stdout.strip().splitlines()
    if first and first[0].strip().isdigit():
        return int(first[0].strip())
    return None

def _probe_gpu_vendor() -> str | None:
    """Return the GPU vendor string, or ``None`` when no GPU is detected."""
    if _nvidia_vram_mb() is not None:
        return "NVIDIA"
    return None

def _probe_vram_mb() -> int:
    """Return detected VRAM in MB, or ``0`` when no GPU is detected."""
    return _nvidia_vram_mb() or 0
