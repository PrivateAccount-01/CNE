"""Typed platform failures; expected controller declines are not exceptions."""


class PlatformError(ValueError):
    category = "EXECUTION_ERROR"


class SlotValidationError(PlatformError):
    category = "SLOT_ERROR"


class SemanticPlanError(PlatformError):
    category = "SEMANTIC_PLAN_ERROR"


class ModelOutputError(PlatformError):
    category = "MODEL_INFERENCE_ERROR"


class PackageVersionError(PlatformError):
    category = "VERSION_ERROR"


class ToolArgumentError(PlatformError):
    category = "TOOL_ARGUMENT_ERROR"


class CompositionError(PlatformError):
    category = "COMPOSITION_ERROR"


class FreshnessError(PlatformError):
    category = "FRESHNESS_ERROR"


class ModelIntegrityError(PlatformError):
    category = "VERSION_ERROR"


class ModelAssetMissingError(FileNotFoundError):
    category = "VERSION_ERROR"


class BackendUnavailableError(PlatformError):
    category = "BACKEND_ERROR"


class GrammarValidationError(PlatformError):
    category = "SEMANTIC_PLAN_ERROR"


def classify_exception(exc):
    if isinstance(exc, PlatformError):
        return exc.category
    if getattr(exc, "category", None):
        return exc.category
    if isinstance(exc, PermissionError):
        return "PERMISSION_ERROR"
    if isinstance(exc, (MemoryError, TimeoutError)):
        return "RESOURCE_ERROR"
    if isinstance(exc, OSError):
        return "BACKEND_ERROR"
    return "EXECUTION_ERROR"
