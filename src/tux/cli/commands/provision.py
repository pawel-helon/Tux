"""Implementation of the ``tux provision`` command."""

import argparse
import subprocess
import sys
from collections.abc import Callable

from tux.config import ConfigError
from tux.provisioning.main import ProvisionResult, provision

InteractiveProbe = Callable[[], bool]

def run_provision(
    args: argparse.Namespace, *, interactive: InteractiveProbe
) -> int:
    """Run the guided, re-runnable provisioning and report what it did.

    Consent is interactive only when tux is attached to a terminal; a piped or
    redirected (unattended) run never prompts — it defers the model pull to first
    run unless ``--yes`` preseeds consent — so the install never hangs.

    Returns:
        ``0`` on success; ``1`` if a provisioning step (install, pull, or config
        write) fails.
    """
    try:
        result = provision(
            interactive=interactive(), assume_yes=args.yes, pin=args.variant
        )
    except (OSError, subprocess.CalledProcessError, ConfigError) as exc:
        print(f"tux: provisioning failed: {exc}", file=sys.stderr)
        return 1
    _print_provision_result(result)
    return 0

def _print_provision_result(result: ProvisionResult) -> None:
    """Print a human summary of a provisioning run."""
    if result.bypassed:
        print(
            "tux is already pointed at a configured endpoint "
            f"({result.endpoint}); skipping provisioning."
        )
        return
    if not result.ollama_ready:
        print(
            "The Ollama runtime is not installed, so provisioning stopped there "
            "(no model tier was chosen and nothing was downloaded). Run 'tux "
            "provision' again to be asked, or 'tux provision --yes' to install "
            "it and continue."
        )
        return
    if result.decision is not None:
        print(f"Selected the {result.tier.capability} tier ({result.variant}):")
        for reason in result.decision.reasons:
            print(f"  - {reason}")
    print(f"Detected system: {result.system}.")
    if result.ollama_installed:
        print("Installed the Ollama runtime.")
    if result.ollama_server_started:
        print("Started the Ollama server for this provisioning run.")
    if result.model_pulled:
        print(f"Pulled model {result.model}.")
    elif result.model_deferred:
        print(
            f"Deferred the download of {result.model} to first run "
            "(no consent given yet)."
        )
    else:
        print(f"Model {result.model} already present.")
    if result.endpoint_reachable is False:
        print(f"warning: endpoint {result.endpoint} is not reachable yet.")
    print(
        f"Config now points at {result.endpoint} "
        f"(model {result.model}, system {result.system})."
    )

