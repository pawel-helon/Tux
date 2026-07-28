"""Hardware-aware provisioning brain for a fresh tux install.

Provisioning probes the host's hardware, maps it to one of **three model
tiers** — a small lookup-only model for CPU/low-RAM hosts (lite), a middle model
for a modest GPU (mid), and a larger full-capability model for a capable GPU
(full) — ensures the **Ollama** runtime is installed, pulls the tier's model
(after surfacing its download size and getting consent, never silently), checks
the local endpoint is reachable, and records the endpoint / model / variant in
tux's config so a fresh ``tux ask`` works with no further setup.

Capability is a **config value** the probe writes (``variant``), not a package
boundary: there is one ``tux`` package, and the tier is a value in the config
file rather than a pinned variant package. Re-running is idempotent — an
already-installed runtime and an already-pulled model are left untouched and the
config converges to the same values.

Every external effect — the hardware probe, the Ollama runtime, the consent
prompt, the endpoint-reachability check, the config writer, and the
variant-install seam — is an injectable seam, so the whole flow runs under the
test suite offline with no real install, download, or GPU.
"""

import os
import shutil
import subprocess
import time
import signal
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tux.config import ConfigError, load_config, set_value
from tux.state import ollama_pid_path
from tux.system import LINUX, TERMUX, detect_system

#: OpenAI-compatible base URL Ollama serves locally. tux's model client appends
#: ``/v1/chat/completions`` to the stored endpoint, which matches Ollama's
#: OpenAI-compatible route, so the base (no ``/v1``) is what gets recorded.
OLLAMA_ENDPOINT = "http://localhost:11434"

#: Official one-line Ollama installer. Used only by the default runtime's
#: :meth:`OllamaRuntime.install`, which is mocked out in the test suite.
OLLAMA_INSTALL_URL = "https://ollama.com/install.sh"

#: A GPU clears the bar for the full tier only with at least this much VRAM (MB).
#: Kept deliberately simple and transparent; the chosen tier records the VRAM it
#: saw so the user can see and override the decision.
MIN_FULL_VRAM_MB = 8 * 1024

#: A GPU clears the bar for the mid tier with at least this much VRAM (MB); below
#: it (or with no GPU at all) the host falls to the lite tier. This is the lower
#: of the two VRAM bars — a middle GPU band lands on mid, a capable GPU on full.
MIN_MID_VRAM_MB = 4 * 1024


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


# All tiers temporarily use the same phone-tested Qwen coder model.
# They are **provisional**: the hypervisor A/B test (see docs/eval/hypervisor-ab.md)
# pins the final per-tier models once its scoring matrix is filled in. Model names
# stay here as config values written to the config file — they are never hardcoded
# into the client/request path.

#: Lookup-only tier for CPU-only / low-RAM hosts: a small instruction-tuned model
#: sized so common command lookups stay correct with bearable latency. Provisional
#: Temporary default: ``qwen2.5-coder:3b`` for cross-tier evaluation.
LOOKUP_TIER = Tier(
    name="lookup",
    variant="lite",
    model="qwen2.5-coder:3b",
    download_size="1.9 GB",
    capability="lookup-only",
)

#: Middle tier for hosts with a modest GPU: a mid-sized model between the lite and
#: Temporary default: ``qwen2.5-coder:3b`` for cross-tier evaluation.
MID_TIER = Tier(
    name="mid",
    variant="mid",
    model="qwen2.5-coder:3b",
    download_size="1.9 GB",
    capability="mid-capability",
)

#: Full-capability tier for hosts with a capable GPU: a larger model that backs
#: the richer stepwise and conversational surfaces. Provisional default:
#: ``qwen2.5-coder:3b`` during the phone evaluation.
FULL_TIER = Tier(
    name="full",
    variant="full",
    model="qwen2.5-coder:3b",
    download_size="1.9 GB",
    capability="full-capability",
)

#: Variant name → tier, for a run that forces a tier regardless of what the
#: hardware probe would otherwise pick. The ``--variant`` override / ``pin``
#: resolves through this map, so a human can force any of the three tiers against
#: the hardware and have it written to config.
TIERS = {
    LOOKUP_TIER.variant: LOOKUP_TIER,
    MID_TIER.variant: MID_TIER,
    FULL_TIER.variant: FULL_TIER,
}


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


#: A probe returns the host's hardware snapshot.
Probe = Callable[[], HardwareInfo]
SystemProbe = Callable[[], str]

#: A confirm callable shows the consent prompt and returns the user's yes/no.
Confirm = Callable[[str], bool]

#: A config writer persists one ``key = value`` pair (mirrors ``config.set_value``).
ConfigWriter = Callable[[str, str], None]

#: A variant installer installs the chosen variant package. The default is a
#: no-op seam — the concrete ``tux-lite`` / ``tux-full`` packages are a separate
#: item; 8a only records the decision and marks where the install would happen.
VariantInstaller = Callable[[str], None]

#: A reachability check returns whether the endpoint base URL answers.
Reachable = Callable[[str], bool]


