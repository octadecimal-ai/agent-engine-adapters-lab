#!/usr/bin/env python3
"""
MetaGPT Engine Adapter

Converts team AGENTS.md into MetaGPT Role-based agents with SOP workflow.
Uses Langfuse for tracing, engram for persistent memory.

Usage:
    python adapter.py run <team_id> <task_json>
    python adapter.py status <task_id>
    python adapter.py stop <task_id>

Requires: pip install -r requirements.txt
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
TEAMS_DIR = PROJECT_DIR / "teams"
TASKS_DIR = PROJECT_DIR / ".engine-tasks"
TASKS_DIR.mkdir(exist_ok=True)


def load_team_context(team_id: str) -> dict:
    """Load team AGENTS.md and extract sections for MetaGPT roles."""
    team_dir = TEAMS_DIR / team_id
    llm_md = team_dir / "AGENTS.md"

    if not llm_md.exists():
        raise FileNotFoundError(f"Team AGENTS.md not found: {llm_md}")

    content = llm_md.read_text()

    sections = {}
    current_section = "header"
    current_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_content:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip()
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections[current_section] = "\n".join(current_content).strip()

    return {
        "team_id": team_id,
        "team_dir": str(team_dir),
        "llm_md": content,
        "sections": sections,
    }


def create_metagpt_config(team_context: dict, task_description: str) -> dict:
    """Convert team context into MetaGPT role configuration.

    MetaGPT uses SOP (Standard Operating Procedure) with roles:
    - ProductManager: requirement analysis
    - Architect: system design
    - Engineer: implementation
    - QAEngineer: testing/review
    """
    team_id = team_context["team_id"]
    sections = team_context["sections"]

    team_role = sections.get("Rola", f"Członek zespołu {team_id}")
    context_parts = []
    for key, value in sections.items():
        if key not in ("header", "Rola"):
            context_parts.append(f"## {key}\n{value}")
    team_context_str = "\n\n".join(context_parts)[:4000]

    return {
        "company": f"Octadecimal - Team {team_id}",
        "roles": [
            {
                "name": "Analyst",
                "profile": "Requirements Analyst",
                "goal": "Analyze requirements and create clear specifications",
                "constraints": "Stay within the team's domain and expertise",
                "context": f"{team_role}\n\n{team_context_str}",
            },
            {
                "name": "Implementer",
                "profile": "Senior Engineer",
                "goal": "Implement solutions based on specifications",
                "constraints": "Follow CONTRIBUTING.md and team conventions",
                "context": f"{team_role}\n\n{team_context_str}",
            },
            {
                "name": "Reviewer",
                "profile": "QA Engineer",
                "goal": "Review and validate the implementation",
                "constraints": "Ensure quality, security, and completeness",
                "context": f"{team_role}\n\n{team_context_str}",
            },
        ],
        "sop": [
            {"role": "Analyst", "action": "analyze", "input": task_description},
            {"role": "Implementer", "action": "implement", "input": "analysis_result"},
            {"role": "Reviewer", "action": "review", "input": "implementation_result"},
        ],
        "model": "llm-sonnet-4-6",
        "temperature": 0.1,
        "max_rounds": 10,
    }


def build_team_context_str(team_context: dict) -> str:
    """Build a condensed context string from AGENTS.md sections."""
    sections = team_context["sections"]
    team_role = sections.get("Rola", f"Członek zespołu {team_context['team_id']}")
    parts = [f"# Rola zespołu\n{team_role}"]
    for key, value in sections.items():
        if key not in ("header", "Rola"):
            parts.append(f"## {key}\n{value}")
    return "\n\n".join(parts)[:6000]


def run_task(team_id: str, task_json: str, context_aware: bool = False) -> dict:
    """Run a MetaGPT task for a team.

    Args:
        team_id: Team directory name (e.g. 'dev-innovation-lab')
        task_json: JSON string with 'prompt' or 'description' key
        context_aware: If True, use custom team-aware roles instead of
                       built-in MetaGPT SOP roles. Custom roles inject
                       the team's AGENTS.md context into every Action.
    """
    task_data = json.loads(task_json)
    task_description = task_data.get("prompt", task_data.get("description", task_json))

    task_id = f"task-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}"
    task_file = TASKS_DIR / f"{task_id}.json"

    team_context = load_team_context(team_id)
    metagpt_config = create_metagpt_config(team_context, task_description)

    # Memory bridge: query for relevant context
    memory_context = ""
    memory_bridge = None
    try:
        from memory_bridge import MemoryBridge
        memory_bridge = MemoryBridge(scope=team_id)
        memory_context = memory_bridge.query_context(task_description)
        if memory_context:
            task_description = f"{task_description}\n\n---\n# Relevant context from memory:\n{memory_context}"
    except ImportError:
        pass

    task_record = {
        "task_id": task_id,
        "team_id": team_id,
        "engine": "metagpt",
        "mode": "context-aware" if context_aware else "sop-standard",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "prompt": task_description,
        "metagpt_config": metagpt_config,
    }
    task_file.write_text(json.dumps(task_record, indent=2))

    try:
        from metagpt.team import Team
        from metagpt.config2 import Config

        config = Config.default()
        config.llm.model = config.llm.model or metagpt_config["model"]
        config.llm.temperature = metagpt_config["temperature"]

        team = Team()

        if context_aware:
            # Custom team-aware roles with AGENTS.md context
            from team_actions import TeamAnalyst, TeamImplementer, TeamReviewer

            ctx_str = build_team_context_str(team_context)
            team.hire([
                TeamAnalyst(team_context=ctx_str),
                TeamImplementer(team_context=ctx_str),
                TeamReviewer(team_context=ctx_str),
            ])
        else:
            # Standard MetaGPT SOP pipeline
            from metagpt.roles.product_manager import ProductManager
            from metagpt.roles.architect import Architect
            from metagpt.roles.project_manager import ProjectManager
            from metagpt.roles.engineer import Engineer

            team.hire([
                ProductManager(),
                Architect(),
                ProjectManager(),
                Engineer(n_borg=5, use_code_review=True),
            ])

        team.invest(investment=10.0)
        team.run_project(task_description)

        import asyncio
        result = asyncio.run(team.run(n_round=metagpt_config["max_rounds"]))

        if result is None or str(result) == "None":
            task_record["status"] = "failed"
            task_record["ended_at"] = datetime.now(timezone.utc).isoformat()
            task_record["error"] = "MetaGPT returned None — check logs for internal errors"
            task_file.write_text(json.dumps(task_record, indent=2, default=str))
            return {"task_id": task_id, "status": "failed", "error": task_record["error"]}

        task_record["status"] = "completed"
        task_record["ended_at"] = datetime.now(timezone.utc).isoformat()
        task_record["result"] = str(result)

        # Memory bridge: save results
        if memory_bridge:
            try:
                memory_bridge.save_result(
                    task_id=task_id,
                    title=task_description[:100],
                    result=str(result)[:4000],
                )
                task_record["memory_saved"] = True
            except Exception:
                task_record["memory_saved"] = False

        task_file.write_text(json.dumps(task_record, indent=2, default=str))

        return {"task_id": task_id, "status": "completed", "result": str(result)}

    except ImportError as e:
        task_record["status"] = "pending_install"
        task_record["note"] = f"MetaGPT not installed. Run: pip install -r engines/metagpt/requirements.txt ({e})"
        task_file.write_text(json.dumps(task_record, indent=2))
        return {
            "task_id": task_id,
            "status": "pending_install",
            "metagpt_config": metagpt_config,
            "note": task_record["note"],
        }

    except Exception as e:
        task_record["status"] = "failed"
        task_record["ended_at"] = datetime.now(timezone.utc).isoformat()
        task_record["error"] = str(e)
        task_file.write_text(json.dumps(task_record, indent=2))
        return {"task_id": task_id, "status": "failed", "error": str(e)}


def get_status(task_id: str) -> dict:
    """Get task status."""
    task_file = TASKS_DIR / f"{task_id}.json"
    if not task_file.exists():
        return {"error": f"Task not found: {task_id}"}
    return json.loads(task_file.read_text())


def stop_task(task_id: str) -> dict:
    """Stop a running task."""
    task_file = TASKS_DIR / f"{task_id}.json"
    if task_file.exists():
        task_record = json.loads(task_file.read_text())
        task_record["status"] = "stopped"
        task_record["ended_at"] = datetime.now(timezone.utc).isoformat()
        task_file.write_text(json.dumps(task_record, indent=2))
    return {"task_id": task_id, "status": "stopped"}


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: adapter.py run|status|stop <args>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == "run":
        if len(sys.argv) < 4:
            print("Usage: adapter.py run <team_id> <task_json> [--context-aware]", file=sys.stderr)
            sys.exit(1)
        context_aware = "--context-aware" in sys.argv
        result = run_task(sys.argv[2], sys.argv[3], context_aware=context_aware)
        print(json.dumps(result, indent=2))

    elif command == "status":
        if len(sys.argv) < 3:
            print("Usage: adapter.py status <task_id>", file=sys.stderr)
            sys.exit(1)
        result = get_status(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "stop":
        if len(sys.argv) < 3:
            print("Usage: adapter.py stop <task_id>", file=sys.stderr)
            sys.exit(1)
        result = stop_task(sys.argv[2])
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
