"""Model tier definitions and hardware-to-tier policy."""

from tux.provisioning.models import HardwareInfo, Tier, TierDecision

MIN_FULL_VRAM_MB = 8 * 1024
MIN_MID_VRAM_MB = 4 * 1024

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
