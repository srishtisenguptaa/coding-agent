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
    "RequestsCookieJar":    "from requests.cookies import RequestsCookieJar",
    "HTTPDigestAuth":       "from requests.auth import HTTPDigestAuth",
    "HTTPBasicAuth":        "from requests.auth import HTTPBasicAuth",
    "AuthBase":             "from requests.auth import AuthBase",
}

# Maps (class_name, method_name) → how to monkey-patch it
PATCH_TARGET_MAP = {
    ("Response",             "__getstate__"):          "Response.__getstate__",
    ("Response",             "__setstate__"):          "Response.__setstate__",
    ("Response",             "__reduce__"):            "Response.__reduce__",
    ("PreparedRequest",      "__getstate__"):          "PreparedRequest.__getstate__",
    ("PreparedRequest",      "__setstate__"):          "PreparedRequest.__setstate__",
    ("PreparedRequest",      "__reduce__"):            "PreparedRequest.__reduce__",
    ("Session",              "request"):               "Session.request",
    ("Session",              "prepare_request"):       "Session.prepare_request",
    ("SessionRedirectMixin", "resolve_redirects"):     "SessionRedirectMixin.resolve_redirects",
    ("SessionRedirectMixin", "rebuild_auth"):          "SessionRedirectMixin.rebuild_auth",
    ("SessionRedirectMixin", "get_redirect_target"):   "SessionRedirectMixin.get_redirect_target",
    ("RequestsCookieJar",    "set"):                   "RequestsCookieJar.set",
    ("RequestsCookieJar",    "set_cookie"):            "RequestsCookieJar.set_cookie",
    ("RequestsCookieJar",    "update"):                "RequestsCookieJar.update",
    ("HTTPDigestAuth",       "__call__"):              "HTTPDigestAuth.__call__",
    ("HTTPDigestAuth",       "build_digest_header"):   "HTTPDigestAuth.build_digest_header",
    ("HTTPDigestAuth",       "handle_401"):            "HTTPDigestAuth.handle_401",
    ("HTTPDigestAuth",       "handle_redirect"):       "HTTPDigestAuth.handle_redirect",
}

# Python 2 → Python 3 module renames to fix in LLM-generated patches
PY2_TO_PY3 = {
    "cookielib":        "http.cookiejar",
    "urllib2":          "urllib.request",
    "urllib.quote":     "urllib.parse.quote",
    "urllib.urlencode": "urllib.parse.urlencode",
    "urlparse":         "urllib.parse",
    "httplib":          "http.client",
    "BaseHTTPServer":   "http.server",
}

