# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler
"""Tests for safe publication pipeline behavior.

These tests verify that the publication script logic (used by the OneDev
buildspec) behaves correctly without requiring real remote credentials.
The actual CI jobs use disposable local bare repositories.
"""

import base64
import json
import os
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

GIT_AVAILABLE = shutil.which("git") is not None
OPENSSL_AVAILABLE = shutil.which("openssl") is not None


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in the specified directory."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def create_test_repo(path: Path) -> None:
    """Create a minimal test repository with required files."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch=master"], path)
    run_git(["config", "user.email", "test@example.com"], path)
    run_git(["config", "user.name", "Test User"], path)

    # Create required files
    (path / "hacs.json").write_text('{"name": "Test", "content_in_root": false}')
    (path / "custom_components").mkdir(exist_ok=True)
    cc = path / "custom_components" / "junie_remote"
    cc.mkdir(parents=True, exist_ok=True)
    (cc / "manifest.json").write_text(
        json.dumps({"domain": "junie_remote", "name": "Test", "version": "0.1.0"})
    )
    frontend = cc / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "junie-remote-card.js").write_text("// test bundle")

    run_git(["add", "."], path)
    run_git(["commit", "-m", "Initial commit"], path)


def create_bare_remote(path: Path) -> None:
    """Create a bare git repository to simulate a remote."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--bare"], path)


def create_test_ca(
    directory: Path, name: str, subject_alt_name: str = "IP:127.0.0.1"
) -> tuple[Path, Path, Path]:
    """Create a local CA and a server certificate for the Git HTTPS fixture."""
    directory.mkdir(parents=True, exist_ok=True)
    ca_key = directory / "ca.key"
    ca_certificate = directory / "ca.crt"
    server_key = directory / "server.key"
    server_request = directory / "server.csr"
    server_certificate = directory / "server.crt"
    extensions = directory / "server.ext"
    extensions.write_text(
        f"subjectAltName = {subject_alt_name}\n"
        "extendedKeyUsage = serverAuth\n"
        "keyUsage = digitalSignature,keyEncipherment\n"
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_certificate),
            "-subj",
            f"/CN={name} Test CA",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(server_key),
            "-out",
            str(server_request),
            "-subj",
            "/CN=127.0.0.1",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(server_request),
            "-CA",
            str(ca_certificate),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_certificate),
            "-days",
            "1",
            "-sha256",
            "-extfile",
            str(extensions),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return ca_certificate, server_certificate, server_key


