#!/usr/bin/env python3
"""
LangGraph Engine Adapter

Converts team AGENTS.md into a LangGraph StateGraph and runs tasks.
Uses LangChain + LLM provider for LLM calls, Langfuse for tracing.

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

PROJECT_DIR = Path(__file__).resolve().parent.parent
TEAMS_DIR = PROJECT_DIR / "teams"
TASKS_DIR = PROJECT_DIR / ".engine-tasks"
TASKS_DIR.mkdir(exist_ok=True)


def load_team_context(team_id: str) -> dict:
    """Load team AGENTS.md and extract sections for graph nodes."""
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


def create_graph_config(team_context: dict, task_description: str) -> dict:
    """Convert team context into LangGraph configuration."""
    team_id = team_context["team_id"]
    sections = team_context["sections"]

    system_prompt = sections.get("Rola", f"Jesteś członkiem zespołu {team_id}.")

    # Build context from remaining sections
    context_parts = []
    for key, value in sections.items():
        if key not in ("header", "Rola"):
            context_parts.append(f"## {key}\n{value}")
    context = "\n\n".join(context_parts)[:6000]

    return {
        "graph_type": "sequential",
        "nodes": [
            {
                "name": "analyze",
                "type": "llm",
                "system_prompt": f"{system_prompt}\n\nKontekst zespołu:\n{context}",
                "human_prompt": f"Przeanalizuj zadanie i zaplanuj kroki:\n\n{task_description}",
            },
            {
                "name": "execute",
                "type": "llm",
                "system_prompt": f"{system_prompt}\n\nJesteś w fazie wykonania. Na podstawie analizy zrealizuj zadanie.",
                "human_prompt": "Na podstawie powyższej analizy, wykonaj zadanie i zwróć wynik.",
            },
            {
                "name": "review",
                "type": "llm",
                "system_prompt": f"{system_prompt}\n\nJesteś w fazie przeglądu. Sprawdź jakość wyniku.",
                "human_prompt": "Sprawdź wynik wykonania. Czy jest kompletny i poprawny? Jeśli nie, wskaż co poprawić.",
            },
        ],
        "edges": [
            {"from": "analyze", "to": "execute"},
            {"from": "execute", "to": "review"},
        ],
        "model": "llm-sonnet-4-6",
        "temperature": 0.1,
        "max_steps": 25,
    }


def run_task(team_id: str, task_json: str) -> dict:
    """Run a LangGraph task for a team."""
    task_data = json.loads(task_json)
    task_description = task_data.get("prompt", task_data.get("description", task_json))

    task_id = f"task-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}"
    task_file = TASKS_DIR / f"{task_id}.json"

    team_context = load_team_context(team_id)
    graph_config = create_graph_config(team_context, task_description)

    task_record = {
        "task_id": task_id,
        "team_id": team_id,
        "engine": "langgraph",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "prompt": task_description,
        "graph_config": graph_config,
    }
    task_file.write_text(json.dumps(task_record, indent=2))

    try:
        from langchain_llm-provider import ChatLLM provider
        from langgraph.graph import StateGraph, START, END
        from typing import TypedDict, Annotated
        import operator

        class GraphState(TypedDict):
            messages: Annotated[list, operator.add]
            analysis: str
            result: str
            review: str

        llm = ChatLLM provider(
            model=graph_config["model"],
            temperature=graph_config["temperature"],
        )

        def analyze_node(state: GraphState) -> dict:
            node_cfg = graph_config["nodes"][0]
            response = llm.invoke([
                {"role": "system", "content": node_cfg["system_prompt"]},
                {"role": "human", "content": node_cfg["human_prompt"]},
            ])
            return {"analysis": response.content, "messages": [response]}

        def execute_node(state: GraphState) -> dict:
            node_cfg = graph_config["nodes"][1]
            analysis = state.get("analysis", "")
            response = llm.invoke([
                {"role": "system", "content": node_cfg["system_prompt"]},
                {"role": "human", "content": f"Analiza:\n{analysis}\n\n{node_cfg['human_prompt']}"},
            ])
            return {"result": response.content, "messages": [response]}

        def review_node(state: GraphState) -> dict:
            node_cfg = graph_config["nodes"][2]
            result = state.get("result", "")
            response = llm.invoke([
                {"role": "system", "content": node_cfg["system_prompt"]},
                {"role": "human", "content": f"Wynik do przeglądu:\n{result}\n\n{node_cfg['human_prompt']}"},
            ])
            return {"review": response.content, "messages": [response]}

        # Build graph
        graph = StateGraph(GraphState)
        graph.add_node("analyze", analyze_node)
        graph.add_node("execute", execute_node)
        graph.add_node("review", review_node)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "execute")
        graph.add_edge("execute", "review")
        graph.add_edge("review", END)

        app = graph.compile()
        final_state = app.invoke({"messages": [], "analysis": "", "result": "", "review": ""})

        task_record["status"] = "completed"
        task_record["ended_at"] = datetime.now(timezone.utc).isoformat()
        task_record["result"] = {
            "analysis": final_state.get("analysis", ""),
            "result": final_state.get("result", ""),
            "review": final_state.get("review", ""),
        }
        task_file.write_text(json.dumps(task_record, indent=2, default=str))

        return {"task_id": task_id, "status": "completed", "result": task_record["result"]}

    except ImportError:
        task_record["status"] = "pending_install"
        task_record["note"] = "LangGraph not installed. Run: pip install -r engines/langgraph/requirements.txt"
        task_file.write_text(json.dumps(task_record, indent=2))
        return {
            "task_id": task_id,
            "status": "pending_install",
            "graph_config": graph_config,
            "note": "Install LangGraph to run: pip install -r engines/langgraph/requirements.txt",
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
