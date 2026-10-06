"""OS-enforced offline Linux workers; unsupported hosts fail closed.

Network and host files are not mounted. Resource access must be brokered by the
trusted host before supplying JSON inputs. No Python-only sandbox is claimed.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import re


class SandboxUnavailable(RuntimeError):
    pass


class BubblewrapWorker:
    def __init__(self, timeout_s=10, memory_mb=256, max_output_bytes=1024 * 1024):
        self.timeout_s = timeout_s
        self.memory_mb = memory_mb
        self.max_output_bytes = max_output_bytes

    def run(self, pack_directory, entrypoint, inputs):
        if sys.platform != "linux" or not shutil.which("bwrap"):
            raise SandboxUnavailable(
                "BACKEND_UNAVAILABLE: Linux bubblewrap required; no unsandboxed fallback"
            )
        root = Path(pack_directory).resolve()
        call = ":" in entrypoint
        if call:
            if not re.fullmatch(
                r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint
            ):
                raise ValueError("Invalid tool entrypoint")
            module, function = entrypoint.split(":")
            script = (root / (module.replace(".", "/") + ".py")).resolve()
        else:
            script = (root / entrypoint).resolve()
        if not script.is_relative_to(root) or not script.is_file():
            raise PermissionError("ACCESS_DENIED: worker entrypoint")
        command = [
            "bwrap",
            "--unshare-all",
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
        ]
        for directory in ("/usr", "/lib", "/lib64", "/bin"):
            if Path(directory).exists():
                command += ["--ro-bind", directory, directory]
        command += [
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            str(root),
            "/pack",
            "--chdir",
            "/pack",
            "/usr/bin/python3",
            "-I",
            "-B",
        ]
        if call:
            command += [
                "-c",
                "import sys,json,importlib; sys.path.insert(0,'/pack'); module,fn=sys.argv[1].split(':'); args=json.load(sys.stdin); print(json.dumps(getattr(importlib.import_module(module),fn)(*args)))",
                entrypoint,
            ]
        else:
            command += ["/pack/" + str(script.relative_to(root))]

        def limits():
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (self.memory_mb * 1048576,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (max(1, int(self.timeout_s)),) * 2)
            resource.setrlimit(resource.RLIMIT_FSIZE, (self.max_output_bytes,) * 2)
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
            resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))

        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                preexec_fn=limits,
            )
            try:
                process.communicate(json.dumps(inputs).encode(), timeout=self.timeout_s)
            except BaseException:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
            if process.returncode:
                raise RuntimeError(
                    f"SANDBOX_EXECUTION_FAILED: exit={process.returncode}"
                )
            stdout.seek(0)
            payload = stdout.read(self.max_output_bytes + 1)
            if len(payload) > self.max_output_bytes:
                raise ValueError("Worker output too large")
            return json.loads(payload)


class WSLBubblewrapWorker(BubblewrapWorker):
    """Windows host transport into the same Linux OS-enforced sandbox."""

    def run(self, pack_directory, entrypoint, inputs):
        if sys.platform != "win32" or not shutil.which("wsl"):
            raise SandboxUnavailable("BACKEND_UNAVAILABLE: WSL required")
        request = {
            "pack_directory": str(Path(pack_directory).resolve()),
            "entrypoint": entrypoint,
            "inputs": inputs,
            "timeout_s": self.timeout_s,
            "memory_mb": self.memory_mb,
            "max_output_bytes": self.max_output_bytes,
        }
        root = Path(__file__).resolve().parents[2]
        # No user-authored code is executed until the Linux sandbox is established.
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--exec", "python3", "-m", "cne.platform.sandbox"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=self.timeout_s + 30,
            cwd=root,
        )
        if result.returncode:
            raise SandboxUnavailable(
                "SANDBOX_EXECUTION_FAILED: WSL worker rejected request"
            )
        if len(result.stdout) > self.max_output_bytes:
            raise ValueError("Worker output too large")
        return json.loads(result.stdout)


if __name__ == "__main__":
    request = json.load(sys.stdin)
    path = request["pack_directory"]
    if re.match(r"^[A-Za-z]:", path):
        path = subprocess.check_output(["wslpath", "-a", "-u", path], text=True).strip()
    worker = BubblewrapWorker(
        request["timeout_s"], request["memory_mb"], request["max_output_bytes"]
    )
    print(json.dumps(worker.run(path, request["entrypoint"], request["inputs"])))
