import ast
from dataclasses import dataclass
from typing import List, Optional
from modules.github_reader import IssueData


@dataclass
class ClassInfo:
    """Represents a class found in a Python file."""
    name: str
    filepath: str
    start_line: int
    end_line: int
    methods: List[str]
    source: str  # full source of the class


@dataclass
class ParsedCode:
    """Everything the agent needs to understand the codebase structure."""
    classes: List[ClassInfo]
    suspicious_classes: List[ClassInfo]   # classes most likely containing the bug
    suspicious_methods: List[dict]         # methods most likely buggy
    issue_keywords: List[str]             # keywords extracted from issue


class CodeParser:
    def __init__(self):
        pass

    def parse(self, issue_data: IssueData) -> ParsedCode:
        """
        Main entry point.
        Reads all relevant files, parses them, finds suspicious locations.
        """
        print("\n[Code Parser] Starting AST analysis...")

        all_classes = []

        for filepath, content in issue_data.file_contents.items():
            if not content.startswith("# Could not read"):
                classes = self._extract_classes(filepath, content)
                all_classes.extend(classes)
                print(f"[Code Parser] {filepath} → {len(classes)} classes found")

        # Extract keywords from the issue
        keywords = self._extract_keywords(
            issue_data.issue_title,
            issue_data.issue_body
        )
        print(f"[Code Parser] Issue keywords: {keywords}")

        # Find which classes are suspicious
        suspicious_classes = self._find_suspicious_classes(all_classes, keywords)
        print(f"[Code Parser] Suspicious classes: {[c.name for c in suspicious_classes]}")

        # Find which methods inside those classes are suspicious
        suspicious_methods = self._find_suspicious_methods(suspicious_classes, keywords)
        print(f"[Code Parser] Suspicious methods: {[m['name'] for m in suspicious_methods]}")

        return ParsedCode(
            classes=all_classes,
            suspicious_classes=suspicious_classes,
            suspicious_methods=suspicious_methods,
            issue_keywords=keywords
        )

    def _extract_classes(self, filepath: str, source: str) -> List[ClassInfo]:
        """Parse a Python file and extract all class definitions."""
        classes = []
        try:
            tree = ast.parse(source)
            source_lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Get all method names in this class
                    methods = [
                        n.name for n in ast.walk(node)
                        if isinstance(n, ast.FunctionDef)
                    ]

                    # Extract the actual source lines for this class
                    start = node.lineno - 1
                    end = node.end_lineno
                    class_source = "\n".join(source_lines[start:end])

                    classes.append(ClassInfo(
                        name=node.name,
                        filepath=filepath,
                        start_line=node.lineno,
                        end_line=node.end_lineno,
                        methods=methods,
                        source=class_source
                    ))
        except SyntaxError as e:
            print(f"[Code Parser] Syntax error in {filepath}: {e}")
        return classes

    def _extract_keywords(self, title: str, body: str) -> List[str]:
        """Pull meaningful keywords from the issue title and body."""
        # Only use title + first 300 chars of body to avoid noise
        text = (title + " " + body[:300]).lower()

        for char in [".", ",", ":", ";", "(", ")", "`", "'", '"', "\n", "-", "/", "\\", "<", ">"]:
            text = text.replace(char, " ")

        words = text.split()

        noise = {
            "the", "a", "an", "is", "in", "it", "of", "to", "and", "or",
            "for", "with", "this", "that", "when", "not", "be", "are",
            "was", "were", "has", "have", "had", "do", "does", "did",
            "but", "if", "on", "at", "by", "from", "as", "its", "i",
            "using", "without", "can", "will", "result", "actual",
            "expected", "following", "traceback", "most", "last", "call",
            "file", "line", "error", "class", "module", "self", "return",
            ">>>", "lib", "python", "site", "users", "recent"
        }

        # Only keep clean alphabetic words longer than 2 chars
        keywords = list(set(
            w for w in words
            if w not in noise and len(w) > 2 and w.isalpha()
        ))
        return keywords[:15]

    def _find_suspicious_classes(
        self,
        classes: List[ClassInfo],
        keywords: List[str]
    ) -> List[ClassInfo]:
        """Score each class by keyword match — higher score = more suspicious."""
        scored = []
        for cls in classes:
            score = 0
            cls_text = (cls.name + " " + " ".join(cls.methods)).lower()

            for kw in keywords:
                if kw in cls_text:
                    score += 2
                if kw in cls.source.lower():
                    score += 1

            if score > 0:
                scored.append((score, cls))

        scored.sort(reverse=True, key=lambda x: x[0])
        return [cls for _, cls in scored[:3]]  # top 3 suspicious classes

    def _find_suspicious_methods(
            self,
            classes: List[ClassInfo],
            keywords: List[str]
        ) -> List[dict]:
            """Find methods most likely containing the bug. Skips test classes."""
            suspicious = []

            pickle_keywords = {"pickle", "pickling", "pickled", "unpickle", "reduce"}
            is_pickle_issue = any(kw in pickle_keywords for kw in keywords)

            for cls in classes:
                # Skip test classes — bug is in source, not tests
                if cls.name.startswith("Test") or "test" in cls.filepath.lower():
                    continue

                for method in cls.methods:
                    score = 0
                    method_lower = method.lower()

                    for kw in keywords:
                        if kw in method_lower:
                            score += 3

                    if is_pickle_issue:
                        if method in ["__getstate__", "__setstate__", "__reduce__"]:
                            score += 5
                        if method == "__init__":
                            score += 2

                    if score > 0:
                        suspicious.append({
                            "class": cls.name,
                            "filepath": cls.filepath,
                            "name": method,
                            "score": score,
                            "class_source": cls.source
                        })

                # Pickle issue: flag if class has NO pickle methods at all
                if is_pickle_issue:
                    has_pickle_method = any(
                        m in cls.methods
                        for m in ["__getstate__", "__setstate__", "__reduce__"]
                    )
                    if not has_pickle_method:
                        suspicious.append({
                            "class": cls.name,
                            "filepath": cls.filepath,
                            "name": "__getstate__ (MISSING)",
                            "score": 10,
                            "class_source": cls.source
                        })

            suspicious.sort(key=lambda x: x["score"], reverse=True)
            return suspicious[:5]