def start_git_https_server(
    project_root: Path,
    certificate: Path,
    private_key: Path,
    redirect_prefix: str | None = None,
    redirect_target_prefix: str | None = None,
    auth_token: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Serve Git smart HTTP over TLS using Git's own http-backend."""

    class GitHTTPHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._run_git_backend()

        def do_POST(self) -> None:
            self._run_git_backend()

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _run_git_backend(self) -> None:
            path, separator, query = self.path.partition("?")
            if redirect_prefix and path.startswith(redirect_prefix):
                location = redirect_target_prefix + path[len(redirect_prefix) :]
                if separator:
                    location += f"?{query}"
                self.send_response(307 if self.command == "POST" else 302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            remote_user = "test-user"
            if auth_token:
                expected_auth = "Basic " + base64.b64encode(
                    f"x-access-token:{auth_token}".encode()
                ).decode()
                if self.headers.get("Authorization") != expected_auth:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="Git"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                remote_user = "x-access-token"
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if self.command == "POST" else b""
            backend_env = os.environ.copy()
            backend_env.update(
                {
                    "GIT_PROJECT_ROOT": str(project_root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "PATH_INFO": path,
                    "QUERY_STRING": query if separator else "",
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(content_length),
                    "REMOTE_USER": remote_user,
                    "REMOTE_ADDR": self.client_address[0],
                    "SERVER_PROTOCOL": self.protocol_version,
                    "SERVER_NAME": "127.0.0.1",
                    "SERVER_PORT": str(self.server.server_port),
                    "HTTP_GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                }
            )
            result = subprocess.run(
                ["git", "http-backend"],
                input=body,
                capture_output=True,
                env=backend_env,
                check=True,
            )
            headers, separator, response_body = result.stdout.partition(b"\r\n\r\n")
            if not separator:
                headers, _separator, response_body = result.stdout.partition(b"\n\n")
            status = 200
            response_headers: list[tuple[str, str]] = []
            for line in headers.splitlines():
                key, delimiter, value = line.partition(b":")
                if not delimiter:
                    continue
                name = key.decode("ascii")
                header_value = value.decode("latin-1").strip()
                if name.lower() == "status":
                    status = int(header_value.split(" ", 1)[0])
                elif name.lower() not in {"content-length", "transfer-encoding"}:
                    response_headers.append((name, header_value))
            self.send_response(status)
            for name, value in response_headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), GitHTTPHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate), str(private_key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"https://127.0.0.1:{server.server_port}/"


def start_connect_proxy(
    git_server: ThreadingHTTPServer,
    certificate: Path,
    private_key: Path,
    target_host: str = "github.com",
) -> tuple[socketserver.ThreadingTCPServer, str]:
    """Route verified HTTPS proxy tunnels for a target host to a local server."""

    class ConnectProxyHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            request = bytearray()
            while not request.endswith(b"\r\n\r\n"):
                chunk = self.request.recv(1)
                if not chunk:
                    return
                request.extend(chunk)
            request_line = request.splitlines()[0].decode("ascii")
            if not request_line.startswith(f"CONNECT {target_host}:443 "):
                self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

            upstream = socket.create_connection(
                ("127.0.0.1", git_server.server_port)
            )
            try:
                self.request.sendall(
                    b"HTTP/1.1 200 Connection Established\r\n\r\n"
                )
                endpoints = (self.request, upstream)
                while True:
                    readable, _writable, _exceptional = select.select(endpoints, [], [])
                    for endpoint in readable:
                        payload = endpoint.recv(65536)
                        if not payload:
                            return
                        destination = upstream if endpoint is self.request else self.request
                        destination.sendall(payload)
            finally:
                upstream.close()

    class TLSThreadingTCPServer(socketserver.ThreadingTCPServer):
        def __init__(self) -> None:
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.load_cert_chain(str(certificate), str(private_key))
            super().__init__(("127.0.0.1", 0), ConnectProxyHandler)

        def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
            request, address = super().get_request()
            return self.context.wrap_socket(request, server_side=True), address

    server = TLSThreadingTCPServer()
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"https://127.0.0.1:{server.server_address[1]}"


def start_github_connect_proxy(
    git_server: ThreadingHTTPServer, certificate: Path, private_key: Path
) -> tuple[socketserver.ThreadingTCPServer, str]:
    """Route verified HTTPS proxy tunnels for github.com to a local server."""
    return start_connect_proxy(git_server, certificate, private_key, "github.com")


def publisher_commands(job_name: str) -> str:
    """Extract a publisher shell script from the OneDev buildspec."""
    buildspec = (Path(__file__).parent.parent / ".onedev-buildspec.yml").read_text()
    job_marker = f"- name: {job_name}\n"
    job_start = buildspec.index(job_marker)
    next_job = buildspec.find("\n- name: ", job_start + len(job_marker))
    job = buildspec[job_start:next_job if next_job >= 0 else None]
    commands_marker = "      commands: |\n"
    commands_start = job.index(commands_marker) + len(commands_marker)
    commands = []
    for line in job[commands_start:].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) < 8:
            break
        commands.append(line[8:] if line.strip() else "")
    return textwrap.dedent("\n".join(commands)).replace("@@", "@")


def prepare_publication_repositories(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    """Prepare a source checkout, its origin and an empty publication remote."""
    source = tmp_path / "source"
    origin = tmp_path / "origin.git"
    published = tmp_path / "published.git"
    create_test_repo(source)

    run_git(["tag", "internal-history"], source)
    (source / "release.txt").write_text("current source tree")
    run_git(["add", "release.txt"], source)
    run_git(["commit", "-m", "Current source"], source)
    run_git(["tag", "v1.0.0"], source)
    source_timestamp = run_git(["log", "-1", "--format=%ct"], source).stdout.strip()

    create_bare_remote(origin)
    run_git(["remote", "add", "origin", str(origin)], source)
    run_git(["push", "--set-upstream", "origin", "master"], source)
    run_git(["push", "origin", "--tags"], source)
    create_bare_remote(published)
    return source, origin, published, source_timestamp


def create_git_transport_stub(tmp_path: Path) -> Path:
    """Stub the HTTPS push target and model loss of OneDev's TLS trust."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(
        """#!/usr/bin/env python3
import os
import pathlib
import subprocess
import sys

args = sys.argv[1:]
marker = pathlib.Path(os.environ["TLS_RESET_MARKER"])
if args and args[0] == "config" and "--unset-all" in args and "http.sslCAInfo" in args:
    marker.touch()
if len(args) > 1 and args[0] == "fetch" and args[1] == "origin" and marker.exists():
    print("fatal: OneDev TLS certificate is no longer trusted", file=sys.stderr)
    raise SystemExit(128)
if "push" in args:
    push_index = args.index("push")
    for index, value in enumerate(args[push_index + 1:], start=push_index + 1):
        if value.startswith("https://"):
            args[index] = os.environ["TEST_PUBLISH_REMOTE"]
            break
result = subprocess.run([os.environ["REAL_GIT"], *args])
raise SystemExit(result.returncode)
"""
    )
    wrapper.chmod(0o755)
    return bin_dir


class TestPublicationSafety:
    """Test cases for issue #41 - safe publication."""

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_orphan_commit_has_no_parent(self, tmp_path: Path) -> None:
        """Verify orphan commits have no parent."""
        source = tmp_path / "source"
        create_test_repo(source)

        # Create orphan commit
        run_git(["checkout", "--orphan", "public-release"], source)
        run_git(["rm", "-rf", "."], source)
        (source / "file.txt").write_text("content")
        run_git(["add", "."], source)
        run_git(["commit", "-m", "Public release"], source)

        # Verify no parent
        result = run_git(["log", "--format=%P", "-1"], source)
        assert result.stdout.strip() == ""

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_orphan_commit_preserves_tracked_files(self, tmp_path: Path) -> None:
        """Verify orphan commit contains all tracked files."""
        source = tmp_path / "source"
        create_test_repo(source)

        # Create orphan commit
        run_git(["checkout", "--orphan", "public-release"], source)
        run_git(["add", "-A"], source)
        run_git(["commit", "-m", "Public release"], source)

        # Verify required files exist
        assert (source / "hacs.json").exists()
        assert (
            source / "custom_components" / "junie_remote" / "manifest.json"
        ).exists()
        assert (
            source
            / "custom_components"
            / "junie_remote"
            / "frontend"
            / "junie-remote-card.js"
        ).exists()

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_tag_only_for_current_commit(self, tmp_path: Path) -> None:
        """Verify only tags pointing at the current commit are published."""
        source = tmp_path / "source"
        create_test_repo(source)

        # Create a tag for the current commit
        current_sha = run_git(["rev-parse", "HEAD"], source).stdout.strip()
        run_git(["tag", "v1.0.0"], source)

        # Create another commit with a different tag
        (source / "other.txt").write_text("other")
        run_git(["add", "."], source)
        run_git(["commit", "-m", "Other commit"], source)
        run_git(["tag", "v2.0.0"], source)

        # Go back to the first commit
        run_git(["checkout", current_sha], source)

        # Only v1.0.0 should point at this commit
        tags = run_git(["tag", "--points-at", "HEAD"], source).stdout.strip().split()
        assert tags == ["v1.0.0"]

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_bare_remote_receives_only_explicit_refs(self, tmp_path: Path) -> None:
        """Verify only explicit refs are pushed to the remote."""
        source = tmp_path / "source"
        remote = tmp_path / "remote.git"
        create_test_repo(source)
        create_bare_remote(remote)

        # Create orphan and tag
        run_git(["checkout", "--orphan", "public-release"], source)
        run_git(["add", "-A"], source)
        run_git(["commit", "-m", "Public release"], source)
        run_git(["tag", "v1.0.0"], source)

        # Push only the branch
        run_git(
            ["push", str(remote), "public-release:master"],
            source,
        )

        # Verify remote has the branch
        clone = tmp_path / "clone"
        run_git(["clone", str(remote), str(clone)], tmp_path)
        branches = run_git(["branch", "-r"], clone).stdout
        assert "origin/master" in branches

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_unrelated_tags_not_exposed(self, tmp_path: Path) -> None:
        """Verify unrelated tags are not published."""
        source = tmp_path / "source"
        create_test_repo(source)

        # Create unrelated tag on a different branch
        run_git(["checkout", "-b", "internal"], source)
        (source / "internal.txt").write_text("secret")
        run_git(["add", "."], source)
        run_git(["commit", "-m", "Internal"], source)
        run_git(["tag", "internal-tag"], source)

        # Go back to master and create public release
        run_git(["checkout", "master"], source)
        run_git(["checkout", "--orphan", "public-release"], source)
        run_git(["add", "-A"], source)
        run_git(["commit", "-m", "Public release"], source)
        run_git(["tag", "v1.0.0"], source)

        # Only v1.0.0 should point at HEAD, not internal-tag
        tags = run_git(["tag", "--points-at", "HEAD"], source).stdout.strip().split()
        assert "v1.0.0" in tags
        assert "internal-tag" not in tags

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_deterministic_commit_timestamp(self, tmp_path: Path) -> None:
        """Verify commits can use deterministic timestamps."""
        source = tmp_path / "source"
        create_test_repo(source)

        timestamp = "1234567890"
        run_git(["checkout", "--orphan", "public-release"], source)
        run_git(["rm", "-rf", "."], source)
        (source / "file.txt").write_text("content")
        run_git(["add", "."], source)
        # Use GIT_COMMITTER_DATE and GIT_AUTHOR_DATE for deterministic timestamps
        env = os.environ.copy()
        env["GIT_COMMITTER_DATE"] = timestamp
        env["GIT_AUTHOR_DATE"] = timestamp
        subprocess.run(
            ["git", "commit", "-m", "Public release"],
            cwd=str(source),
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )

        # Verify the commit date (committer date)
        result = run_git(["log", "-1", "--format=%ct"], source)
        assert result.stdout.strip() == timestamp

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    @pytest.mark.parametrize(
        ("job_name", "target_branch"),
        [
            ("Publish to GitLab", "master"),
            ("Publish to GitHub", "main"),
        ],
    )
    def test_publisher_command_publishes_flattened_snapshot(
        self, tmp_path: Path, job_name: str, target_branch: str
    ) -> None:
        """Run each real publisher script against local bare Git remotes."""
        source, _origin, published, source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        source_tree = run_git(["rev-parse", "HEAD^{tree}"], source).stdout.strip()
        bin_dir = create_git_transport_stub(tmp_path)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["REAL_GIT"] = shutil.which("git") or "git"
        env["TEST_PUBLISH_REMOTE"] = str(published)
        env["TLS_RESET_MARKER"] = str(tmp_path / "tls-reset")
        env["GITLAB_TOKEN"] = "test-token"
        env["GITHUB_TOKEN"] = "test-token"

        result = subprocess.run(
            ["sh", "-eu", "-c", publisher_commands(job_name)],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        published_sha = run_git(
            ["--git-dir", str(published), "rev-parse", f"refs/heads/{target_branch}"],
            tmp_path,
        ).stdout.strip()
        published_tree = run_git(
            ["--git-dir", str(published), "rev-parse", f"{published_sha}^{{tree}}"],
            tmp_path,
        ).stdout.strip()
        assert published_tree == source_tree
        assert run_git(
            ["--git-dir", str(published), "show", "-s", "--format=%P", published_sha],
            tmp_path,
        ).stdout.strip() == ""

        identity = run_git(
            [
                "--git-dir",
                str(published),
                "show",
                "-s",
                "--format=%an|%ae|%cn|%ce|%at|%ct",
                published_sha,
            ],
            tmp_path,
        ).stdout.strip()
        assert identity == (
            f"Publication Bot|bot@onedev.internal|Publication Bot|"
            f"bot@onedev.internal|{source_timestamp}|{source_timestamp}"
        )

        refs = run_git(["--git-dir", str(published), "show-ref"], tmp_path).stdout
        assert f"refs/heads/{target_branch}" in refs
        assert "refs/tags/v1.0.0" in refs
        assert "refs/tags/internal-history" not in refs
        tag_sha = run_git(
            ["--git-dir", str(published), "rev-parse", "refs/tags/v1.0.0"],
            tmp_path,
        ).stdout.strip()
        assert tag_sha == published_sha

    @pytest.mark.skipif(
        not (GIT_AVAILABLE and OPENSSL_AVAILABLE),
        reason="git and openssl are required for HTTPS publication tests",
    )
    def test_github_publisher_uses_public_ca_after_internal_fetch(
        self, tmp_path: Path
    ) -> None:
        """Verify publisher fetch and push use their respective trusted CAs."""
        source, _origin, published, _source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        internal_ca, internal_cert, internal_key = create_test_ca(
            tmp_path / "internal-ca", "Internal"
        )
        public_ca, public_cert, public_key = create_test_ca(
            tmp_path / "public-ca", "Public", "DNS:github.com"
        )

        public_root = tmp_path / "public-http"
        public_repo = (
            public_root
            / "canonical"
            / "OpenTasmania"
            / "junie-remote-lovelace-card.git"
        )
        public_repo.parent.mkdir(parents=True)
        shutil.move(str(published), public_repo)
        run_git(["config", "http.receivepack", "true"], public_repo)

        source_server, source_url = start_git_https_server(
            tmp_path, internal_cert, internal_key
        )
        public_server, _public_url = start_git_https_server(
            public_root,
            public_cert,
            public_key,
            "/OpenTasmania/",
            "/canonical/OpenTasmania/",
            auth_token="test-token",
        )
        proxy_server, proxy_url = start_github_connect_proxy(
            public_server, internal_cert, internal_key
        )
        try:
            run_git(["remote", "set-url", "origin", source_url + "origin.git"], source)
            run_git(["config", "http.sslCAInfo", str(internal_ca)], source)
            run_git(
                [
                    "config",
                    "http.https://github.com.sslCAInfo",
                    str(internal_ca),
                ],
                source,
            )
            run_git(
                [
                    "config",
                    "http.https://github.com/OpenTasmania/junie-remote-lovelace-card.git.sslCAInfo",
                    str(internal_ca),
                ],
                source,
            )

            env = os.environ.copy()
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env.pop(name, None)
            env["HTTPS_PROXY"] = proxy_url
            env["https_proxy"] = proxy_url
            env["NO_PROXY"] = "127.0.0.1,localhost"
            env["no_proxy"] = "127.0.0.1,localhost"
            env["HOME"] = str(tmp_path / "home")
            Path(env["HOME"]).mkdir()
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            env.pop("GIT_SSL_NO_VERIFY", None)
            env.pop("GIT_SSL_CAPATH", None)
            env["GIT_SSL_CAINFO"] = str(internal_ca)
            env["GIT_PROXY_SSL_CAINFO"] = str(internal_ca)
            env["PUBLIC_CA_BUNDLE"] = str(public_ca)
            env["GITHUB_TOKEN"] = "test-token"

            commands = publisher_commands("Publish to GitHub")
            assert "https://x-access-token:${GITHUB_TOKEN}@github.com" not in commands
            result = subprocess.run(
                ["sh", "-eu", "-c", commands],
                cwd=source,
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "test-token" not in result.stdout + result.stderr

            published_sha = run_git(
                ["--git-dir", str(public_repo), "rev-parse", "refs/heads/main"],
                tmp_path,
            ).stdout.strip()
            assert run_git(
                ["--git-dir", str(public_repo), "show", "-s", "--format=%P", published_sha],
                tmp_path,
            ).stdout.strip() == ""
            tag_sha = run_git(
                ["--git-dir", str(public_repo), "rev-parse", "refs/tags/v1.0.0"],
                tmp_path,
            ).stdout.strip()
            assert tag_sha == published_sha
        finally:
            source_server.shutdown()
            source_server.server_close()
            public_server.shutdown()
            public_server.server_close()
            proxy_server.shutdown()
            proxy_server.server_close()

    @pytest.mark.skipif(
        not (GIT_AVAILABLE and OPENSSL_AVAILABLE),
        reason="git and openssl are required for HTTPS publication tests",
    )
    def test_github_publisher_rejects_untrusted_server_even_with_no_verify_env(
        self, tmp_path: Path
    ) -> None:
        """An inherited no-verify flag must not permit an untrusted push."""
        source, _origin, published, _source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        wrong_ca, _wrong_cert, _wrong_key = create_test_ca(
            tmp_path / "wrong-ca", "Wrong"
        )
        proxy_ca, proxy_cert, proxy_key = create_test_ca(
            tmp_path / "proxy-ca", "Proxy"
        )
        _public_ca, public_cert, public_key = create_test_ca(
            tmp_path / "public-ca", "Public", "DNS:github.com"
        )
        public_root = tmp_path / "public-http"
        public_repo = public_root / "OpenTasmania" / "junie-remote-lovelace-card.git"
        public_repo.parent.mkdir(parents=True)
        shutil.move(str(published), public_repo)
        run_git(["config", "http.receivepack", "true"], public_repo)
        public_server, _public_url = start_git_https_server(
            public_root, public_cert, public_key
        )
        proxy_server, proxy_url = start_github_connect_proxy(
            public_server, proxy_cert, proxy_key
        )
        try:
            run_git(
                [
                    "config",
                    "http.https://github.com.sslVerify",
                    "false",
                ],
                source,
            )
            run_git(
                [
                    "config",
                    "http.https://github.com/OpenTasmania/junie-remote-lovelace-card.git.sslVerify",
                    "false",
                ],
                source,
            )
            run_git(
                [
                    "config",
                    "http.https://x-access-token@github.com/OpenTasmania/junie-remote-lovelace-card.git.sslVerify",
                    "false",
                ],
                source,
            )
            env = os.environ.copy()
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env.pop(name, None)
            env["HTTPS_PROXY"] = proxy_url
            env["https_proxy"] = proxy_url
            env["NO_PROXY"] = "127.0.0.1,localhost"
            env["no_proxy"] = "127.0.0.1,localhost"
            env["HOME"] = str(tmp_path / "home")
            Path(env["HOME"]).mkdir()
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            env.pop("GIT_SSL_CAPATH", None)
            env["GIT_PROXY_SSL_CAINFO"] = str(proxy_ca)
            env["PUBLIC_CA_BUNDLE"] = str(wrong_ca)
            env["GIT_SSL_NO_VERIFY"] = "1"
            env["GITHUB_TOKEN"] = "test-token"

            result = subprocess.run(
                ["sh", "-eu", "-c", publisher_commands("Publish to GitHub")],
                cwd=source,
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0
            assert "certificate" in result.stderr.lower()
            refs = subprocess.run(
                ["git", "--git-dir", str(public_repo), "show-ref"],
                capture_output=True,
                text=True,
            )
            assert refs.returncode != 0
        finally:
            public_server.shutdown()
            public_server.server_close()
            proxy_server.shutdown()
            proxy_server.server_close()

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_github_publisher_fails_closed_for_missing_ca_bundle(
        self, tmp_path: Path
    ) -> None:
        """A missing configured public CA bundle must prevent publication."""
        source, _origin, published, _source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        file_root = tmp_path / "github"
        published = (
            file_root / "OpenTasmania" / "junie-remote-lovelace-card.git"
        )
        published.parent.mkdir(parents=True)
        shutil.move(str(tmp_path / "published.git"), published)
        run_git(
            [
                "config",
                f"url.{file_root.as_uri()}/.insteadOf",
                "https://x-access-token:test-token@github.com/",
            ],
            source,
        )
        env = os.environ.copy()
        env["PUBLIC_CA_BUNDLE"] = str(tmp_path / "missing-ca-bundle.crt")
        env["GITHUB_TOKEN"] = "test-token"

        result = subprocess.run(
            ["sh", "-eu", "-c", publisher_commands("Publish to GitHub")],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "CA bundle is missing or unreadable" in result.stdout
        refs = subprocess.run(
            ["git", "--git-dir", str(published), "show-ref"],
            capture_output=True,
            text=True,
        )
        assert refs.returncode != 0

    @pytest.mark.skipif(
        not (GIT_AVAILABLE and OPENSSL_AVAILABLE),
        reason="git and openssl are required for HTTPS publication tests",
    )
    def test_gitlab_publisher_uses_public_ca_after_internal_fetch(
        self, tmp_path: Path
    ) -> None:
        """Verify GitLab publisher fetch and push use their respective trusted CAs."""
        source, _origin, published, _source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        internal_ca, internal_cert, internal_key = create_test_ca(
            tmp_path / "internal-ca", "Internal"
        )
        public_ca, public_cert, public_key = create_test_ca(
            tmp_path / "public-ca", "Public", "DNS:gitlab.com"
        )

        public_root = tmp_path / "public-http"
        public_repo = (
            public_root
            / "opentasmania"
            / "junie-remote-lovelace-card.git"
        )
        public_repo.parent.mkdir(parents=True)
        shutil.move(str(published), public_repo)
        run_git(["config", "http.receivepack", "true"], public_repo)

        source_server, source_url = start_git_https_server(
            tmp_path, internal_cert, internal_key
        )
        public_server, _public_url = start_git_https_server(
            public_root, public_cert, public_key
        )
        proxy_server, proxy_url = start_connect_proxy(
            public_server, internal_cert, internal_key, "gitlab.com"
        )
        try:
            run_git(["remote", "set-url", "origin", source_url + "origin.git"], source)
            run_git(["config", "http.sslCAInfo", str(internal_ca)], source)
            run_git(
                [
                    "config",
                    "http.https://gitlab.com.sslCAInfo",
                    str(internal_ca),
                ],
                source,
            )
            run_git(
                [
                    "config",
                    "http.https://gitlab.com/opentasmania/junie-remote-lovelace-card.git.sslCAInfo",
                    str(internal_ca),
                ],
                source,
            )

            env = os.environ.copy()
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env.pop(name, None)
            env["HTTPS_PROXY"] = proxy_url
            env["https_proxy"] = proxy_url
            env["NO_PROXY"] = "127.0.0.1,localhost"
            env["no_proxy"] = "127.0.0.1,localhost"
            env["HOME"] = str(tmp_path / "home")
            Path(env["HOME"]).mkdir()
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            env.pop("GIT_SSL_NO_VERIFY", None)
            env.pop("GIT_SSL_CAPATH", None)
            env["GIT_SSL_CAINFO"] = str(internal_ca)
            env["GIT_PROXY_SSL_CAINFO"] = str(internal_ca)
            env["PUBLIC_CA_BUNDLE"] = str(public_ca)
            env["GITLAB_TOKEN"] = "test-token"

            commands = publisher_commands("Publish to GitLab")
            result = subprocess.run(
                ["sh", "-eu", "-c", commands],
                cwd=source,
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr

            published_sha = run_git(
                ["--git-dir", str(public_repo), "rev-parse", "refs/heads/master"],
                tmp_path,
            ).stdout.strip()
            assert run_git(
                ["--git-dir", str(public_repo), "show", "-s", "--format=%P", published_sha],
                tmp_path,
            ).stdout.strip() == ""
            tag_sha = run_git(
                ["--git-dir", str(public_repo), "rev-parse", "refs/tags/v1.0.0"],
                tmp_path,
            ).stdout.strip()
            assert tag_sha == published_sha
        finally:
            source_server.shutdown()
            source_server.server_close()
            public_server.shutdown()
            public_server.server_close()
            proxy_server.shutdown()
            proxy_server.server_close()

    @pytest.mark.skipif(
        not (GIT_AVAILABLE and OPENSSL_AVAILABLE),
        reason="git and openssl are required for HTTPS publication tests",
    )
    def test_gitlab_publisher_rejects_untrusted_server_even_with_no_verify_env(
        self, tmp_path: Path
    ) -> None:
        """An inherited no-verify flag must not permit an untrusted GitLab push."""
        source, _origin, published, _source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        wrong_ca, _wrong_cert, _wrong_key = create_test_ca(
            tmp_path / "wrong-ca", "Wrong"
        )
        _public_ca, public_cert, public_key = create_test_ca(
            tmp_path / "public-ca", "Public", "DNS:gitlab.com"
        )
        public_root = tmp_path / "public-http"
        public_repo = public_root / "opentasmania" / "junie-remote-lovelace-card.git"
        public_repo.parent.mkdir(parents=True)
        shutil.move(str(published), public_repo)
        run_git(["config", "http.receivepack", "true"], public_repo)
        public_server, _public_url = start_git_https_server(
            public_root, public_cert, public_key
        )
        try:
            run_git(
                [
                    "config",
                    "http.https://gitlab.com.sslVerify",
                    "false",
                ],
                source,
            )
            run_git(
                [
                    "config",
                    "http.https://gitlab.com/opentasmania/junie-remote-lovelace-card.git.sslVerify",
                    "false",
                ],
                source,
            )
            env = os.environ.copy()
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env.pop(name, None)
            env["HOME"] = str(tmp_path / "home")
            Path(env["HOME"]).mkdir()
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            env.pop("GIT_SSL_CAPATH", None)
            env["PUBLIC_CA_BUNDLE"] = str(wrong_ca)
            env["GIT_SSL_NO_VERIFY"] = "1"
            env["GITLAB_TOKEN"] = "test-token"

            result = subprocess.run(
                ["sh", "-eu", "-c", publisher_commands("Publish to GitLab")],
                cwd=source,
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0
            assert "certificate" in result.stderr.lower()
            refs = subprocess.run(
                ["git", "--git-dir", str(public_repo), "show-ref"],
                capture_output=True,
                text=True,
            )
            assert refs.returncode != 0
        finally:
            public_server.shutdown()
            public_server.server_close()

    @pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
    def test_gitlab_publisher_fails_closed_for_missing_ca_bundle(
        self, tmp_path: Path
    ) -> None:
        """A missing configured public CA bundle must prevent GitLab publication."""
        source, _origin, published, _source_timestamp = (
            prepare_publication_repositories(tmp_path)
        )
        file_root = tmp_path / "gitlab"
        published = (
            file_root / "opentasmania" / "junie-remote-lovelace-card.git"
        )
        published.parent.mkdir(parents=True)
        shutil.move(str(tmp_path / "published.git"), published)
        run_git(
            [
                "config",
                f"url.{file_root.as_uri()}/.insteadOf",
                "https://oauth2:test-token@gitlab.com/",
            ],
            source,
        )
        env = os.environ.copy()
        env["PUBLIC_CA_BUNDLE"] = str(tmp_path / "missing-ca-bundle.crt")
        env["GITLAB_TOKEN"] = "test-token"

        result = subprocess.run(
            ["sh", "-eu", "-c", publisher_commands("Publish to GitLab")],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "CA bundle is missing or unreadable" in result.stdout
        refs = subprocess.run(
            ["git", "--git-dir", str(published), "show-ref"],
            capture_output=True,
            text=True,
        )
        assert refs.returncode != 0


class TestPackageStructure:
    """Test cases for issue #42 - HACS package structure."""

    @staticmethod
    def _project_root() -> Path:
        """Get the project root directory."""
        return Path(__file__).parent.parent

    def test_hacs_json_has_required_fields(self) -> None:
        """Verify hacs.json has all required fields."""
        hacs_path = self._project_root() / "hacs.json"
        data = json.loads(hacs_path.read_text())

        assert "name" in data
        assert data["content_in_root"] is False
        assert "homeassistant" in data

    def test_manifest_has_required_fields(self) -> None:
        """Verify manifest.json has all required HACS fields."""
        manifest_path = (
            self._project_root()
            / "custom_components"
            / "junie_remote"
            / "manifest.json"
        )
        data = json.loads(manifest_path.read_text())

        required = ["domain", "name", "version", "documentation", "issue_tracker", "codeowners"]
        for field in required:
            assert field in data, f"Missing required field: {field}"

    def test_card_bundle_exists(self) -> None:
        """Verify the compiled card bundle is tracked."""
        bundle_path = (
            self._project_root()
            / "custom_components"
            / "junie_remote"
            / "frontend"
            / "junie-remote-card.js"
        )
        assert bundle_path.exists()
        assert bundle_path.stat().st_size > 0

    def test_build_manifest_exists(self) -> None:
        """Verify the build ownership manifest exists."""
        manifest_path = (
            self._project_root()
            / "custom_components"
            / "junie_remote"
            / "frontend"
            / ".junie-build-manifest.json"
        )
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert isinstance(data, dict)