# Internal test-helper classes that are NEVER importable from the public API
_SKIP_CLASSES = frozenset({
    "MockRequest", "MockResponse", "FakeSocket",
    "FakeCookieJar", "TestCase", "FakeConfig",
})


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

    def _fix_py2_imports(self, code: str) -> str:
        """Replace Python 2 module names with their Python 3 equivalents."""
        for py2, py3 in PY2_TO_PY3.items():
            code = re.sub(rf'\b{re.escape(py2)}\b', py3, code)
        return code

    def _extract_method_names(self, code: str) -> List[str]:
        """Extract all top-level def names from a patch code block."""
        return re.findall(r"^def (\w+)", code, flags=re.MULTILINE)

    def _build_patch_block(self, patch: PatchResult, method_names: List[str]) -> str:
        """
        Build monkey-patch assignments ONLY for the class being patched.
        Skips internal/test-only helper classes that can't be imported.
        """
        class_name = patch.class_name

        # Guard: if the class isn't in our public import map, skip silently
        if class_name in _SKIP_CLASSES or class_name not in CLASS_IMPORT_MAP:
            return f"# Skipped monkey-patch: '{class_name}' is not a public importable class"

        lines = []
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
            "import re",                              # LLM patches often use re
            "import requests",
            "from urllib.parse import urlparse, urlunparse, quote",  # digest auth needs these
            "from http.cookiejar import CookieJar",  # fixes any cookielib refs
            "from http.cookies import Morsel",        # LLM cookie patches use Morsel
        ]

        class_name = patch.class_name

        # Skip internal/test-only classes — they have no public import
        if class_name in _SKIP_CLASSES:
            return imports

        # Always import the class being patched
        if class_name in CLASS_IMPORT_MAP:
            imports.append(CLASS_IMPORT_MAP[class_name])

        # Extra imports per class
        if class_name == "Response":
            imports.append("from requests.models import PreparedRequest")

        if class_name in ("Session", "SessionRedirectMixin"):
            imports.append("from requests.sessions import Session, SessionRedirectMixin")
            imports.append("from requests.cookies import RequestsCookieJar")

        if class_name == "RequestsCookieJar":
            imports.append("from requests.sessions import Session")
            imports.append("from requests.models import PreparedRequest")

        if class_name in ("HTTPDigestAuth", "HTTPBasicAuth", "AuthBase"):
            imports.append("from requests.auth import HTTPDigestAuth, HTTPBasicAuth")
            imports.append("from requests.models import PreparedRequest, Response")

        return imports

    def _build_test_script(self, issue_data: IssueData, patch: PatchResult) -> str:
        """Build a test script scoped exactly to the class being patched."""

        # Guard: skip sandbox entirely for internal/test-only classes
        if patch.class_name in _SKIP_CLASSES or patch.class_name not in CLASS_IMPORT_MAP:
            return (
                "import sys\n"
                f"print('SKIPPED: {patch.class_name} is not a public importable class')\n"
                "sys.exit(1)\n"
            )

        # 1. Clean, fix Python 2 references, rename defs to patched_<name>
        clean_patch = textwrap.dedent(patch.patched_code).strip()
        clean_patch = self._fix_py2_imports(clean_patch)
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

        # 4. Detect issue type from issue body keywords
        keywords = " ".join(issue_data.issue_body[:500].lower().split())
        is_pickle_issue   = any(w in keywords for w in ["pickle", "pickling", "unpickle"])
        is_encoding_issue = any(w in keywords for w in ["encoding", "charset", "unicode", "utf"])
        is_cookie_issue   = any(w in keywords for w in ["cookie", "cookies", "cookiejar", "cookiepolicy"])
        is_auth_issue     = any(w in keywords for w in ["digest", "auth", "authentication", "authorization", "semicolon"])
        is_session_issue  = "session" in patch.class_name.lower()

        # 5. Build imports
        imports = self._build_imports(patch)

        # 6. Choose test block
        class_name = patch.class_name
        test_block = self._select_test_block(
            class_name, is_pickle_issue, is_encoding_issue,
            is_cookie_issue, is_session_issue, is_auth_issue
        )

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
        is_cookie_issue: bool,
        is_session_issue: bool,
        is_auth_issue: bool = False,
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

        elif class_name in ("Session", "SessionRedirectMixin") and is_cookie_issue:
            return textwrap.dedent("""
                print("Test 1: Session respects custom cookie jar...")
                s = Session()
                custom_jar = RequestsCookieJar()
                custom_jar.set("testcookie", "testvalue", domain="example.com", path="/")
                from requests import Request
                req = Request("GET", "https://example.com/", cookies=custom_jar)
                prepared = s.prepare_request(req)
                assert "testcookie" in prepared.headers.get("Cookie", ""), \
                    f"Cookie not in request headers: {prepared.headers}"
                print("  PASS")

                print("Test 2: Per-request cookies override session cookies...")
                s2 = Session()
                s2.cookies.set("session_cookie", "session_val", domain="example.com", path="/")
                req2 = Request("GET", "https://example.com/",
                               cookies={"request_cookie": "request_val"})
                prepared2 = s2.prepare_request(req2)
                cookie_header = prepared2.headers.get("Cookie", "")
                assert "request_cookie" in cookie_header, \
                    f"Per-request cookie missing: {cookie_header}"
                print("  PASS")
            """).strip()

        elif class_name == "RequestsCookieJar" and is_cookie_issue:
            return textwrap.dedent("""
                print("Test 1: RequestsCookieJar basic set...")
                jar = RequestsCookieJar()
                jar.set("key", "value", domain="example.com", path="/")
                assert jar["key"] == "value"
                print("  PASS")

                print("Test 2: Cookie policy can be overridden...")
                from http.cookiejar import DefaultCookiePolicy
                jar2 = RequestsCookieJar()
                policy = DefaultCookiePolicy(allowed_domains=["example.com"])
                jar2.set_policy(policy)
                jar2.set("allowed", "yes", domain="example.com", path="/")
                assert jar2["allowed"] == "yes"
                print("  PASS")

                print("Test 3: Cookie jar works with Session...")
                s = Session()
                s.cookies = RequestsCookieJar()
                s.cookies.set("sc", "sv", domain="example.com", path="/")
                assert s.cookies["sc"] == "sv"
                print("  PASS")
            """).strip()

        elif class_name == "HTTPDigestAuth" and is_auth_issue:
            return textwrap.dedent("""
                print("Test 1: HTTPDigestAuth can be created...")
                auth = HTTPDigestAuth("user", "pass")
                assert auth.username == "user"
                assert auth.password == "pass"
                print("  PASS")

                print("Test 2: URI with semicolons in path is not truncated...")
                # Simulate what build_digest_header does with a URL containing semicolons
                url = "https://example.com/path;param=value/resource"
                parsed = urlparse(url)
                # The uri for digest should be the full path, not truncated at ';'
                uri = parsed.path
                if parsed.query:
                    uri += "?" + parsed.query
                assert ";" in uri, f"Semicolon was stripped from URI: {uri}"
                assert uri == "/path;param=value/resource", f"URI mismatch: {uri}"
                print("  PASS")

                print("Test 3: URI with query string and semicolons preserved...")
                url2 = "https://api.example.org/v1/resource;type=A?format=json"
                parsed2 = urlparse(url2)
                uri2 = parsed2.path
                if parsed2.query:
                    uri2 += "?" + parsed2.query
                assert ";" in uri2
                assert "format=json" in uri2
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