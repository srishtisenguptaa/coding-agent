import os
import re
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from typing import List
from modules.patch_generator import PatchResult
from modules.github_reader import IssueData
from dotenv import load_dotenv

load_dotenv()

# Maps class names to their import source
CLASS_IMPORT_MAP = {
    "Response":             "from requests.models import Response",
    "PreparedRequest":      "from requests.models import PreparedRequest",
    "Request":              "from requests.models import Request",
    "Session":              "from requests.sessions import Session",
    "SessionRedirectMixin": "from requests.sessions import SessionRedirectMixin",
}

# Maps (class_name, method_name) → how to monkey-patch it
PATCH_TARGET_MAP = {
    ("Response",             "__getstate__"):       "Response.__getstate__",
    ("Response",             "__setstate__"):       "Response.__setstate__",
    ("Response",             "__reduce__"):         "Response.__reduce__",
    ("PreparedRequest",      "__getstate__"):       "PreparedRequest.__getstate__",
    ("PreparedRequest",      "__setstate__"):       "PreparedRequest.__setstate__",
    ("PreparedRequest",      "__reduce__"):         "PreparedRequest.__reduce__",
    ("Session",              "request"):            "Session.request",
    ("Session",              "prepare_request"):    "Session.prepare_request",
    ("SessionRedirectMixin", "resolve_redirects"):  "SessionRedirectMixin.resolve_redirects",
    ("SessionRedirectMixin", "rebuild_auth"):       "SessionRedirectMixin.rebuild_auth",
}


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
        try:
            subprocess.run(["docker", "info"], capture_output=True, check=True)
            print("[Sandbox] Docker is running ✓")
        except subprocess.CalledProcessError:
            raise RuntimeError("Docker is not running. Please start Docker Desktop.")
        except FileNotFoundError:
            raise RuntimeError("Docker not found. Please install Docker.")

    def run(self, issue_data: IssueData, patches: List[PatchResult]) -> List[ExecutionResult]:
        results = []
        for patch in patches:
            print(f"\n[Sandbox] Testing patch for {patch.class_name}...")
            result = self._run_patch(issue_data, patch)
            results.append(result)
        return results

    def _run_patch(self, issue_data: IssueData, patch: PatchResult) -> ExecutionResult:
        test_script = self._build_test_script(issue_data, patch)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False,
            prefix="patch_test_", encoding="utf-8"
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
            proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=120)
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
            return ExecutionResult(success=False, test_output="", error_output="Timeout", patch=patch)
        except Exception as e:
            return ExecutionResult(success=False, test_output="", error_output=str(e), patch=patch)
        finally:
            os.unlink(script_path)

    def _extract_method_names(self, code: str) -> List[str]:
        """Extract all top-level def names from a patch code block."""
        return re.findall(r"^def (\w+)", code, flags=re.MULTILINE)

    def _build_patch_block(self, patch: PatchResult, method_names: List[str]) -> str:
        """
        Build monkey-patch assignments ONLY for the class being patched.
        Each patched_<method> is wired only to patch.class_name.<method>.
        """
        lines = []
        class_name = patch.class_name
        for method in method_names:
            target = PATCH_TARGET_MAP.get((class_name, method))
            if target:
                lines.append(f"{target} = patched_{method}")
            else:
                # Generic fallback: only apply to the correct class
                lines.append(f"setattr({class_name}, '{method}', patched_{method})")
        return "\n".join(lines)

    def _build_imports(self, patch: PatchResult) -> List[str]:
        """Only import classes actually needed for this patch's test."""
        imports = [
            "import pickle",
            "import requests",
        ]
        # Always import the class being patched
        class_name = patch.class_name
        if class_name in CLASS_IMPORT_MAP:
            imports.append(CLASS_IMPORT_MAP[class_name])

        # For pickle tests on Response, we also need PreparedRequest for _next
        keywords_text = patch.class_name.lower()
        if class_name == "Response":
            imports.append("from requests.models import PreparedRequest")
        if class_name in ("Session", "SessionRedirectMixin"):
            imports.append("from requests.sessions import Session, SessionRedirectMixin")

        return imports

    def _build_test_script(self, issue_data: IssueData, patch: PatchResult) -> str:
        """Build a test script scoped exactly to the class being patched."""

        # 1. Clean and rename all defs in the patch to patched_<name>
        clean_patch = textwrap.dedent(patch.patched_code).strip()
        renamed_patch = re.sub(
            r"^def (\w+)",
            r"def patched_\1",
            clean_patch,
            flags=re.MULTILINE
        )

        # 2. Find what methods the patch defines
        original_method_names = self._extract_method_names(clean_patch)

        # 3. Build monkey-patch block scoped to THIS class only
        patch_block = self._build_patch_block(patch, original_method_names)

        # 4. Detect issue type
        keywords = " ".join(issue_data.issue_body[:500].lower().split())
        is_pickle_issue = any(w in keywords for w in ["pickle", "pickling", "unpickle"])
        is_encoding_issue = any(w in keywords for w in ["encoding", "charset", "unicode", "utf"])
        is_session_issue = "session" in patch.class_name.lower()

        # 5. Build imports scoped to what this test actually needs
        imports = self._build_imports(patch)

        # 6. Choose test block based on class + issue type
        class_name = patch.class_name
        test_block = self._select_test_block(class_name, is_pickle_issue, is_encoding_issue, is_session_issue)

        lines = [
            *imports,
            "",
            "# Patched method(s)",
            renamed_patch,
            "",
            "# Apply patch to correct class only",
            patch_block,
            "",
            "# Run tests",
            test_block,
            "",
            'print("\\nAll tests passed! Patch is valid.")',
        ]

        return "\n".join(lines) + "\n"

    def _select_test_block(
        self,
        class_name: str,
        is_pickle_issue: bool,
        is_encoding_issue: bool,
        is_session_issue: bool
    ) -> str:
        """Return the right test block for the class + issue combination."""

        if class_name == "Response" and is_pickle_issue:
            return textwrap.dedent("""
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
            """).strip()

        elif class_name == "PreparedRequest" and is_pickle_issue:
            return textwrap.dedent("""
                print("Test 1: PreparedRequest basic pickle roundtrip...")
                prep = PreparedRequest()
                prep.method = "GET"
                prep.url = "https://example.com"
                prep.headers = {}
                prep.body = None
                restored = pickle.loads(pickle.dumps(prep))
                assert restored.method == "GET"
                assert restored.url == "https://example.com"
                print("  PASS")

                print("Test 2: PreparedRequest preserves all fields...")
                prep2 = PreparedRequest()
                prep2.method = "POST"
                prep2.url = "https://example.com/post"
                prep2.body = b"data"
                restored2 = pickle.loads(pickle.dumps(prep2))
                assert restored2.body == b"data"
                print("  PASS")
            """).strip()

        elif is_session_issue or is_encoding_issue:
            return textwrap.dedent("""
                print("Test 1: Session can be created...")
                s = Session()
                assert s is not None
                print("  PASS")

                print("Test 2: prepare_request works...")
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
            """).strip()

        else:
            return textwrap.dedent(f"""
                print("Test 1: Basic instantiation of {class_name}...")
                from requests.models import Response, PreparedRequest
                from requests.sessions import Session
                r = Response()
                assert r is not None
                print("  PASS")
            """).strip()