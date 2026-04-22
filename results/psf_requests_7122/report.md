# Agent Report

**Repo:** psf/requests  
**Issue:** #7122 — Unable to override cookie policy in Session.prepare_request  
**Generated:** 2026-04-07 10:45:43  

---

```
============================================================
AGENT REPORT
============================================================
Repo    : psf/requests
Issue   : #7122 — Unable to override cookie policy in Session.prepare_request
Files   : src/requests/sessions.py, src/requests/exceptions.py, src/requests/cookies.py, src/requests/__version__.py, tests/test_requests.py

✗ No patches passed.

✗ 2 patch(es) FAILED:
  - RequestsCookieJar:  isinstance(value, Morsel):
                         ^^^^^^
NameError: name 'Morsel' is not defined

  - Session:                       ^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'headers'


============================================================
```

