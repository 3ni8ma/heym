import unittest
from pathlib import Path


class OpenCodeImageWiringTests(unittest.TestCase):
    """Compose and the single GHCR image must both ship the OpenCode CLI + wrapper."""

    _REPO_ROOT = Path(__file__).resolve().parents[2]

    @classmethod
    def setUpClass(cls) -> None:
        cls._backend_dockerfile = (cls._REPO_ROOT / "backend" / "Dockerfile").read_text()
        cls._release_dockerfile = (cls._REPO_ROOT / "docker" / "release.Dockerfile").read_text()
        cls._compose = (cls._REPO_ROOT / "docker-compose.yml").read_text()

    def test_backend_image_installs_opencode_from_github_releases(self) -> None:
        self.assertIn("github.com/anomalyco/opencode/releases", self._backend_dockerfile)
        self.assertNotIn("opencode.ai/install", self._backend_dockerfile)
        self.assertIn("ARG HEYM_OPENCODE_CLI_VERSION=latest", self._backend_dockerfile)
        self.assertIn("/usr/local/bin/opencode", self._backend_dockerfile)
        self.assertIn(
            "COPY docker/heym-opencode-docker /usr/local/bin/heym-opencode-docker",
            self._backend_dockerfile,
        )

    def test_compose_points_deploy_sh_at_the_opencode_wrapper(self) -> None:
        self.assertIn(
            "HEYM_OPENCODE_CLI_COMMAND: ${HEYM_OPENCODE_CLI_COMMAND:-/usr/local/bin/heym-opencode-docker}",
            self._compose,
        )
        self.assertIn("heym-opencode-workspaces", self._compose)

    def test_release_image_wires_opencode_like_codex(self) -> None:
        self.assertIn("github.com/anomalyco/opencode/releases", self._release_dockerfile)
        self.assertNotIn("opencode.ai/install", self._release_dockerfile)
        self.assertIn(
            "COPY docker/heym-opencode-docker /usr/local/bin/heym-opencode-docker",
            self._release_dockerfile,
        )
        self.assertIn(
            "HEYM_OPENCODE_CLI_COMMAND=/usr/local/bin/heym-opencode-docker",
            self._release_dockerfile,
        )
        self.assertIn(
            "HEYM_OPENCODE_DOCKER_IMAGE=${HEYM_RELEASE_IMAGE}",
            self._release_dockerfile,
        )
        self.assertIn(
            "HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME=heym-opencode-workspaces",
            self._release_dockerfile,
        )
