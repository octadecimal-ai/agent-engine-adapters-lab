"""
Memory Bridge — MetaGPT ↔ Engram/Qdrant integration.

Provides two-way memory integration:
- PRE-PIPELINE: Query Qdrant/engram for relevant context to inject into MetaGPT
- POST-PIPELINE: Save MetaGPT results (PRD, Design, Code) to engram

Usage:
    from memory_bridge import MemoryBridge

    bridge = MemoryBridge(scope="dev-innovation-lab")

    # Before pipeline: get relevant context
    context = bridge.query_context("Wiki.js integration")

    # After pipeline: save results
    bridge.save_result(task_id="task-123", title="Wiki.js integration", result="...")
"""

import json
import subprocess
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError


QDRANT_URL = "http://100.112.122.1:6333"
QDRANT_COLLECTIONS = ["global_knowledge", "agent_memory"]


class MemoryBridge:
    """Bridge between MetaGPT and Engram/Qdrant memory systems."""

    def __init__(self, scope: str = "dev-innovation-lab"):
        self.scope = scope
        self._engram_available = self._check_engram()
        self._qdrant_available = self._check_qdrant()

    def _check_engram(self) -> bool:
        try:
            result = subprocess.run(
                ["engram", "stats"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _check_qdrant(self) -> bool:
        try:
            req = Request(f"{QDRANT_URL}/collections", method="GET")
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return data.get("status") == "ok"
        except (URLError, json.JSONDecodeError, OSError):
            return False

    def query_context(self, query: str, limit: int = 5) -> str:
        """Query both engram and Qdrant for relevant context."""
        results = []

        # 1. Search engram
        if self._engram_available:
            engram_results = self._search_engram(query, limit)
            if engram_results:
                results.append("## Relevant memories (engram)\n" + engram_results)

        # 2. Search Qdrant (scroll with filter, since we can't embed the query here)
        if self._qdrant_available:
            qdrant_results = self._search_qdrant_scroll(query, limit)
            if qdrant_results:
                results.append("## Relevant knowledge (Qdrant)\n" + qdrant_results)

        if not results:
            return ""

        return "\n\n".join(results)

    def _search_engram(self, query: str, limit: int) -> str:
        try:
            result = subprocess.run(
                ["engram", "search", query, "--scope", self.scope, "--limit", str(limit)],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout.strip()
            if "No memories found" in output:
                return ""
            return output
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def _search_qdrant_scroll(self, query: str, limit: int) -> str:
        """Scroll Qdrant for points matching query keywords in payload."""
        results = []
        for collection in QDRANT_COLLECTIONS:
            try:
                # Use scroll with payload filter (keyword match)
                payload = json.dumps({
                    "limit": limit,
                    "with_payload": True,
                    "with_vector": False,
                }).encode()
                req = Request(
                    f"{QDRANT_URL}/collections/{collection}/points/scroll",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                resp = urlopen(req, timeout=10)
                data = json.loads(resp.read())

                points = data.get("result", {}).get("points", [])
                query_lower = query.lower()
                for point in points:
                    p = point.get("payload", {})
                    text = p.get("text", p.get("content", p.get("title", "")))
                    if isinstance(text, str) and query_lower.split()[0] in text.lower():
                        title = p.get("title", p.get("source", f"point-{point.get('id', '?')}"))
                        snippet = text[:300].replace("\n", " ")
                        results.append(f"- **{title}**: {snippet}")
            except (URLError, json.JSONDecodeError, OSError):
                continue

        return "\n".join(results) if results else ""

    def save_result(self, task_id: str, title: str, result: str,
                    doc_type: str = "metagpt-output") -> bool:
        """Save MetaGPT pipeline result to engram."""
        if not self._engram_available:
            return False

        # Truncate to reasonable size for engram
        content = result[:4000]

        try:
            subprocess.run(
                [
                    "engram", "save",
                    f"[MetaGPT] {title}",
                    content,
                    "--type", doc_type,
                    "--scope", self.scope,
                ],
                capture_output=True, text=True, timeout=10
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def save_artifacts(self, task_id: str, workspace_dir: str) -> dict:
        """Save key MetaGPT artifacts (PRD, Design) to engram."""
        saved = {}
        workspace = Path(workspace_dir)

        # Save PRD
        for prd_file in workspace.glob("resources/prd/*.md"):
            content = prd_file.read_text()[:4000]
            if self.save_result(task_id, f"PRD: {workspace.name}", content, "prd"):
                saved["prd"] = str(prd_file)

        # Save System Design
        for design_file in workspace.glob("resources/system_design/*.md"):
            content = design_file.read_text()[:4000]
            if self.save_result(task_id, f"Design: {workspace.name}", content, "system-design"):
                saved["design"] = str(design_file)

        return saved

    def status(self) -> dict:
        """Check memory system status."""
        return {
            "engram_available": self._engram_available,
            "qdrant_available": self._qdrant_available,
            "scope": self.scope,
            "qdrant_url": QDRANT_URL,
            "qdrant_collections": QDRANT_COLLECTIONS,
        }
