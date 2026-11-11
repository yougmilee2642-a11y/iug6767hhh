"""Fail closed for cloud evaluation; not dynamic model discovery.
Verified: Groq API reference, Structured Outputs and Local Tool Calling docs.
"""
from providers.errors import KNOWN_MODELS, ProviderError


def validate_models(models, include_simulator=False):
    roles=['agent','generator','judge']+(['simulator'] if include_simulator else [])
    for role in roles:
        if models[role] not in KNOWN_MODELS:
            raise ProviderError(models[role], 'capability_check', 'model_unsupported')
    return {role:{'model':models[role],'tool_use':role=='agent','strict_json_schema':role!='agent'} for role in roles}
