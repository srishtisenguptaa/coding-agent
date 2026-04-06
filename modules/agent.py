import os
from typing import TypedDict, List, Optional, Annotated
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from modules.github_reader import GitHubReader, IssueData
from modules.code_parser import CodeParser, ParsedCode
from modules.patch_generator import PatchGenerator, PatchResult
from modules.sandbox_executor import SandboxExecutor, ExecutionResult
from dotenv import load_dotenv

load_dotenv()


# ── Agent State ───────────────────────────────────────────────────────────────
# This is the shared memory that flows through every node in the graph
class AgentState(TypedDict):
    # Input
    repo_name: str
    issue_number: int

    # Populated by each node
    issue_data: Optional[IssueData]
    parsed_code: Optional[ParsedCode]
    patches: Optional[List[PatchResult]]
    results: Optional[List[ExecutionResult]]

    # Control flow
    passed_patches: Optional[List[ExecutionResult]]
    failed_patches: Optional[List[ExecutionResult]]
    retry_count: int
    error: Optional[str]
    final_summary: Optional[str]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def node_fetch_issue(state: AgentState) -> AgentState:
    """Node 1: Fetch the GitHub issue and relevant files."""
    print("\n[Agent] ▶ Node: fetch_issue")
    try:
        reader = GitHubReader()
        issue_data = reader.read_issue(state["repo_name"], state["issue_number"])
        return {**state, "issue_data": issue_data, "error": None}
    except Exception as e:
        return {**state, "error": f"fetch_issue failed: {e}"}


def node_parse_code(state: AgentState) -> AgentState:
    """Node 2: Parse the code and find suspicious locations."""
    print("\n[Agent] ▶ Node: parse_code")
    try:
        parser = CodeParser()
        parsed = parser.parse(state["issue_data"])
        return {**state, "parsed_code": parsed, "error": None}
    except Exception as e:
        return {**state, "error": f"parse_code failed: {e}"}


def node_generate_patches(state: AgentState) -> AgentState:
    """Node 3: Generate patches using Groq."""
    print("\n[Agent] ▶ Node: generate_patches")
    try:
        patcher = PatchGenerator()
        patches = patcher.generate(state["issue_data"], state["parsed_code"])
        if not patches:
            return {**state, "error": "No patches generated"}
        return {**state, "patches": patches, "error": None}
    except Exception as e:
        return {**state, "error": f"generate_patches failed: {e}"}


def node_run_sandbox(state: AgentState) -> AgentState:
    """Node 4: Run patches in Docker sandbox."""
    print("\n[Agent] ▶ Node: run_sandbox")
    try:
        executor = SandboxExecutor()
        results = executor.run(state["issue_data"], state["patches"])

        passed = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        return {
            **state,
            "results": results,
            "passed_patches": passed,
            "failed_patches": failed,
            "error": None
        }
    except Exception as e:
        return {**state, "error": f"run_sandbox failed: {e}"}


def node_summarize(state: AgentState) -> AgentState:
    """Node 5: Generate a final human-readable summary."""
    print("\n[Agent] ▶ Node: summarize")

    passed = state.get("passed_patches", [])
    failed = state.get("failed_patches", [])
    issue = state["issue_data"]

    lines = []
    lines.append("=" * 60)
    lines.append(f"AGENT REPORT")
    lines.append("=" * 60)
    lines.append(f"Repo    : {issue.repo_name}")
    lines.append(f"Issue   : #{issue.issue_number} — {issue.issue_title}")
    lines.append(f"Files   : {', '.join(issue.relevant_files)}")
    lines.append("")

    if passed:
        lines.append(f"✓ {len(passed)} patch(es) PASSED:")
        for r in passed:
            lines.append(f"\n  Class: {r.patch.class_name}")
            lines.append(f"  File : {r.patch.filepath}")
            lines.append(f"  Confidence: {r.patch.confidence.upper()}")
            lines.append(f"\n  WHY IT'S BUGGY:")
            lines.append(f"  {r.patch.explanation[:300]}")
            lines.append(f"\n  FIX:")
            lines.append(f"  {r.patch.patched_code[:500]}")
            lines.append(f"\n  TEST OUTPUT:")
            lines.append(f"  {r.test_output.strip()}")
    else:
        lines.append("✗ No patches passed.")

    if failed:
        lines.append(f"\n✗ {len(failed)} patch(es) FAILED:")
        for r in failed:
            lines.append(f"  - {r.patch.class_name}: {r.error_output[-100:]}")

    lines.append("\n" + "=" * 60)

    summary = "\n".join(lines)
    print(summary)
    return {**state, "final_summary": summary}


def node_handle_error(state: AgentState) -> AgentState:
    """Node: Handle errors gracefully."""
    print(f"\n[Agent] ✗ Error encountered: {state['error']}")
    retry = state.get("retry_count", 0)
    if retry < 2:
        print(f"[Agent] Retrying... (attempt {retry + 1})")
        return {**state, "retry_count": retry + 1, "error": None}
    print("[Agent] Max retries reached. Stopping.")
    return {**state, "final_summary": f"Agent failed: {state['error']}"}


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_fetch(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "parse_code"

def route_after_parse(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "generate_patches"

def route_after_generate(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "run_sandbox"

def route_after_sandbox(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    passed = state.get("passed_patches", [])
    if passed:
        return "summarize"
    # No patches passed — retry if we haven't exceeded limit
    retry = state.get("retry_count", 0)
    if retry < 2:
        print(f"\n[Agent] No patches passed. Retrying patch generation (attempt {retry + 1})...")
        return "generate_patches"
    return "summarize"

def route_after_error(state: AgentState) -> str:
    if state.get("error"):
        return "summarize"  # give up
    return "fetch_issue"    # retry from start


# ── Build the Graph ───────────────────────────────────────────────────────────

def build_agent() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("fetch_issue", node_fetch_issue)
    graph.add_node("parse_code", node_parse_code)
    graph.add_node("generate_patches", node_generate_patches)
    graph.add_node("run_sandbox", node_run_sandbox)
    graph.add_node("summarize", node_summarize)
    graph.add_node("handle_error", node_handle_error)

    # Entry point
    graph.set_entry_point("fetch_issue")

    # Add conditional edges
    graph.add_conditional_edges("fetch_issue", route_after_fetch)
    graph.add_conditional_edges("parse_code", route_after_parse)
    graph.add_conditional_edges("generate_patches", route_after_generate)
    graph.add_conditional_edges("run_sandbox", route_after_sandbox)
    graph.add_conditional_edges("handle_error", route_after_error)

    # Terminal node
    graph.add_edge("summarize", END)

    return graph.compile()


# ── Run the agent ─────────────────────────────────────────────────────────────

def run_agent(repo_name: str, issue_number: int) -> str:
    """Main entry point to run the full agent."""
    agent = build_agent()

    initial_state: AgentState = {
        "repo_name": repo_name,
        "issue_number": issue_number,
        "issue_data": None,
        "parsed_code": None,
        "patches": None,
        "results": None,
        "passed_patches": None,
        "failed_patches": None,
        "retry_count": 0,
        "error": None,
        "final_summary": None,
    }

    print(f"\n[Agent] Starting for {repo_name} issue #{issue_number}")
    final_state = agent.invoke(initial_state)
    return final_state.get("final_summary", "No summary generated.")