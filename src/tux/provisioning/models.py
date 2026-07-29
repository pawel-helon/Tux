"""Provisioning data models and injectable callable types."""

from collections.abc import Callable
from dataclasses import dataclass

@dataclass(frozen=True)
class HardwareInfo:
    """A snapshot of the signals the tier decision is allowed to use.

    ``gpu_vendor`` is ``None`` when no GPU was detected, in which case
    ``vram_mb`` is ``0``.
    """

    cpu_count: int
    ram_mb: int
    gpu_vendor: str | None
    vram_mb: int

@dataclass(frozen=True)
class Tier:
    """A capability tier: the variant package and the Ollama model it runs."""

    name: str
    variant: str
    model: str
    download_size: str
    capability: str

@dataclass(frozen=True)
class TierDecision:
    """The chosen tier plus the human-readable signals that drove the pick."""

    tier: Tier
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class ProvisionResult:
    """The outcome of a provisioning run, for the caller to report.

    ``tier`` and ``decision`` are ``None`` on a bypassed run (the user pointed
    tux at their own endpoint, so no decision was made) *or* when the Ollama
    runtime itself is missing and installing it was declined or deferred — the
    tier and model depend on a working runtime, so neither is decided until the
    runtime is in place. ``ollama_ready`` distinguishes that second case from an
    ordinary deferred model pull: it is ``True`` whenever the runtime was
    already installed or was freshly installed this run, and ``False`` when it
    is still missing at the end of the run.
    ``endpoint_reachable`` is ``None`` when reachability was not checked — a
    deferred pull or a bypass leaves it unknown.
    """

    tier: Tier | None
    decision: TierDecision | None
    ollama_installed: bool
    ollama_ready: bool
    model_pulled: bool
    model_deferred: bool
    bypassed: bool
    endpoint_reachable: bool | None
    endpoint: str
    model: str
    variant: str
    system: str
    ollama_server_started: bool

Probe = Callable[[], HardwareInfo]
SystemProbe = Callable[[], str]
Confirm = Callable[[str], bool]
ConfigWriter = Callable[[str, str], None]
VariantInstaller = Callable[[str], None]
Reachable = Callable[[str], bool]
