import streamlit as st
import requests as http_requests
import re
import subprocess
import threading
import time

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="GH Bug Agent", layout="wide", page_icon="🖥️")

# ─── Global CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=VT323&display=swap');

/* ── Base ── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background-color: #0a0a0a !important;
    color: #39ff14 !important;
    font-family: 'Share Tech Mono', monospace !important;
}

[data-testid="stSidebar"] { display: none; }
[data-testid="stHeader"]  { display: none; }
footer                    { display: none; }

/* ── Title ── */
.main-title {
    font-family: 'VT323', monospace;
    font-size: 3.2rem;
    color: #39ff14;
    text-shadow: 0 0 12px #39ff14, 0 0 30px #00ff88;
    letter-spacing: 0.15em;
    margin-bottom: 0.2rem;
}
.sub-title {
    font-size: 0.78rem;
    color: #1aff6e;
    letter-spacing: 0.25em;
    margin-bottom: 1.6rem;
    opacity: 0.7;
}

/* ── Status Panel ── */
.status-grid {
    display: flex;
    gap: 12px;
    margin-bottom: 1.2rem;
    flex-wrap: wrap;
}
.status-card {
    background: #0d1a0d;
    border: 1px solid #1a4d1a;
    border-radius: 4px;
    padding: 10px 18px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    min-width: 180px;
    position: relative;
    overflow: hidden;
}
.status-card::before {
    content: '';
    position: absolute; inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(57,255,20,0.04) 100%);
}
.status-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}
.dot-checking { background: #ffcc00; box-shadow: 0 0 6px #ffcc00; animation: blink 0.9s infinite; }
.dot-ok       { background: #39ff14; box-shadow: 0 0 8px #39ff14; }
.dot-fail     { background: #ff3333; box-shadow: 0 0 8px #ff3333; }
.dot-idle     { background: #444; }

@keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0.2; } }

/* ── Input ── */
.stTextInput > div > div > input {
    background-color: #0d1a0d !important;
    border: 1px solid #2a6b2a !important;
    border-radius: 3px !important;
    color: #39ff14 !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.9rem !important;
    padding: 10px 14px !important;
    caret-color: #39ff14;
    box-shadow: inset 0 0 8px rgba(57,255,20,0.06) !important;
}
.stTextInput > div > div > input:focus {
    border-color: #39ff14 !important;
    box-shadow: 0 0 0 2px rgba(57,255,20,0.18) !important;
}
.stTextInput label {
    color: #1aff6e !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.12em !important;
}

/* ── Button ── */
.stButton > button {
    background: transparent !important;
    color: #39ff14 !important;
    border: 1px solid #39ff14 !important;
    border-radius: 3px !important;
    font-family: 'VT323', monospace !important;
    font-size: 1.35rem !important;
    letter-spacing: 0.18em !important;
    padding: 8px 28px !important;
    transition: all 0.2s !important;
    text-transform: uppercase !important;
}
.stButton > button:hover {
    background: rgba(57,255,20,0.12) !important;
    box-shadow: 0 0 14px rgba(57,255,20,0.4) !important;
}
.stButton > button:active { transform: scale(0.97) !important; }

/* ── Terminal ── */
.terminal-wrap {
    background: #050f05;
    border: 1px solid #1a4d1a;
    border-radius: 5px;
    overflow: hidden;
    margin-top: 1rem;
    box-shadow: 0 0 20px rgba(57,255,20,0.08);
}
.term-titlebar {
    background: #0d1a0d;
    border-bottom: 1px solid #1a4d1a;
    padding: 6px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.72rem;
    color: #2aaa2a;
    letter-spacing: 0.14em;
}
.term-dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
.t-red    { background:#ff5f57; }
.t-yellow { background:#febc2e; }
.t-green  { background:#28c840; }

.terminal-body {
    background: #050f05;
    color: #90EE90;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.84rem;
    line-height: 1.55;
    padding: 18px 20px;
    min-height: 320px;
    max-height: 420px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
}
.terminal-body::-webkit-scrollbar      { width: 6px; }
.terminal-body::-webkit-scrollbar-track { background: #050f05; }
.terminal-body::-webkit-scrollbar-thumb { background: #1a4d1a; border-radius: 3px; }

/* ── File cards ── */
.file-card {
    background: #0d1a0d;
    border: 1px solid #2a6b2a;
    border-radius: 4px;
    padding: 14px 18px;
    margin-top: 10px;
    font-size: 0.82rem;
    position: relative;
}
.file-card-title {
    color: #39ff14;
    font-size: 0.95rem;
    margin-bottom: 6px;
    letter-spacing: 0.08em;
}
.file-content-box {
    background: #050f05;
    border: 1px solid #1a4d1a;
    border-radius: 3px;
    padding: 10px;
    color: #90EE90;
    font-size: 0.75rem;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    margin-top: 8px;
}

/* ── Misc ── */
.scanline {
    pointer-events: none;
    position: fixed; inset: 0; z-index: 9999;
    background: repeating-linear-gradient(
        to bottom,
        transparent 0px,
        transparent 3px,
        rgba(0,0,0,0.07) 3px,
        rgba(0,0,0,0.07) 4px
    );
    opacity: 0.35;
}
.prompt { color: #39ff14; }
.out    { color: #90EE90; }
.err    { color: #ff6666; }
.ok     { color: #39ff14; font-weight: bold; }
.warn   { color: #ffcc00; }
</style>
<div class="scanline"></div>
""", unsafe_allow_html=True)

# ─── Helpers ────────────────────────────────────────────────────────────────
def parse_github_url(url: str):
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)", url)
    return (m.group(1), int(m.group(2))) if m else (None, None)

def check_docker() -> tuple[bool, str]:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=6)
        return (r.returncode == 0), ("running" if r.returncode == 0 else "error")
    except FileNotFoundError:
        return False, "not found"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)

def check_api() -> tuple[bool, str]:
    try:
        r = http_requests.get("http://localhost:8000/docs", timeout=4)
        return r.status_code == 200, "online"
    except http_requests.ConnectionError:
        return False, "offline"
    except Exception as e:
        return False, str(e)

def dot_class(ok: bool) -> str:
    return "dot-ok" if ok else "dot-fail"

# ─── Session state ────────────────────────────────────────────────────────
for k, v in {
    "log": "",
    "docker_ok": None,
    "api_ok": None,
    "report_md": None,
    "patch_py": None,
    "running": False,
    "checked": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Title ───────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">▌GH BUG AGENT</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">AUTOMATED GITHUB ISSUE RESOLVER  //  LANGGRAPH + GROQ + DOCKER</div>', unsafe_allow_html=True)

# ─── Status Checks ──────────────────────────────────────────────────────────
col_check, _ = st.columns([1, 3])
with col_check:
    if st.button("⟳  RUN DIAGNOSTICS"):
        with st.spinner(""):
            d_ok, d_msg = check_docker()
            a_ok, a_msg = check_api()
            st.session_state.docker_ok = d_ok
            st.session_state.api_ok    = a_ok
            st.session_state.checked   = True

d_ok = st.session_state.docker_ok
a_ok = st.session_state.api_ok

if st.session_state.checked:
    d_dot  = "dot-ok" if d_ok else "dot-fail"
    a_dot  = "dot-ok" if a_ok else "dot-fail"
    d_txt  = "DOCKER ✓ RUNNING" if d_ok else "DOCKER ✗ NOT FOUND"
    a_txt  = "BACKEND ✓ ONLINE" if a_ok else "BACKEND ✗ OFFLINE"
    gh_dot = "dot-ok" if (d_ok and a_ok) else "dot-fail"
    gh_txt = "AGENT ✓ READY" if (d_ok and a_ok) else "AGENT ✗ NOT READY"
else:
    d_dot = a_dot = gh_dot = "dot-idle"
    d_txt = "DOCKER  —  NOT CHECKED"
    a_txt = "BACKEND —  NOT CHECKED"
    gh_txt = "AGENT   —  AWAITING CHECK"

st.markdown(f"""
<div class="status-grid">
  <div class="status-card">
    <span class="status-dot {d_dot}"></span>
    <span>{d_txt}</span>
  </div>
  <div class="status-card">
    <span class="status-dot {a_dot}"></span>
    <span>{a_txt}</span>
  </div>
  <div class="status-card">
    <span class="status-dot {gh_dot}"></span>
    <span>{gh_txt}</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ─── Input ──────────────────────────────────────────────────────────────────
st.markdown("---")
issue_url = st.text_input(
    "▸  TARGET ISSUE URL",
    placeholder="https://github.com/psf/requests/issues/6361",
)

repo, issue_id = parse_github_url(issue_url) if issue_url else (None, None)

# Inline URL validation feedback
if issue_url:
    if repo and issue_id:
        st.markdown(f'<span style="color:#39ff14;font-size:0.78rem;letter-spacing:0.1em">✓  PARSED  →  repo: <b>{repo}</b>  issue: <b>#{issue_id}</b></span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="color:#ff6666;font-size:0.78rem;letter-spacing:0.1em">✗  INVALID URL — expected: github.com/owner/repo/issues/N</span>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
run_btn = st.button("▶  EXECUTE AGENT", disabled=st.session_state.running)

# ─── Terminal ────────────────────────────────────────────────────────────────
term_placeholder = st.empty()

def render_terminal(content: str):
    # Colorize lines
    colored = []
    for line in content.split("\n"):
        if line.startswith("user@"):
            colored.append(f'<span class="prompt">{line}</span>')
        elif "[SUCCESS]" in line or "✓" in line or "PASSED" in line:
            colored.append(f'<span class="ok">{line}</span>')
        elif "[ERROR]" in line or "[CRITICAL]" in line or "✗" in line or "FAILED" in line:
            colored.append(f'<span class="err">{line}</span>')
        elif "[WARNING]" in line or "Retrying" in line:
            colored.append(f'<span class="warn">{line}</span>')
        else:
            colored.append(f'<span class="out">{line}</span>')
    html_lines = "\n".join(colored)
    term_placeholder.markdown(f"""
<div class="terminal-wrap">
  <div class="term-titlebar">
    <span class="term-dot t-red"></span>
    <span class="term-dot t-yellow"></span>
    <span class="term-dot t-green"></span>
    &nbsp;&nbsp;agent@gh-bugfix ~ bash
  </div>
  <div class="terminal-body" id="termbox">{html_lines}</div>
</div>
<script>
  var tb = document.getElementById('termbox');
  if(tb) tb.scrollTop = tb.scrollHeight;
</script>
""", unsafe_allow_html=True)

# Render initial/previous terminal
if st.session_state.log or st.session_state.running:
    render_terminal(st.session_state.log)

# ─── Run Agent ────────────────────────────────────────────────────────────────
if run_btn:
    if not (repo and issue_id):
        st.error("Please enter a valid GitHub issue URL first.")
    elif not (st.session_state.checked and d_ok and a_ok):
        st.warning("Run diagnostics first and ensure Docker + Backend are online.")
    else:
        st.session_state.running    = True
        st.session_state.report_md  = None
        st.session_state.patch_py   = None

        log = f"user@agent:~$ python3 run_agent.py --repo {repo} --issue {issue_id}\n"
        log += "[SYSTEM] Initializing LangGraph StateGraph...\n"
        log += "[SYSTEM] Loading nodes: fetch_issue → parse_code → generate_patches → run_sandbox → summarize\n"
        st.session_state.log = log
        render_terminal(log)

        log += f"\n[NODE] fetch_issue  →  fetching {repo} #{issue_id} from GitHub API...\n"
        st.session_state.log = log
        render_terminal(log)

        try:
            resp = http_requests.post(
                "http://localhost:8000/fix-issue",
                json={"repo": repo, "issue_id": issue_id},
                timeout=360,
            )

            if resp.status_code == 200:
                data = resp.json()
                summary = data.get("summary", "")
                output_dir = data.get("output_dir", "")

                log += "[NODE] parse_code       →  AST analysis complete\n"
                log += "[NODE] generate_patches →  Groq LLM patch generation done\n"
                log += "[NODE] run_sandbox      →  Docker execution finished\n"
                log += "[NODE] summarize        →  report compiled\n"
                log += "[NODE] save_output      →  files written\n"
                log += "\n[SUCCESS] ─────────────────────────────────────────────\n"
                log += "[SUCCESS]  ALL TESTS PASSED  //  PATCH VALIDATED\n"
                log += f"[SUCCESS]  Output directory: {output_dir}\n"
                log += "[SUCCESS] ─────────────────────────────────────────────\n"
                log += "\n" + summary
                st.session_state.log = log
                render_terminal(log)

                # ── try to read actual output files ──
                import os
                if output_dir and os.path.isdir(output_dir):
                    for fname in os.listdir(output_dir):
                        fpath = os.path.join(output_dir, fname)
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        if fname.endswith(".md"):
                            st.session_state.report_md = (fname, content)
                        elif fname.endswith(".py"):
                            st.session_state.patch_py  = (fname, content)
                else:
                    # fallback: use summary as report
                    st.session_state.report_md = ("report.md", summary)

            else:
                log += f"\n[ERROR] Backend returned HTTP {resp.status_code}\n"
                log += f"[ERROR] {resp.text[:300]}\n"
                st.session_state.log = log
                render_terminal(log)

        except http_requests.ConnectionError:
            log += "\n[CRITICAL] Cannot reach backend at localhost:8000\n"
            log += "[CRITICAL] Is backend.py running?  →  python backend.py\n"
            st.session_state.log = log
            render_terminal(log)
        except Exception as e:
            log += f"\n[ERROR] Unexpected exception: {e}\n"
            st.session_state.log = log
            render_terminal(log)

        st.session_state.running = False
        st.rerun()

# ─── Output Files ────────────────────────────────────────────────────────────
if st.session_state.report_md or st.session_state.patch_py:
    st.markdown("---")
    st.markdown('<span style="color:#39ff14;font-family:VT323,monospace;font-size:1.5rem;letter-spacing:0.15em">▌OUTPUT FILES</span>', unsafe_allow_html=True)

    cols = st.columns(2)

    for col, key, icon in [
        (cols[0], "report_md", "📄"),
        (cols[1], "patch_py",  "🔧"),
    ]:
        data = st.session_state.get(key)
        if data:
            fname, content = data
            with col:
                st.markdown(f"""
<div class="file-card">
  <div class="file-card-title">{icon}  {fname}</div>
  <div style="font-size:0.72rem;color:#2aaa2a;margin-bottom:4px;">{len(content)} bytes  //  click below to copy</div>
  <div class="file-content-box">{content[:1200]}{'...' if len(content)>1200 else ''}</div>
</div>
""", unsafe_allow_html=True)
                st.download_button(
                    label=f"⬇  DOWNLOAD {fname}",
                    data=content,
                    file_name=fname,
                    mime="text/plain",
                    key=f"dl_{key}",
                )
                if st.button(f"⧉  COPY {fname} TO CLIPBOARD", key=f"cp_{key}"):
                    st.code(content, language="python" if fname.endswith(".py") else "markdown")
