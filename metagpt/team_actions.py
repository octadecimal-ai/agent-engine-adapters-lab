"""
Custom MetaGPT Actions with team AGENTS.md context injection.

Provides team-aware Actions and Roles that use the team's AGENTS.md
sections (role, rules, tools, services) in their prompts.

Usage:
    from team_actions import TeamAnalyst, TeamImplementer, TeamReviewer
    team = Team()
    team.hire([
        TeamAnalyst(team_context=ctx),
        TeamImplementer(team_context=ctx),
        TeamReviewer(team_context=ctx),
    ])
"""

from metagpt.actions import Action
from metagpt.roles import Role
from metagpt.roles.role import RoleReactMode
from metagpt.schema import Message


# ── Team-Aware Actions ──────────────────────────────────────────────


class AnalyzeWithContext(Action):
    """Analyze requirements using team AGENTS.md context."""

    name: str = "AnalyzeWithContext"
    team_context: str = ""

    async def run(self, with_messages, **kwargs):
        last_msg = with_messages[-1].content if with_messages else "No input"

        prompt = f"""You are a requirements analyst for a specialized team.

## Team Context
{self.team_context}

## Task
Analyze the following requirement and create a clear specification.
Consider the team's role, available tools/services, and constraints.

## Requirement
{last_msg}

## Output Format
Provide your analysis as structured markdown with these sections:
1. **Scope** — what exactly needs to be done
2. **Approach** — how to implement it given the team's capabilities
3. **Dependencies** — what tools/services/APIs from the team context are needed
4. **Risks** — potential issues and mitigations
5. **Acceptance Criteria** — how to verify the result
"""
        response = await self._aask(prompt)
        return response


class ImplementWithContext(Action):
    """Implement solution using team AGENTS.md context."""

    name: str = "ImplementWithContext"
    team_context: str = ""

    async def run(self, with_messages, **kwargs):
        last_msg = with_messages[-1].content if with_messages else "No input"

        prompt = f"""You are a senior engineer for a specialized team.

## Team Context
{self.team_context}

## Task
Based on the analysis below, implement the solution.
Use the team's tools, services, and conventions.

## Analysis
{last_msg}

## Output Format
Provide the implementation as:
1. **Files** — list of files to create/modify with full content
2. **Commands** — any shell commands needed (install, configure, etc.)
3. **Integration Notes** — how this connects to existing team infrastructure
"""
        response = await self._aask(prompt)
        return response


class ReviewWithContext(Action):
    """Review implementation using team AGENTS.md context."""

    name: str = "ReviewWithContext"
    team_context: str = ""

    async def run(self, with_messages, **kwargs):
        last_msg = with_messages[-1].content if with_messages else "No input"

        prompt = f"""You are a QA engineer for a specialized team.

## Team Context
{self.team_context}

## Task
Review the implementation below against the team's standards and constraints.

## Implementation
{last_msg}

## Review Checklist
1. **Correctness** — does it solve the requirement?
2. **Security** — any vulnerabilities? (especially for APIs/services)
3. **Team Standards** — follows CONTRIBUTING.md and team conventions?
4. **Integration** — properly uses team tools/services?
5. **Completeness** — all acceptance criteria met?

## Output Format
Provide:
- **Verdict**: APPROVED / NEEDS_CHANGES
- **Issues**: list of issues found (if any)
- **Suggestions**: improvements (optional)
"""
        response = await self._aask(prompt)
        return response


# ── Team-Aware Roles ────────────────────────────────────────────────


class TeamAnalyst(Role):
    """Requirements Analyst with team AGENTS.md context."""

    name: str = "TeamAnalyst"
    profile: str = "Team Requirements Analyst"
    goal: str = "Analyze requirements within the team's domain and capabilities"
    constraints: str = "Stay within the team's tools and expertise"
    team_context: str = ""

    def __init__(self, team_context: str = "", **kwargs):
        super().__init__(**kwargs)
        self.team_context = team_context
        action = AnalyzeWithContext(team_context=team_context)
        self.set_actions([action])
        from metagpt.actions import UserRequirement
        self._watch([UserRequirement])


class TeamImplementer(Role):
    """Senior Engineer with team AGENTS.md context."""

    name: str = "TeamImplementer"
    profile: str = "Team Senior Engineer"
    goal: str = "Implement solutions using the team's tools and infrastructure"
    constraints: str = "Follow team conventions and use available services"
    team_context: str = ""

    def __init__(self, team_context: str = "", **kwargs):
        super().__init__(**kwargs)
        self.team_context = team_context
        action = ImplementWithContext(team_context=team_context)
        self.set_actions([action])
        self._watch([AnalyzeWithContext])


class TeamReviewer(Role):
    """QA Engineer with team AGENTS.md context."""

    name: str = "TeamReviewer"
    profile: str = "Team QA Engineer"
    goal: str = "Ensure implementation quality and team standard compliance"
    constraints: str = "Validate against team rules and security requirements"
    team_context: str = ""

    def __init__(self, team_context: str = "", **kwargs):
        super().__init__(**kwargs)
        self.team_context = team_context
        action = ReviewWithContext(team_context=team_context)
        self.set_actions([action])
        self._watch([ImplementWithContext])
