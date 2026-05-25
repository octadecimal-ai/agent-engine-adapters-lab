# Agent Engine Adapters Lab

Public, sanitized extract from an internal Octadecimal AI operations repository.

The original work explored a common adapter interface for multiple agent orchestration engines used by development teams. This repository preserves selected Git history for the extracted components while removing private infrastructure details, client data, credentials, production configuration and unrelated operational context.

## What This Shows

- A common adapter interface for agent execution engines.
- Practical comparison points between automation assistant native orchestration, CrewAI, LangGraph and MetaGPT.
- Task lifecycle normalization: run, status, stop.
- Basic task state persistence under `.engine-tasks/`.
- Team-context loading from `teams/<team-id>/AGENTS.md`.
- Optional memory bridge pattern for Engram/Qdrant.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `engine-spec.json` | Shared engine registry and adapter contract. |
| `llm-native/` | Bash adapter for automation assistant style execution. |
| `crewai/` | Python adapter mapping team context to CrewAI. |
| `langgraph/` | Python adapter mapping team context to a LangGraph workflow. |
| `metagpt/` | Python adapter for MetaGPT-style SOP workflows. |
| `teams/demo-team/` | Safe demo team context. |

## Adapter Contract

Each adapter is expected to expose:

```bash
adapter run <team_id> <task_json>
adapter status <task_id>
adapter stop <task_id>
```

Expected output shape:

```json
{
  "task_id": "string",
  "status": "running|completed|failed|stopped",
  "result": {},
  "tokens_used": 0,
  "cost_usd": 0,
  "duration_sec": 0
}
```

## Example

```bash
./llm-native/adapter.sh run demo-team '{"prompt":"Summarize the adapter contract."}'
```

CrewAI, LangGraph and MetaGPT adapters require their Python dependencies from the corresponding `requirements.txt` files and valid model provider configuration.

## Sanitization Notes

This public extract intentionally excludes:

- private client folders and task histories,
- production hostnames, IP addresses and access paths,
- credentials, tokens and secrets,
- copied third-party tool schema bundles not needed for the adapter demonstration,
- unrelated infrastructure and CRM data.

The public repository creation date may be newer than the preserved commits because this is a portfolio-safe extract from internal work.

## Status

Portfolio lab / architecture sample. The code is intentionally compact and should be treated as an adapter design reference, not a drop-in production framework.
