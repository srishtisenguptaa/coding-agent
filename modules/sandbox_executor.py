import os
import re
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from typing import List
from unittest.mock import patch
from modules.patch_generator import PatchResult
from modules.github_reader import IssueData
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ExecutionResult:
    """Result of running the patch in Docker."""
    success: bool
    test_output: str
    error_output: str
    patch: PatchResult


class SandboxExecutor:
    def __init__(self):
        self._check_docker()

    def _check_docker(self):
        """Make sure Docker is running."""
        try:
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=True
            )
            print("[Sandbox] Docker is running ✓")
        except subprocess.CalledProcessError:
            raise RuntimeError("Docker is not running. Please start Docker Desktop.")
        except FileNotFoundError:
            raise RuntimeError("Docker not found. Please install Docker.")

    def run(self, issue_data: IssueData, patches: List[PatchResult]) -> List[ExecutionResult]:
        """For each patch, apply it and run tests inside Docker."""
        results = []
        for patch in patches:
            print(f"\n[Sandbox] Testing patch for {patch.class_name}...")
            result = self._run_patch(issue_data, patch)
            results.append(result)
        return results

    def _run_patch(self, issue_data: IssueData, patch: PatchResult) -> ExecutionResult:
        """Run a single patch in an isolated Docker container."""
        test_script = self._build_test_script(issue_data, patch)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="patch_test_",
            encoding="utf-8"
        ) as f:
            f.write(test_script)
            script_path = f.name

        try:
            docker_cmd = [
                "docker", "run", "--rm",
                "--memory", "256m",
                "--cpus", "0.5",
                "-v", f"{script_path}:/test_script.py",
                "python:3.11-slim",
                "sh", "-c",
                "pip install requests --quiet && python /test_script.py"
            ]

            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            success = proc.returncode == 0
            print(f"[Sandbox] {'✓ PASSED' if success else '✗ FAILED'}")

            if not success:
                print(f"[Sandbox] Error:\n{proc.stderr[-500:]}")

            return ExecutionResult(
                success=success,
                test_output=proc.stdout,
                error_output=proc.stderr,
                patch=patch
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                test_output="",
                error_output="Timeout: test took longer than 2 minutes",
                patch=patch
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                test_output="",
                error_output=str(e),
                patch=patch
            )
        finally:
            os.unlink(script_path)

def _build_test_script(self, issue_data: IssueData, patch: PatchResult) -> str:
    """Build a test script matched to the actual issue type."""

    clean_patch = textwrap.dedent(patch.patched_code).strip()
    renamed_patch = re.sub(
        r"^def (\w+)",
        r"def patched_\1",
        clean_patch,
        flags=re.MULTILINE
    )

    # Detect what kind of issue this is from keywords
    keywords = " ".join(issue_data.issue_body[:500].lower().split())
    is_pickle_issue = any(w in keywords for w in ["pickle", "pickling", "unpickle"])
    is_encoding_issue = any(w in keywords for w in ["encoding", "charset", "unicode", "utf"])
    is_session_issue = "session" in patch.class_name.lower()

    # Build the monkey-patch block
    patch_block = f'''
# Monkey-patch into the class
try:
    Response.__getstate__ = patched___getstate__
except NameError:
    pass
try:
    Response.__setstate__ = patched___setstate__
except NameError:
    pass
try:
    Session.request = patched_request
except NameError:
    pass
try:
    Session.prepare_request = patched_prepare_request
except NameError:
    pass
try:
    PreparedRequest.__getstate__ = patched___getstate__
except NameError:
    pass
try:
    PreparedRequest.__setstate__ = patched___setstate__
except NameError:
    pass
try:
    SessionRedirectMixin.resolve_redirects = patched_resolve_redirects
except NameError:
    pass
try:
    SessionRedirectMixin.rebuild_auth = patched_rebuild_auth
except NameError:
    pass
'''.strip()

    # Build appropriate tests based on issue type
    if is_pickle_issue:
        test_block = '''
print("Test 1: Basic pickle roundtrip...")
r = Response()
r.status_code = 200
r.url = "https://example.com"
r._content = b"hello"
r._content_consumed = True
restored = pickle.loads(pickle.dumps(r))
assert restored.status_code == 200
print("  PASS")

print("Test 2: _next preserved after pickle...")
r2 = Response()
r2._content = b""
r2._content_consumed = True
prep = PreparedRequest()
prep.url = "https://example.com/next"
r2._next = prep
restored2 = pickle.loads(pickle.dumps(r2))
assert hasattr(restored2, "_next"), "_next missing after pickle!"
assert restored2._next is not None
print("  PASS")

print("Test 3: _next=None case...")
r3 = Response()
r3._content = b""
r3._content_consumed = True
r3._next = None
restored3 = pickle.loads(pickle.dumps(r3))
assert restored3._next is None
print("  PASS")
'''.strip()

    elif is_encoding_issue or is_session_issue:
        test_block = '''
print("Test 1: Session can be created...")
s = Session()
assert s is not None
print("  PASS")

print("Test 2: Session prepare_request works with standard request...")
from requests import Request
req = Request("GET", "https://httpbin.org/get")
s2 = Session()
prepared = s2.prepare_request(req)
assert prepared.url is not None
assert prepared.method == "GET"
print("  PASS")

print("Test 3: Session handles headers correctly...")
s3 = Session()
s3.headers.update({"X-Test": "value"})
req2 = Request("GET", "https://httpbin.org/get")
prepared2 = s3.prepare_request(req2)
assert "X-Test" in prepared2.headers
print("  PASS")
'''.strip()

    else:
        # Generic test — just verify the patch doesn't crash on import
        test_block = '''
print("Test 1: Import and basic instantiation...")
r = Response()
assert r is not None
print("  PASS")

print("Test 2: Session instantiation...")
s = Session()
assert s is not None
print("  PASS")
'''.strip()

    lines = [
        "import pickle",
        "import requests",
        "from requests.models import Response, PreparedRequest",
        "from requests.sessions import Session",
        "",
        "# Apply patch",
        renamed_patch,
        "",
        "# Monkey-patch into the class",
        patch_block,
        "",
        "# Run tests",
        test_block,
        "",
        'print("\\nAll tests passed! Patch is valid.")',
    ]

    return "\n".join(lines) + "\n"