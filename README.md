# 🤖 GH Bug Agent

> An autonomous AI agent that reads a GitHub issue URL, localizes the bug using AST analysis, generates a patch with an LLM, validates it in an isolated Docker sandbox, and produces a ready-to-use fix — fully automated, end to end.

## What It Does

Paste any public GitHub issue URL into the terminal UI. The agent:

1. **Fetches** the issue and scans the repo for relevant files via the GitHub API
2. **Parses** those files with Python AST to find suspicious classes and methods
3. **Generates** a targeted patch using Groq's LLaMA 3.3-70b — class-scoped, no hallucinated attributes
4. **Validates** the patch by running it inside an isolated Docker container against real tests
5. **Saves** a `patch_<ClassName>.py` and a `report.md` you can apply directly

If no patch passes, it retries patch generation up to 2× before reporting failure.

---

## Demo

**Issue:** [`psf/requests#6361`](https://github.com/psf/requests/issues/6361) — *Response class does not pickle `_next` attribute*

```
[Agent] ▶ Node: fetch_issue
[GitHub Reader] Fetching issue #6361 from psf/requests...
[GitHub Reader] Issue: Response class does not pickle _next attribute
[GitHub Reader] Found 36 Python files → 5 relevant files identified

[Agent] ▶ Node: parse_code
[Code Parser] Suspicious classes: ['Response', 'PreparedRequest']
[Code Parser] Suspicious methods: ['__getstate__ (MISSING)', '__getstate__', '__setstate__']

[Agent] ▶ Node: generate_patches
[Patch Generator] Analyzing Response in src/requests/models.py...

[Agent] ▶ Node: run_sandbox
[Sandbox] ✓ PASSED

✓ 1 patch PASSED — Response (src/requests/models.py)
  Confidence: HIGH

  Fix: Added _next to __getstate__ so it survives pickling

  Test 1: Basic pickle roundtrip...        PASS
  Test 2: _next preserved after pickle...  PASS
  Test 3: _next=None case...               PASS
```

---

## Architecture

```
 GitHub Issue URL
        │
        ▼
┌───────────────────┐
│  Node 1           │  PyGithub API → fetch issue body + scan repo tree
│  GitHub Reader    │  keyword scoring → top 5 relevant files
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Node 2           │  Python AST → extract all classes + methods
│  Code Parser      │  keyword match → rank suspicious locations
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Node 3           │  Groq LLaMA 3.3-70b → class-scoped patch
│  Patch Generator  │  sibling context injection → no cross-class hallucination
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Node 4           │  Docker python:3.11-slim → install requests → run tests
│  Sandbox Executor │  monkey-patch injection → real execution, real pass/fail
└────────┬──────────┘
         │
    ┌────┴────┐
    │         │
  PASS      FAIL (retry up to 2×)
    │         │
    ▼         ▼
┌───────────────────┐
│  Node 5           │  structured report + patch file saved to results/
│  Summarizer       │
└───────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM | [Groq](https://groq.com) — LLaMA 3.3-70b-versatile |
| GitHub integration | [PyGithub](https://github.com/PyGithub/PyGithub) |
| Code analysis | Python `ast` module |
| Sandbox execution | Docker `python:3.11-slim` |
| Backend API | FastAPI + Uvicorn |
| Frontend | Streamlit (terminal-themed UI) |

---

## Setup

### Prerequisites
- Python 3.11+
- Docker Desktop running
- A [Groq API key](https://console.groq.com) (free tier works)
- A [GitHub personal access token](https://github.com/settings/tokens) (read-only scopes)

### Install

```bash
git clone https://github.com/YOUR_USERNAME/gh-bug-agent
cd gh-bug-agent
pip install -r requirements.txt
```

### Configure

Create a `.env` file in the root:

```env
GITHUB_TOKEN=your_github_personal_access_token
GROQ_API_KEY=your_groq_api_key
```

### Run

**Option A — Full UI (recommended)**
```bash
# Terminal 1: start the backend
python backend.py

# Terminal 2: start the frontend
streamlit run frontend.py
```
Open `http://localhost:8501`, run diagnostics, paste a GitHub issue URL, hit Execute.

**Option B — CLI only**
```bash
python main.py
```
Edit `main.py` to target any repo and issue number.

---

## Usage Examples

```python
from modules.agent import run_agent

# Fix a pickle issue in requests
run_agent("psf/requests", 6361)

# Fix a cookie handling bug
run_agent("psf/requests", 6890)

# Try on other repos
run_agent("encode/httpx", 1234)
run_agent("pallets/flask", 5678)
```

Output is saved to `results/<repo>_<issue>/`:
```
results/
└── psf_requests_6361/
    ├── patch_Response.py   ← ready-to-apply fix
    └── report.md           ← full agent report
```

---

## Project Structure

```
gh-bug-agent/
├── modules/
│   ├── agent.py             # LangGraph state graph + all nodes + routing
│   ├── github_reader.py     # GitHub API: fetch issue + relevant files
│   ├── code_parser.py       # AST analysis: suspicious class/method ranking
│   ├── patch_generator.py   # Groq LLM: class-scoped patch generation
│   └── sandbox_executor.py  # Docker: monkey-patch injection + test execution
├── backend.py               # FastAPI server
├── frontend.py              # Streamlit terminal UI
├── main.py                  # CLI entry point
├── results/                 # Agent outputs (git-ignored)
├── .env                     # API keys (git-ignored)
└── requirements.txt
```

---

## Tested Issues

| Repo | Issue | Status | Bug Type |
|---|---|---|---|
| psf/requests | [#6361](https://github.com/psf/requests/issues/6361) | ✅ PASS | Pickle / `__getstate__` |
| psf/requests | [#6890](https://github.com/psf/requests/issues/6890) | ✅ PARTIAL | Cookie value escaping |
| psf/requests | [#6990](https://github.com/psf/requests/issues/6990) | 🔄 Rate limited | Digest auth URI |

---

## Known Limitations

- **Groq free tier TPD limit** — 100k tokens/day. Running 3+ complex issues in one session will hit it. Upgrade to Dev tier or wait for the daily reset.
- **Docker required** — the sandbox runs locally. No cloud deployment of the execution layer yet.
- **Python-only** — the AST parser only handles `.py` files.
- **Top 5 files** — the GitHub reader scores files by keyword match and picks the top 5. Issues touching many files simultaneously may miss relevant context.

---

## Roadmap

- [ ] Exponential backoff on Groq 429 rate limit errors
- [ ] Support for `encode/httpx`, `urllib3`, `flask`
- [ ] E2B cloud sandbox as Docker alternative (for deployment)
- [ ] Auto-open a pull request with the passing patch
- [ ] Multi-file patches (current: one class per patch)
- [ ] Support JavaScript / TypeScript repos

---


## License

MIT — use freely, contributions welcome.
