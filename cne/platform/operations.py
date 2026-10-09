"""Operation-level permission requirements, bounded by the manifest ceiling."""
from cne.platform.manifest import Permission


def intent_permissions(manifest, intent):
    mapping = next(
        (m for m in manifest.schemas.get("intents", []) if m["intent"] == intent), None
    )
    return set(
        Permission(p)
        for p in (mapping or {}).get("required_permissions", manifest.permissions)
    )


def authorize_operation(registry, pack, user_id, intent=None, tools=(), sources=()):
    required = intent_permissions(pack.manifest, intent)
    for tool in pack.manifest.deterministic_tools:
        if tool.tool_id in tools:
            required.update(Permission(p) for p in tool.required_permissions)
    specs = pack.manifest.schemas.get("source_permissions", {})
    for source in sources:
        required.update(Permission(p) for p in specs.get(source, []))
    if not required <= set(pack.manifest.permissions):
        raise PermissionError("NOT_DECLARED: operation permission")
    for permission in required:
        registry.require_permission(pack.id, permission, user_id)
    return required
