#!/usr/bin/env python3
"""
CrewAI Engine Adapter

Converts team AGENTS.md into CrewAI Crew configuration and runs tasks.
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
ENGINE_DIR = Path(__file__).resolve().parent
TEAMS_DIR = PROJECT_DIR / "teams"
TASKS_DIR = PROJECT_DIR / ".engine-tasks"
TASKS_DIR.mkdir(exist_ok=True)


def load_engine_config() -> dict:
    """Load engine config from config.json."""
    config_file = ENGINE_DIR / "config.json"
    if config_file.exists():
        return json.loads(config_file.read_text())
    return {}


def load_team_context(team_id: str) -> dict:
    """Load team AGENTS.md and extract role/context for CrewAI agents."""
    team_dir = TEAMS_DIR / team_id
    llm_md = team_dir / "AGENTS.md"

    if not llm_md.exists():
        raise FileNotFoundError(f"Team AGENTS.md not found: {llm_md}")

    content = llm_md.read_text()

    # Extract sections from AGENTS.md
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


def create_crew_config(team_context: dict, task_description: str) -> dict:
    """Convert team context into CrewAI crew configuration."""
    team_id = team_context["team_id"]
    sections = team_context["sections"]

    # Build agent role from AGENTS.md
    role = sections.get("Rola", f"Członek zespołu {team_id}")
    backstory = "\n".join(
        f"## {k}\n{v}" for k, v in sections.items()
        if k not in ("header", "Rola")
    )[:4000]  # Limit backstory size

    return {
        "agents": [
            {
                "role": f"Team Lead - {team_id}",
                "goal": task_description,
                "backstory": f"{role}\n\n{backstory}",
                "verbose": True,
                "allow_delegation": False,
            }
        ],
        "tasks": [
            {
                "description": task_description,
                "expected_output": "Detailed result of the task execution",
                "agent_role": f"Team Lead - {team_id}",
            }
        ],
        "process": "sequential",
        "verbose": True,
    }


def run_task(team_id: str, task_json: str) -> dict:
    """Run a CrewAI task for a team."""
    task_data = json.loads(task_json)
    task_description = task_data.get("prompt", task_data.get("description", task_json))

    task_id = f"task-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}"
    task_file = TASKS_DIR / f"{task_id}.json"

    # Load team context
    team_context = load_team_context(team_id)

    # Create crew config
    crew_config = create_crew_config(team_context, task_description)

    # Record task start
    task_record = {
        "task_id": task_id,
        "team_id": team_id,
        "engine": "crewai",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "prompt": task_description,
        "crew_config": crew_config,
    }
    task_file.write_text(json.dumps(task_record, indent=2))

    try:
        # Import CrewAI (deferred to avoid import errors if not installed)
        from crewai import Agent, Crew, Task, Process, LLM

        # Load engine config for LLM settings
        engine_config = load_engine_config()
        model_config = engine_config.get("model_config", {})
        provider = model_config.get("provider", "llm-provider")
        model = model_config.get("model", "llm-sonnet-4-6")
        temperature = model_config.get("temperature", 0.1)
        max_tokens = model_config.get("max_tokens", 4096)

        llm = LLM(
            model=f"{provider}/{model}",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Create agents
        agents = []
        for agent_config in crew_config["agents"]:
            agent = Agent(
                role=agent_config["role"],
                goal=agent_config["goal"],
                backstory=agent_config["backstory"],
                verbose=agent_config["verbose"],
                allow_delegation=agent_config["allow_delegation"],
                llm=llm,
            )
            agents.append(agent)

        # Create tasks
        tasks = []
        for task_config in crew_config["tasks"]:
            agent = agents[0]  # Single agent for now
            task = Task(
                description=task_config["description"],
                expected_output=task_config["expected_output"],
                agent=agent,
            )
            tasks.append(task)

        # Create and run crew
        process = Process.sequential if crew_config["process"] == "sequential" else Process.hierarchical
        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=process,
            verbose=crew_config["verbose"],
        )

        result = crew.kickoff()

        # Update task record
        task_record["status"] = "completed"
        task_record["ended_at"] = datetime.now(timezone.utc).isoformat()
        task_record["result"] = str(result)
        task_file.write_text(json.dumps(task_record, indent=2, default=str))

        return {"task_id": task_id, "status": "completed", "result": str(result)}

    except ImportError:
        # CrewAI not installed — return config for manual execution
        task_record["status"] = "pending_install"
        task_record["note"] = "CrewAI not installed. Run: pip install -r engines/crewai/requirements.txt"
        task_file.write_text(json.dumps(task_record, indent=2))
        return {
            "task_id": task_id,
            "status": "pending_install",
            "crew_config": crew_config,
            "note": "Install CrewAI to run: pip install -r engines/crewai/requirements.txt",
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
            print("Usage: adapter.py run <team_id> <task_json>", file=sys.stderr)
            sys.exit(1)
        result = run_task(sys.argv[2], sys.argv[3])
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
