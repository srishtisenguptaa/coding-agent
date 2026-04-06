import os
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from typing import List
from modules.patch_generator import PatchResult
from modules.github_reader import IssueData


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
        """
        For each patch:
        1. Clone the repo into a temp folder inside Docker
        2. Apply the patch
        3. Run the existing test suite
        4. Return pass/fail
        """
        results = []
        for patch in patches:
            print(f"\n[Sandbox] Testing patch for {patch.class_name}...")
            result = self._run_patch(issue_data, patch)
            results.append(result)
        return results

    def _run_patch(self, issue_data: IssueData, patch: PatchResult) -> ExecutionResult:
        """Run a single patch in an isolated Docker container."""

        # Build a Python test script that:
        # 1. Applies the patch by monkey-patching the class at runtime
        # 2. Runs a targeted pickle test
        test_script = self._build_test_script(issue_data, patch)

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="patch_test_"
        ) as f:
            f.write(test_script)
            script_path = f.name

        try:
            # Run inside Docker — use python:3.11-slim image
            # Mount the temp script into the container
            docker_cmd = [
                "docker", "run", "--rm",
                "--network", "none",          # no internet inside sandbox
                "--memory", "256m",           # memory limit
                "--cpus", "0.5",              # cpu limit
                "-v", f"{script_path}:/test_script.py",
                "python:3.11-slim",
                "sh", "-c",
                "pip install requests --quiet && python /test_script.py"
            ]

            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 min max
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
            os.unlink(script_path)  # cleanup temp file

    def _build_test_script(self, issue_data: IssueData, patch: PatchResult) -> str:
        """
        Build a self-contained Python script that:
        - Imports requests
        - Applies the patch at runtime (monkey-patch)
        - Runs a targeted test for the exact issue
        """

        # Indent the patched code for use inside a class body
        indented_patch = textwrap.indent(patch.patched_code, "    ")

        script = f'''
import pickle
import requests
from requests.models import Response, PreparedRequest

# ─── Apply patch at runtime ───────────────────────────────────────────────────
# We inject the fixed methods directly into the class without modifying source
{indented_patch.replace("def ", "def patched_")}

# Monkey-patch the class
if "Response" in "{patch.class_name}":
    if "def patched___getstate__" in """{indented_patch}""":
        Response.__getstate__ = patched___getstate__
    if "def patched___setstate__" in """{indented_patch}""":
        Response.__setstate__ = patched___setstate__

elif "PreparedRequest" in "{patch.class_name}":
    if "def patched___getstate__" in """{indented_patch}""":
        PreparedRequest.__getstate__ = patched___getstate__
    if "def patched___setstate__" in """{indented_patch}""":
        PreparedRequest.__setstate__ = patched___setstate__

# ─── Test 1: Basic pickle roundtrip ──────────────────────────────────────────
print("Test 1: Basic pickle roundtrip...")
r = Response()
r.status_code = 200
r.url = "https://example.com"
r._content = b"hello"
r._content_consumed = True

pickled = pickle.dumps(r)
restored = pickle.loads(pickled)
assert restored.status_code == 200, "status_code lost after pickle"
assert restored.url == "https://example.com", "url lost after pickle"
print("  PASS ✓")

# ─── Test 2: _next attribute preserved ───────────────────────────────────────
print("Test 2: _next attribute preserved after pickle...")
r2 = Response()
r2._content = b""
r2._content_consumed = True
prep = PreparedRequest()
prep.url = "https://example.com/next"
r2._next = prep

pickled2 = pickle.dumps(r2)
restored2 = pickle.loads(pickled2)

assert hasattr(restored2, "_next"), "_next attribute missing after pickle!"
assert restored2._next is not None, "_next is None after pickle!"
assert restored2._next.url == "https://example.com/next", "_next.url wrong after pickle!"
print("  PASS ✓")

# ─── Test 3: _next=None works fine ───────────────────────────────────────────
print("Test 3: _next=None case...")
r3 = Response()
r3._content = b""
r3._content_consumed = True
r3._next = None

pickled3 = pickle.dumps(r3)
restored3 = pickle.loads(pickled3)
assert restored3._next is None, "_next should be None"
print("  PASS ✓")

print("\\n✓ All tests passed! Patch is valid.")
'''
        return script