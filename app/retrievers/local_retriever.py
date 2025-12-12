import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel


class CodeSnippet(BaseModel):
    path: str
    content: str
    url: str
    score: Optional[float] = None
    role: Optional[str] = None  # action, scoring, lookup, boolean, flow, rule


class LogicRetriever:
    """Base abstraction for logic retrieval."""
    async def retrieve_logic_snippets(self, user_query: str, intent: str = "general_query") -> List[CodeSnippet]:
        raise NotImplementedError


class LocalRepoRetriever(LogicRetriever):
    """
    Previous local file system implementation retained for fallback / comparison.
    Searches the bundled sample_code_repo-main directory.
    """
    def __init__(self, repo_path: Optional[str] = None):
        if repo_path is None:
            workspace_root = Path(__file__).parent.parent.parent
            repo_path = workspace_root / "sample_code_repo-main" / "src"
        self.repo_path = Path(repo_path)

        # Static role mapping (domain-specific). Left unchanged intentionally.
        self.role_map = {
            "action": ["cf004_dummy_action.py", "df_action_dummy.py"],
            "scoring": ["cf003_dummy_scoring.py"],
            "finalize": ["cf002_dummy_rules.py"],
            "lookup": ["dummy_lookup_tables.py", "dummy_lookups.py"],
            "boolean": ["booleans_dummy.py"],
            "flow": ["df_main_dummy.py"],
            "rule_set": ["dummy_rule_set.py"],
            "model": ["dummy_model.py"],
        }

    async def retrieve_logic_snippets(self, user_query: str, intent: str = "general_query") -> List[CodeSnippet]:
        print(f"  [Local] Repo Path: {self.repo_path}")
        print(f"  [Local] Query Intent: {intent}")

        snippets: List[CodeSnippet] = []
        priority_roles = self._get_priority_roles(intent, user_query)
        print(f"  [Local] Priority Roles: {priority_roles}")

        for role in priority_roles:
            for filename in self.role_map.get(role, []):
                snippet = self._read_file_by_name(filename, role)
                if snippet:
                    snippets.append(snippet)

        if not snippets:
            print("  [Local] No priority matches, performing keyword search...")
            snippets = self._keyword_search(user_query)

        return snippets[:5]

    def _get_priority_roles(self, intent: str, query: str) -> List[str]:
        query_lower = query.lower()
        roles: List[str] = []
        if intent == "action_justification" or "action" in query_lower:
            roles.append("action")
        if intent == "explain_rule" or "rule" in query_lower or "r00" in query_lower:
            roles.extend(["finalize", "rule_set"])
        if "score" in query_lower or "scoring" in query_lower:
            roles.append("scoring")
        if intent == "check_limit" or "limit" in query_lower or "src" in query_lower:
            roles.append("lookup")
        if "flag" in query_lower or "boolean" in query_lower:
            roles.append("boolean")
        if "flow" in query_lower or "decision" in query_lower:
            roles.append("flow")
        if not roles:
            roles = ["action", "finalize", "scoring", "lookup"]
        return roles

    def _read_file_by_name(self, filename: str, role: str) -> Optional[CodeSnippet]:
        for root, _dirs, files in os.walk(self.repo_path):
            if filename in files:
                filepath = Path(root) / filename
                try:
                    content = filepath.read_text(encoding="utf-8")
                    relative_path = filepath.relative_to(self.repo_path.parent)
                    print(f"    [Local] ✓ Loaded: {relative_path} (role: {role})")
                    return CodeSnippet(
                        path=str(relative_path),
                        content=content[:2000],
                        url=f"file://{filepath}",
                        role=role,
                    )
                except Exception as e:  # pragma: no cover - defensive
                    print(f"    [Local] ✗ Error reading {filename}: {e}")
        return None

    def _keyword_search(self, query: str) -> List[CodeSnippet]:
        keywords = [w.lower() for w in query.split() if len(w) > 3]
        snippets: List[CodeSnippet] = []
        for root, _dirs, files in os.walk(self.repo_path):
            for file in files:
                if file.endswith(".py"):
                    filepath = Path(root) / file
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        content_lower = content.lower()
                        matches = sum(1 for kw in keywords if kw in content_lower)
                        if matches > 0:
                            relative_path = filepath.relative_to(self.repo_path.parent)
                            snippets.append(
                                CodeSnippet(
                                    path=str(relative_path),
                                    content=content[:2000],
                                    url=f"file://{filepath}",
                                    score=float(matches),
                                    role="general",
                                )
                            )
                    except Exception:
                        pass
        snippets.sort(key=lambda x: x.score or 0, reverse=True)
        return snippets
