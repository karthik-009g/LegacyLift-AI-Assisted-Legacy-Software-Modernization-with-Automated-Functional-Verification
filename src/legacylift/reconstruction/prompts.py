"""Provider-neutral prompt construction for a bounded EER request."""

from __future__ import annotations

import json

from .models import ReconstructionRequest


def build_reconstruction_prompt(request: ReconstructionRequest) -> str:
    payload = json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True)
    return (
        "Propose a FastAPI implementation for only the supplied workflow scope. "
        "Keep observed facts, inferences, and unknowns distinct. Do not claim that "
        "the proposal is verified. Do not execute generated code.\n\n"
        f"Evidence condition: {request.condition}\n"
        f"Bounded evidence payload:\n{payload}\n"
    )
