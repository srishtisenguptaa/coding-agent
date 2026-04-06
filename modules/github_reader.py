import os
from github import Github
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Optional

load_dotenv()

@dataclass
class IssueData:
    """Everything the agent needs to know about a GitHub issue."""
    repo_name: str
    issue_number: int
    issue_title: str
    issue_body: str
    relevant_files: List[str]      # file paths likely related to the bug
    file_contents: dict            # {filepath: content}
    test_files: List[str]          # existing test files found

class GitHubReader:
    def __init__(self):
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN not found in .env")
        self.github = Github(token)

    def read_issue(self, repo_name: str, issue_number: int) -> IssueData:
        """
        Main entry point.
        Given a repo like 'psf/requests' and issue number 1234,
        returns everything the agent needs to attempt a fix.
        """
        print(f"[GitHub Reader] Fetching issue #{issue_number} from {repo_name}...")

        repo = self.github.get_repo(repo_name)
        issue = repo.get_issue(number=issue_number)

        print(f"[GitHub Reader] Issue: {issue.title}")
        print(f"[GitHub Reader] Scanning repo file tree...")

        # Get all Python files in the repo (max 100 to stay within API limits)
        all_files = self._get_python_files(repo)
        print(f"[GitHub Reader] Found {len(all_files)} Python files")

        # Find files most likely related to this issue
        relevant_files = self._find_relevant_files(
            all_files,
            issue.title,
            issue.body or ""
        )
        print(f"[GitHub Reader] {len(relevant_files)} relevant files identified")

        # Read contents of relevant files
        file_contents = self._read_files(repo, relevant_files)

        # Find test files
        test_files = [f for f in all_files if "test" in f.lower()]

        return IssueData(
            repo_name=repo_name,
            issue_number=issue_number,
            issue_title=issue.title,
            issue_body=issue.body or "No description provided.",
            relevant_files=relevant_files,
            file_contents=file_contents,
            test_files=test_files[:5]  # top 5 test files only
        )

    def _get_python_files(self, repo, max_files: int = 100) -> List[str]:
        """Walk the repo tree and collect Python file paths."""
        files = []
        try:
            contents = repo.get_git_tree(sha="HEAD", recursive=True)
            for item in contents.tree:
                if item.path.endswith(".py") and item.type == "blob":
                    files.append(item.path)
                if len(files) >= max_files:
                    break
        except Exception as e:
            print(f"[GitHub Reader] Warning: Could not read file tree: {e}")
        return files

    def _find_relevant_files(
        self,
        all_files: List[str],
        issue_title: str,
        issue_body: str
    ) -> List[str]:
        """
        Simple keyword matching to find files relevant to the issue.
        No LLM needed here — fast and free.
        """
        # Extract keywords from issue title and body
        text = (issue_title + " " + issue_body).lower()
        words = set(text.replace(".", " ").replace("/", " ").split())

        # Remove common noise words
        noise = {"the", "a", "an", "is", "in", "it", "of", "to", "and",
                 "or", "for", "with", "this", "that", "when", "not", "be"}
        keywords = words - noise

        scored = []
        for filepath in all_files:
            # Score each file by how many keywords appear in its path
            path_lower = filepath.lower()
            score = sum(1 for kw in keywords if kw in path_lower)
            if score > 0:
                scored.append((score, filepath))

        # Sort by score descending, return top 5
        scored.sort(reverse=True)
        relevant = [f for _, f in scored[:5]]

        # Always include files with "main" or "core" or "base" in name as fallback
        if len(relevant) < 3:
            for f in all_files:
                if any(k in f.lower() for k in ["main", "core", "base", "util"]):
                    if f not in relevant:
                        relevant.append(f)
                if len(relevant) >= 5:
                    break

        return relevant

    def _read_files(self, repo, file_paths: List[str]) -> dict:
        """Read file contents from GitHub. Returns {path: content}."""
        contents = {}
        for path in file_paths:
            try:
                file_obj = repo.get_contents(path)
                contents[path] = file_obj.decoded_content.decode("utf-8")
            except Exception as e:
                contents[path] = f"# Could not read file: {e}"
        return contents