"""Verified immutable package extraction with an atomic durable registry pointer."""
from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile
from cne.platform.manifest import CapabilityManifest


class CapabilityPackageInstaller:
    def __init__(self, registry, root, max_bytes=256 * 1024 * 1024):
        self.registry = registry
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    def install(self, archive, auto_enable=True):
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            names = [i.filename for i in infos]
            if (
                len(names) != len(set(names))
                or sum(i.file_size for i in infos) > self.max_bytes
            ):
                raise ValueError("Invalid package size or duplicate entries")
            for info in infos:
                path = PurePosixPath(info.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in info.filename
                    or ":" in info.filename
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Unsafe archive path or symlink")
            manifest = CapabilityManifest(**json.loads(zf.read("manifest.json")))
            declared = (
                set(manifest.asset_hashes)
                | set(manifest.model_asset_hashes)
                | {"manifest.json"}
            )
            if {i.filename for i in infos if not i.is_dir()} != declared:
                raise ValueError("Every package asset must have a declared hash")
            # TemporaryDirectory removes only its own verified child directory.
            with tempfile.TemporaryDirectory(
                dir=self.root, prefix=".staging-"
            ) as temporary:
                stage = Path(temporary)
                for info in infos:
                    target = (stage / info.filename).resolve()
                    if not target.is_relative_to(stage):
                        raise ValueError("Archive escape")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("wb") as out:
                        out.write(zf.read(info))
                        out.flush()
                        os.fsync(out.fileno())
                digest = self.registry.package_verifier.verify(manifest, str(stage))
                if auto_enable:
                    self.registry._validate_dependencies(manifest)
                destination = self.root / manifest.id / digest
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    self.registry.package_verifier.verify(manifest, str(destination))
                else:
                    # Leave the temporary directory itself in place for its owner.
                    payload = Path(tempfile.mkdtemp(dir=stage, prefix=".payload-"))
                    for child in list(stage.iterdir()):
                        if child != payload:
                            child.rename(payload / child.name)
                    payload.rename(destination)
                return self.registry.register_pack(
                    manifest, str(destination), auto_enable
                )
