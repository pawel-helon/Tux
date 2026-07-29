"""Provisioning consent prompts."""

from tux.provisioning.models import Tier
from tux.provisioning.ollama import OLLAMA_INSTALL_URL
from tux.system import TERMUX

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
