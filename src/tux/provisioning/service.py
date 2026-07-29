"""Provisioning orchestration with all external effects injected."""

from collections.abc import Iterator
from contextlib import contextmanager

from tux.config import ConfigError, load_config, set_value
from tux.provisioning.hardware import probe_hardware
from tux.provisioning.models import (ConfigWriter, Confirm, Probe, ProvisionResult, Reachable, SystemProbe, TierDecision, VariantInstaller)
from tux.provisioning.network import endpoint_reachable
from tux.provisioning.ollama import OllamaRuntime
from tux.provisioning.prompts import _consent_prompt, _ollama_consent_prompt, confirm_pull
from tux.provisioning.tiers import TIERS, decide_tier
from tux.system import detect_system

OLLAMA_ENDPOINT = "http://localhost:11434"

def _record_variant_only(variant: str) -> None:
    """No-op variant-install seam: record the decision without installing.

    8a only records the chosen variant; the generic (unpinned) provisioning path
    keeps this no-op so the escape hatch and existing behavior are untouched. A
    pinned, packaged install fills the seam with :func:`pin_variant` instead.
    """

def pin_variant(variant: str) -> None:
    """Pin the resolved variant into config: the concrete variant-package seam.

    Where :func:`_record_variant_only` is 8a's no-op placeholder, a real variant
    package pins its variant so a later hardware probe can never upgrade, say, a
    tux-lite install to full. It is idempotent — it re-asserts the same variant
    provisioning already records — so re-running converges on the pinned value.
    """
    set_value("variant", variant)

def provision(
    *,
    probe: Probe = probe_hardware,
    system_probe: SystemProbe = detect_system,
    runtime: OllamaRuntime | None = None,
    confirm: Confirm = confirm_pull,
    writer: ConfigWriter = set_value,
    install_variant: VariantInstaller | None = None,
    reachable: Reachable = endpoint_reachable,
    interactive: bool = True,
    assume_yes: bool = False,
    pin: str | None = None,
) -> ProvisionResult:
    """Provision a local Ollama model and record endpoint, model, variant, and system.

    The configured system value wins over detection. Termux installs Ollama through
    ``pkg``; conventional Linux uses Ollama's installer. If this run starts an Ollama
    server, it is stopped before provisioning exits.
    """
    manager = runtime if runtime is not None else OllamaRuntime()
    existing = load_config()
    system = existing["system"] if "system" in existing else system_probe()
    if install_variant is None:
        install_variant = pin_variant if pin is not None else _record_variant_only

    if "endpoint" in existing and "variant" not in existing:
        return ProvisionResult(
            tier=None, decision=None, ollama_installed=False, ollama_ready=False,
            model_pulled=False, model_deferred=False, bypassed=True,
            endpoint_reachable=None, endpoint=existing.get("endpoint", ""),
            model=existing.get("model", ""), variant=existing.get("variant", ""),
            system=existing.get("system", system), ollama_server_started=False,
        )

    installed_now = False
    installed = manager.is_installed()
    if not installed:
        if assume_yes:
            manager.install(system)
            installed = True
            installed_now = True
        elif interactive and confirm(_ollama_consent_prompt(system)):
            manager.install(system)
            installed = True
            installed_now = True

    if not installed:
        return ProvisionResult(
            tier=None, decision=None, ollama_installed=False, ollama_ready=False,
            model_pulled=False, model_deferred=True, bypassed=False,
            endpoint_reachable=None, endpoint=existing.get("endpoint", ""),
            model=existing.get("model", ""), variant=existing.get("variant", ""),
            system=system, ollama_server_started=False,
        )

    started = manager.start_server(system)
    try:
        if pin is not None:
            if pin not in TIERS:
                allowed = ", ".join(sorted(TIERS))
                raise ConfigError(
                    f"unknown variant {pin!r}; allowed variants are: {allowed}"
                )
            tier = TIERS[pin]
            decision = TierDecision(
                tier, (f"variant pinned to {pin!r}, forced against the hardware probe",)
            )
        else:
            decision = decide_tier(probe())
            tier = decision.tier

        model_pulled = False
        model_deferred = False
        if manager.has_model(tier.model):
            pass
        elif assume_yes:
            manager.pull(tier.model)
            model_pulled = True
        elif interactive and confirm(_consent_prompt(tier)):
            manager.pull(tier.model)
            model_pulled = True
        else:
            model_deferred = True

        install_variant(tier.variant)
        writer("endpoint", OLLAMA_ENDPOINT)
        writer("model", tier.model)
        writer("variant", tier.variant)
        writer("system", system)
        reachable_now = None if model_deferred else reachable(OLLAMA_ENDPOINT)

        return ProvisionResult(
            tier=tier, decision=decision, ollama_installed=installed_now,
            ollama_ready=True, model_pulled=model_pulled,
            model_deferred=model_deferred, bypassed=False,
            endpoint_reachable=reachable_now, endpoint=OLLAMA_ENDPOINT,
            model=tier.model, variant=tier.variant, system=system,
            ollama_server_started=started,
        )
    finally:
        manager.stop_server()

@contextmanager
def managed_local_runtime(
    *, runtime: OllamaRuntime | None = None
) -> Iterator[bool]:
    """Ensure a configured local Ollama server is up for one tux invocation.

    Yields whether this invocation started the server and stops it on exit. Remote
    endpoints and missing Ollama installations are left untouched.
    """
    config = load_config()
    system = config["system"] if "system" in config else detect_system()
    endpoint = config.get("endpoint", OLLAMA_ENDPOINT).rstrip("/")
    local = endpoint in {
        OLLAMA_ENDPOINT.rstrip("/"),
        "http://127.0.0.1:11434",
        "http://localhost:11434",
    }
    manager = runtime if runtime is not None else OllamaRuntime()
    started = False
    try:
        if local and manager.is_installed():
            started = manager.start_server(system)
        yield started
    finally:
        manager.stop_server()
