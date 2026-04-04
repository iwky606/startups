---
name: add-skill
description: Create a new Claude Code skill for this project. Use when the user wants to add a new slash command or skill to .claude/skills/.
argument-hint: [skill-name] [description]
---

Create a new project-level skill under `.claude/skills/$ARGUMENTS[0]/SKILL.md`.

Steps:
1. Read `project.md` to understand the project context before deciding what the skill should do.
2. If the user provided a description via arguments, use it. Otherwise, ask the user what this skill should do and when it should be triggered.
3. Create the directory `.claude/skills/$ARGUMENTS[0]/` if it doesn't exist.
4. Write `.claude/skills/$ARGUMENTS[0]/SKILL.md` using this structure:

```
---
name: $ARGUMENTS[0]
description: <one-line description of what it does and when to trigger>
argument-hint: [optional hint]
---

<detailed instructions for Claude to follow when this skill is invoked>
```

Rules to follow:
- `name` must be lowercase, numbers, and hyphens only, max 64 chars.
- `description` must be specific enough that Claude knows when to auto-invoke it; front-load the key use case; max 250 chars.
- The body should be concrete step-by-step instructions, not vague guidance.
- If uncertain about any detail, read the relevant source files first — never guess.
- After writing the file, confirm the path and show the user the final content.
