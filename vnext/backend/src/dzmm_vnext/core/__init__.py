"""Lazy shared domain-core exports.

Keeping this package import-light is required by Android: the embedded host
can load the pure command engine without importing FastAPI, SQLAlchemy or the
desktop-only persistence adapter. Desktop imports the same use cases lazily
through this stable boundary.
"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AIWorldDraftGenerationError": ("..ai_world_drafts", "AIWorldDraftGenerationError"),
    "AIWorldDraftInput": ("..ai_world_drafts", "AIWorldDraftInput"),
    "AIWorldDraftReviewInput": ("..ai_world_drafts", "AIWorldDraftReviewInput"),
    "AIWorldDraftService": ("..ai_world_drafts", "AIWorldDraftService"),
    "validate_world_draft": ("..ai_world_drafts", "validate_world_draft"),
    "ContentNotFoundError": ("..content", "ContentNotFoundError"),
    "ContentService": ("..content", "ContentService"),
    "LorebookPromotionInput": ("..content", "LorebookPromotionInput"),
    "LorebookSelectionInput": ("..content", "LorebookSelectionInput"),
    "SillyTavernImportInput": ("..content", "SillyTavernImportInput"),
    "PurgeConfirmation": ("..lifecycle", "PurgeConfirmation"),
    "PurgeConfirmationError": ("..lifecycle", "PurgeConfirmationError"),
    "WorldLifecycle": ("..lifecycle", "WorldLifecycle"),
    "WorldNotFoundError": ("..lifecycle", "WorldNotFoundError"),
    "WorldVersionConflictError": ("..lifecycle", "WorldVersionConflictError"),
    "WorldVersionInput": ("..lifecycle", "WorldVersionInput"),
    "diagnostic_snapshot": ("..lifecycle", "diagnostic_snapshot"),
    "integrity_scan": ("..lifecycle", "integrity_scan"),
    "ModelProber": ("..model_profiles", "ModelProber"),
    "ModelProfileInput": ("..model_profiles", "ModelProfileInput"),
    "ModelProfileConflictError": ("..model_profiles", "ModelProfileConflictError"),
    "ModelProfileService": ("..model_profiles", "ModelProfileService"),
    "NarrationError": ("..model_profiles", "NarrationError"),
    "PortableBundleError": ("..portable", "PortableBundleError"),
    "PortableImportInput": ("..portable", "PortableImportInput"),
    "PortableRunCloneInput": ("..portable", "PortableRunCloneInput"),
    "PortableService": ("..portable", "PortableService"),
    "ChoiceTurnInput": ("..turns", "ChoiceTurnInput"),
    "RevisionConflictError": ("..turns", "RevisionConflictError"),
    "RunNotFoundError": ("..turns", "RunNotFoundError"),
    "TurnCoordinator": ("..turns", "TurnCoordinator"),
    "TurnIdempotencyConflictError": ("..turns", "TurnIdempotencyConflictError"),
    "TurnInput": ("..turns", "TurnInput"),
    "TurnResult": ("..turns", "TurnResult"),
    "TurnRollbackInput": ("..turns", "TurnRollbackInput"),
    "ComposeWorldInput": ("..worlds", "ComposeWorldInput"),
    "CreateRunInput": ("..worlds", "CreateRunInput"),
    "DomainValidationError": ("..worlds", "DomainValidationError"),
    "IdempotencyConflictError": ("..worlds", "IdempotencyConflictError"),
    "RunModelProfileConflictError": ("..worlds", "RunModelProfileConflictError"),
    "RunModelProfileInput": ("..worlds", "RunModelProfileInput"),
    "WorldComposer": ("..worlds", "WorldComposer"),
}

__all__ = tuple(sorted(_EXPORTS))


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
