"""Run custom Playwright scripts in an isolated, throwaway sibling container.

Custom ``playwrightCode`` is untrusted Python. Running it in the backend process is
equivalent to backend RCE (GHSA-mp23-7m6r-jfw4): even with a scrubbed environment the
code shares the backend's uid, ``/proc``, filesystem and the mounted Docker socket, so it
can recover secrets and escape to the host. This module runs that code inside a
hardened, single-use container instead.

Modes are selected by ``HEYM_PLAYWRIGHT_SANDBOX``:

* ``docker`` / ``auto`` (default) - run the script inside a throwaway sibling container
  of the backend image: no Docker socket, no backend bind mounts, no backend secrets in
  the environment, ``no-new-privileges``, dropped capabilities, and strict CPU / memory /
  PID limits. Network is left enabled (``bridge``) because browser automation needs it;
  tighten egress at the network layer if required. If Docker is unavailable the call
  **fails closed** (raises) rather than silently running untrusted code in-process.
* ``subprocess`` - run the script in the backend process (the legacy path). This is NOT a
  security boundary and must be selected explicitly, for trusted single-user or local dev
  only.

The script is streamed to ``python`` over stdin, never bind-mounted, so it works under
Docker-in-Docker where the backend's temp paths do not exist on the host daemon.

The bundled Chromium in the backend image is installed under root's home, so the sandbox
runs as root **inside the isolated container** by default. That is safe here: the
container has no socket, no mounts and no secrets, so "root" only owns a throwaway
sandbox. Chromium refuses to run as root without ``--no-sandbox``; custom code that drives
Chromium should launch it with ``args=["--no-sandbox"]`` (documented on the node page), or
the operator can point ``HEYM_PLAYWRIGHT_SANDBOX_USER`` at a non-root uid on a suitably
built image.
"""

import logging
import os
import socket
import subprocess
import uuid

logger = logging.getLogger(__name__)

_docker_available_cache: bool | None = None


class PlaywrightSandboxUnavailableError(RuntimeError):
    """Raised when the Docker sandbox is required but cannot be used (fail closed)."""


def sandbox_mode() -> str:
    raw = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX", "auto").strip().lower()
    if raw not in ("auto", "docker", "subprocess"):
        logger.warning("Unknown HEYM_PLAYWRIGHT_SANDBOX=%r; defaulting to 'auto'", raw)
        return "auto"
    return raw


def _docker_available() -> bool:
    """Return True when a working Docker daemon is reachable (cached)."""
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _docker_available_cache = result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        _docker_available_cache = False
    return _docker_available_cache


def _resolve_image() -> str | None:
    """Resolve the image to run scripts in: explicit override, else this container's image."""
    override = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_IMAGE", "").strip()
    if override:
        return override
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", socket.gethostname()],
            capture_output=True,
            text=True,
            timeout=5,
        )
        image = result.stdout.strip()
        if result.returncode == 0 and image:
            return image
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
    return None


def _force_remove_container(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass


def build_docker_command(image: str, name: str) -> list[str]:
    """Build a hardened, throwaway ``docker run`` invocation that reads the script on stdin.

    Deliberately omits ``-v`` mounts and the Docker socket so the sandbox cannot touch the
    host, backend volumes or the daemon. Network stays on (browser automation needs it).
    """
    memory = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_MEMORY", "1g")
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_NETWORK", "bridge"),
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_PIDS", "512"),
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--cpus",
        os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_CPUS", "2"),
        # Chromium needs a larger /dev/shm than Docker's 64m default.
        "--shm-size",
        os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_SHM_SIZE", "1g"),
        # Writable scratch without touching the host.
        "--tmpfs",
        "/tmp:rw,nosuid,size=256m",
    ]
    user = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_USER", "").strip()
    if user:
        cmd += ["--user", user]
    cmd += [
        # entrypoint.sh starts uvicorn and ignores args, so override it to run python
        # reading the streamed script from stdin. Use the backend image's uv venv
        # interpreter (bare `python` lacks playwright and the app dependencies).
        "--entrypoint",
        os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_PYTHON", "/app/.venv/bin/python"),
        "--env",
        "PYTHONIOENCODING=utf-8",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        image,
        "-",
    ]
    return cmd


def require_image() -> str:
    """Resolve the sandbox image, failing closed if Docker or the image is unavailable."""
    if not _docker_available():
        raise PlaywrightSandboxUnavailableError(
            "Custom Playwright code requires a Docker sandbox but no working Docker daemon "
            "is reachable. Run with Docker available, or set HEYM_PLAYWRIGHT_SANDBOX="
            "subprocess to explicitly allow the insecure in-process fallback "
            "(trusted / local dev only)."
        )
    image = _resolve_image()
    if not image:
        raise PlaywrightSandboxUnavailableError(
            "Custom Playwright code Docker sandbox is enabled but the runner image could "
            "not be resolved. Set HEYM_PLAYWRIGHT_SANDBOX_IMAGE to the backend image."
        )
    return image


def run_script(
    script_content: str,
    timeout_seconds: float,
    image: str | None = None,
) -> tuple[int, str, str]:
    """Run ``script_content`` in a hardened throwaway container.

    Returns ``(returncode, stdout, stderr)``. Raises :class:`TimeoutError` if the script
    exceeds ``timeout_seconds`` and :class:`PlaywrightSandboxUnavailableError` if the sandbox
    cannot be established.
    """
    image = image or require_image()
    name = f"heym-pw-{uuid.uuid4().hex}"
    cmd = build_docker_command(image, name)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(input=script_content, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        _force_remove_container(name)
        raise TimeoutError(f"Playwright script timed out after {timeout_seconds:.1f} seconds")
    return proc.returncode, stdout or "", stderr or ""
