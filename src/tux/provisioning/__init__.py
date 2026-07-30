"""Provisioning API for selecting and preparing a local Tux runtime."""

from .hardware import probe_hardware
from .models import (
    ConfigWriter,
    Confirm,
    HardwareInfo,
    Probe,
    ProvisionResult,
    Reachable,
    SystemProbe,
    Tier,
    TierDecision,
    VariantInstaller,
)
from .network import endpoint_reachable
from .ollama import OLLAMA_INSTALL_URL, OllamaRuntime
from .prompts import confirm_pull
from .service import OLLAMA_ENDPOINT, managed_local_runtime, pin_variant, provision
from .tiers import (
    FULL_TIER,
    LOOKUP_TIER,
    MID_TIER,
    MIN_FULL_VRAM_MB,
    MIN_MID_VRAM_MB,
    TIERS,
    decide_tier,
)

__all__ = [
    "ConfigWriter",
    "Confirm",
    "FULL_TIER",
    "HardwareInfo",
    "LOOKUP_TIER",
    "MID_TIER",
    "MIN_FULL_VRAM_MB",
    "MIN_MID_VRAM_MB",
    "OLLAMA_ENDPOINT",
    "OLLAMA_INSTALL_URL",
    "OllamaRuntime",
    "Probe",
    "ProvisionResult",
    "Reachable",
    "SystemProbe",
    "TIERS",
    "Tier",
    "TierDecision",
    "VariantInstaller",
    "confirm_pull",
    "decide_tier",
    "endpoint_reachable",
    "managed_local_runtime",
    "pin_variant",
    "probe_hardware",
    "provision",
]