class OllamaRuntime:
    """Manage the Ollama CLI and a server process owned by the current tux run."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._system = LINUX
        self._started = False

    def is_installed(self) -> bool:
        return shutil.which("ollama") is not None

    def install(self, system: str) -> None:
        if system == TERMUX:
            subprocess.run(["pkg", "install", "-y", "ollama"], check=True)
            return
        subprocess.run(
            f"curl -fsSL {OLLAMA_INSTALL_URL} | sh",
            shell=True,
            check=True,
        )

    def is_ready(self) -> bool:
        try:
            subprocess.run(
                ["ollama", "list"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        return True

    def start_server(self, system: str) -> bool:
        """Start Ollama if needed and remember ownership for cleanup."""
        self._system = system
        if self.is_ready():
            return False
        self._process = subprocess.Popen(
            ["ollama", "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._started = True
        if system == LINUX:
            path = ollama_pid_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(self._process.pid), encoding="utf-8")
        self.wait_until_ready()
        return True

    def wait_until_ready(self) -> None:
        for _ in range(30):
            if self.is_ready():
                return
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError("Ollama server exited before becoming ready")
            time.sleep(1)
        raise RuntimeError("Ollama did not become ready")

    def stop_server(self) -> None:
        """Stop only an Ollama server started by this runtime instance."""
        if not self._started:
            return
        process = self._process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        if self._system == LINUX:
            ollama_pid_path().unlink(missing_ok=True)
        self._started = False
        self._process = None

    def has_model(self, model: str) -> bool:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
        names = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.split()]
        return model in names

    def pull(self, model: str) -> None:
        subprocess.run(["ollama", "pull", model], check=True)


def decide_tier(hardware: HardwareInfo) -> TierDecision:
    """Map probed hardware to one of three model tiers, recording the signals.

    A capable GPU (a detected vendor with at least :data:`MIN_FULL_VRAM_MB` of
    VRAM) selects the full tier; a middle GPU band (a detected vendor at or above
    :data:`MIN_MID_VRAM_MB` but below the full bar) selects the mid tier;
    everything else — no GPU, or a GPU below the mid bar — selects the
    lookup-only lite tier. The returned reasons make the pick transparent so the
    user can see why and override it.
    """
    if hardware.gpu_vendor and hardware.vram_mb >= MIN_FULL_VRAM_MB:
        reason = (
            f"{hardware.gpu_vendor} GPU with {hardware.vram_mb} MB VRAM "
            f"(≥ {MIN_FULL_VRAM_MB} MB)"
        )
        return TierDecision(FULL_TIER, (reason,))
    if hardware.gpu_vendor and hardware.vram_mb >= MIN_MID_VRAM_MB:
        reason = (
            f"{hardware.gpu_vendor} GPU with {hardware.vram_mb} MB VRAM "
            f"(≥ {MIN_MID_VRAM_MB} MB, < {MIN_FULL_VRAM_MB} MB)"
        )
        return TierDecision(MID_TIER, (reason,))
    if not hardware.gpu_vendor:
        gpu_reason = "no GPU detected"
    else:
        gpu_reason = (
            f"{hardware.gpu_vendor} GPU with {hardware.vram_mb} MB VRAM "
            f"(< {MIN_MID_VRAM_MB} MB)"
        )
    host_reason = f"{hardware.ram_mb} MB system RAM, {hardware.cpu_count} CPU(s)"
    return TierDecision(LOOKUP_TIER, (gpu_reason, host_reason))


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


def _consent_prompt(tier: Tier) -> str:
    """Return the one-line consent prompt naming the model and its download size."""
    return (
        f"tux will download the {tier.capability} model '{tier.model}' "
        f"(~{tier.download_size}) via Ollama. Proceed? [y/N] "
    )


def _ollama_consent_prompt(system: str) -> str:
    """Return the one-line consent prompt for installing the Ollama runtime.

    Asked before :func:`_consent_prompt`, and separately from it: this is
    consent to fetch and run Ollama's own install script, not to download a
    model. A host that already has Ollama installed never sees this prompt.
    """
    if system == TERMUX:
        return "tux will install Ollama with pkg install ollama. Proceed? [y/N] "
    return (
        "tux will install the Ollama runtime via its official install script "
        f"({OLLAMA_INSTALL_URL}). Proceed? [y/N] "
    )


def confirm_pull(prompt: str) -> bool:
    """Read a yes/no answer for the model-pull consent prompt from stdin.

    Anything other than ``y``/``yes`` (including end-of-input) is treated as no,
    so a stray keystroke never triggers a multi-GB download.
    """
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        print()
        return False
    return answer in {"y", "yes"}


def endpoint_reachable(endpoint: str) -> bool:
    """Return whether the endpoint base URL answers an HTTP request.

    A network failure (``urllib.error.URLError`` / ``TimeoutError``, both
    ``OSError`` subclasses) means not reachable rather than an error, since this
    is only a post-pull readiness check.
    """
    try:
        with urllib.request.urlopen(f"{endpoint}/", timeout=5.0):
            return True
    except urllib.error.HTTPError:
        # An HTTP error response still proves the endpoint is answering.
        return True
    except OSError:
        return False


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
    system = existing.get("system", system_probe())
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


from contextlib import contextmanager
from collections.abc import Iterator


@contextmanager
def managed_local_runtime(
    *, runtime: OllamaRuntime | None = None
) -> Iterator[bool]:
    """Ensure a configured local Ollama server is up for one tux invocation.

    Yields whether this invocation started the server and stops it on exit. Remote
    endpoints and missing Ollama installations are left untouched.
    """
    config = load_config()
    system = config.get("system", detect_system())
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
