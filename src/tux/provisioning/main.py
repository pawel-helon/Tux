"""Backward-compatible facade for :mod:`tux.provisioning`."""
from tux.provisioning.hardware import *
from tux.provisioning.hardware import _nvidia_vram_mb, _probe_cpu_count, _probe_gpu_vendor, _probe_ram_mb, _probe_vram_mb
from tux.provisioning.models import *
from tux.provisioning.network import *
from tux.provisioning.ollama import *
from tux.provisioning.prompts import *
from tux.provisioning.prompts import _consent_prompt, _ollama_consent_prompt
from tux.provisioning.service import *
from tux.provisioning.service import _record_variant_only
from tux.provisioning.tiers import *
