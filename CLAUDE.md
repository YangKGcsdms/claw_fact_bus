# Project Rules

## Global Efficiency

- Default to the smallest possible scope.
- Use only the files, errors, code snippets, and paths already provided unless more context is strictly required.
- Do not proactively scan unrelated files, folders, modules, or the whole repository.
- If the current context is enough to solve the task, solve it directly.

### Ask-before-scan rule

- If additional files are required, ask for approval first.
- List the exact files or directories you want to inspect.
- Never say "I'll scan the repo" or "I'll inspect related files" without approval.
- Use this format: "我可以基于当前上下文先给出方案；如果你希望我进一步确认根因，我需要查看：`<file1>`, `<file2>`。要我继续看吗？"

### Response style

- Be concise.
- Do not restate the request.
- Give the conclusion first, then the exact change.
- Avoid multiple options unless tradeoffs matter.
- Do not explain standard patterns unless asked.

### Change scope

- Prefer the minimum viable fix.
- Prefer targeted diffs over large rewrites.
- Do not refactor unrelated code.
- Do not make architecture changes unless explicitly requested.

### Tool usage priority

| Task | Prefer | Avoid |
|------|--------|-------|
| Find code | `Grep` | Reading multiple files |
| File listing | `Glob` | `ls` command |
| Confirm symbol location | `Grep` | Reading entire file |
| Large files (>300 lines) | `Read` with offset+limit | Reading entire file |

### Avoid redundant reads

- Do not re-read files already in context.
- Use CODE REFERENCES (line:file) to cite previously read code.
- Do not read tests/configs unless the task directly requires them.

## Debug Scope Constraints

- Do not inspect adjacent files "just in case".
- Do not open configs, tests, or sibling modules by default.
- Do not do repository-wide tracing without approval.
- If confidence is high from current context, propose the fix directly.
- If confidence is low, ask to inspect exact additional files before expanding scope.

## Implementation Constraints

- Implement the smallest working change first.
- Do not expand scope beyond the requested task.
- Do not add cleanup, refactors, renames, or style changes unless requested.
- Do not touch unrelated files.
- Prefer function-level edits over file rewrites.

## Review Constraints

- Review only the files already changed, shown, or explicitly requested.
- Do not broaden the review to the whole module, package, or repository.
- Do not rewrite the implementation unless asked.
- Do not provide style nitpicks unless they affect correctness.
- Keep review short; report only top risks, omissions, and necessary tests.

## Test Constraints

- Add only the minimum necessary tests for the requested change.
- Do not scan all test files by default.
- Do not build a full test matrix unless requested.
- Do not add redundant snapshot tests.
- Do not over-mock when a simple direct test is enough.

## Safety Guardrails

Before performing any high-risk action, ask for confirmation.

High-risk actions include:
- deleting files
- moving or renaming many files
- large-scale search-and-replace
- changing auth, permissions, billing, payment, or security-sensitive logic
- changing CI/CD, deployment, or environment configuration
- database schema changes or data migrations
- introducing new dependencies with broad impact

### Required behavior

- Explain the exact risky action in one sentence
- List the exact files or areas affected
- Ask for approval before proceeding

### Default alternative

- If possible, provide a low-risk minimal version first.

## High-Cost Model Control

- When planning, keep plans short and concrete.
- Limit plans to at most 5 steps unless explicitly asked for a detailed design.
- When reviewing, report only the most important issues.
- Do not repeat background, requirements, or implementation details unless necessary.
- Do not produce long essays, broad redesigns, or exhaustive option lists by default.

### Preferred output

- concise plan
- exact change
- top risks
- minimum necessary tests
