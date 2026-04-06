# 🤖 AI Coding Agent

An autonomous agent that reads GitHub issues, localizes bugs using AST analysis, generates patches with an LLM, and validates fixes in an isolated Docker sandbox.

Built with **LangGraph**, **Groq (LLaMA 3.3-70b)**, **PyGithub**, and **Docker**.

---

## Architecture
```
GitHub Issue
     ↓
[Node 1] GitHub Reader    → fetches issue + relevant files via GitHub API
     ↓
[Node 2] Code Parser      → AST analysis to locate suspicious classes/methods
     ↓
[Node 3] Patch Generator  → Groq LLM writes the fix
     ↓
[Node 4] Sandbox Executor → runs patch in isolated Docker container
     ↓
[Node 5] Summarizer       → human-readable report with pass/fail
```

The graph has **automatic retry logic** — if no patches pass, it regenerates up to 2 times before reporting failure.

---

## Demo

Tested on real GitHub issue [psf/requests#6361](https://github.com/psf/requests/issues/6361):

> *Response class does not pickle `_next` attribute*

**Agent output:**
```
✓ 1 patch PASSED — Response (src/requests/models.py)
  Confidence: HIGH

  Fix: Added _next to __getstate__ so it's included during pickling

  Tests:
    Test 1: Basic pickle roundtrip...  PASS
    Test 2: _next preserved after pickle...  PASS
    Test 3: _next=None case...  PASS
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph |
| LLM | Groq — LLaMA 3.3-70b-versatile |
| GitHub integration | PyGithub |
| Code analysis | Python AST |
| Sandbox execution | Docker (python:3.11-slim) |
| Backend | Python 3.11 |

---

## Setup
```bash
git clone https://github.com/YOUR_USERNAME/coding-agent
cd coding-agent
pip install -r requirements.txt
```

Create `.env`:
```
GITHUB_TOKEN=your_github_token
GROQ_API_KEY=your_groq_key
```

Make sure Docker Desktop is running, then:
```bash
python main.py
```

---

## Usage

Edit `main.py` to point at any public Python repo and issue:
```python
from modules.agent import run_agent

summary = run_agent("psf/requests", 6361)
```

---

## Project Structure
```
coding-agent/
├── modules/
│   ├── github_reader.py     # GitHub API integration
│   ├── code_parser.py       # AST-based bug localization
│   ├── patch_generator.py   # LLM patch generation
│   ├── sandbox_executor.py  # Docker sandbox execution
│   └── agent.py             # LangGraph agent graph
├── main.py
└── .env
```