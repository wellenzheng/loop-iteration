---
name: loop-engineering
description: The development doctrine for the loop-iteration project. Use this whenever you build, modify, plan, debug, or scaffold anything in this project — even small changes — because this project is built loop-first: work is designed as autonomous loops (automations + worktrees + skills + connectors + sub-agents + on-disk state) rather than as one-shot prompts. Trigger broadly for any development work here, including "add X", "fix Y", "set up Z", planning a feature, writing tooling, or deciding how to structure the work.
---

# Loop Engineering

> Build the loop. Stay the engineer.

This project is developed **loop-first**. The core idea, from Addy Osmani's *Loop Engineering*: you don't get good at prompting the agent — you get good at designing the **system that prompts the agent for you**. A loop is a recursive goal: you define a purpose and a verifiable stopping condition, and the system iterates toward it, off the clock, while you stay in command.

This is not dogma. Directly prompting an agent is still effective and often the right call. Loop engineering is the **leverage point** for work that is recurring, parallel, long-running, or that you'd rather not babysit. Use it where it pays; don't bolt it onto a five-minute task.

The real job is judgment: *when* to loop, *how* to verify, and *whether* you're still the engineer or just pressing "go".

## The five building blocks + state

A loop is five primitives plus one place to remember things. Every block has a concrete handle in this environment.

### 1. Automations — the heartbeat
The thing that turns a one-off run into an actual loop. A scheduled task does discovery and triage on its own and brings findings to you; runs that find nothing archive themselves.
- **`/loop`** — re-run a prompt or command on a cadence (polling, recurring checks).
- **Run-until-done** — keep iterating until a verifiable condition holds, with a *separate reviewer* judging the stop condition (here: `ralph` / `autopilot` modes). This is the maker/checker split applied to "are we done" — the agent that did the work is not the one grading it.
- **Cron** and **hooks** (lifecycle points in `settings.json`) push autonomous work onto its own clock; **GitHub Actions** is the only thing that survives after the laptop closes.

Why it matters: automation surfaces the work so you're not the one wandering around checking. Recurring grunt work (issue triage, CI-failure summaries, commit briefings, bug hunting) belongs in an automation that calls a **skill** — so the recurring thing stays maintainable: `$skill-name` instead of a wall of instructions nobody ever updates.

### 2. Worktrees — parallel without collision
The instant you run more than one agent, file collisions become the failure mode — two agents writing the same file is exactly two engineers stepping on each other's lines. A git worktree is a separate working directory on its own branch sharing the same repo history; one agent's edits literally cannot touch another's checkout.
- **`git worktree`** and the **`EnterWorktree`** tool to open a session in its own checkout.
- **`isolation: worktree`** on a subagent so each helper gets a fresh, self-cleaning checkout.

Why it matters: worktrees remove the *mechanical* collision. But YOU are still the ceiling — your review bandwidth decides how many parallel agents you can actually run, not the tool.

### 3. Skills — stop re-explaining your project
A skill is how you stop re-explaining the same project context every session like a goldfish. It's intent written down on the outside — the conventions, build steps, the "we don't do it like this because of that one incident" — written once, read every run. Without skills, the loop re-derives your project from zero every cycle; with them, knowledge compounds.
- Format: a folder with `SKILL.md` (this very file) plus optional `scripts/`, `references/`, `assets/`. A tight, boring description beats a clever one, because the description is what triggers it.

Why it matters *here*: **this project eats its own dog food.** Whenever a convention, gotcha, or repeated explanation crystallizes during development, capture it as a skill under `.claude/skills/` so the next loop doesn't pay for it again.

### 4. Connectors / MCP — act, don't just report
A loop that only sees the filesystem is a tiny loop. Connectors (MCP) let the agent read your issue tracker, query a database, hit a staging API, drop a message in Slack, open a PR. This is the difference between "here's the fix" and a loop that opens the PR, links the ticket, and pings the channel once CI is green — by itself.

Why it matters: connectors let the loop act *inside your real environment* instead of describing what it would do if it could. Prefer loops that close the loop end-to-end over loops that produce a to-do list for you.

### 5. Sub-agents — keep the maker away from the checker
The single most useful structural idea in a loop. The model that wrote the code is far too nice grading its own homework; a second agent with different instructions (and sometimes a different model, or higher reasoning effort) catches what the first talked itself into.
- Define subagents and split roles — typically **one explores, one implements, one verifies against the spec**.
- Spend subagents where a second opinion is worth paying for: each one does its own model and tool work, so they cost tokens.

Why it matters: a loop runs while you aren't watching, so a verifier you actually trust is the only reason you can walk away.

### + State / memory — the spine
A markdown file (or a board) that lives **on disk, not in context**, and remembers what's done, what's tried, and what's next. Sounds too dumb to matter; it's the same trick every long-running agent depends on. The model forgets between runs — the repo doesn't.

**Convention for this project:** keep state at `.loop/progress.md` (create it if it doesn't exist — or change the path if the team prefers, but pick *one* and stick to it). Record: what's done, what's in flight, what's blocked, what's next. Every meaningful loop writes to it; every new run reads it first to pick up where the last one stopped.

## What the loop will not do for you

Three problems get **sharper**, not easier, as the loop gets better. Watch them.

- **Verification is still on you.** A loop running unattended is also a loop making mistakes unattended. "Done" is a claim, not a proof. Splitting the verifier sub-agent from the maker is what makes the loop's "it's done" mean something — and even then, **ship code you confirmed works.** Prefer run-until-done with a verifiable condition ("all tests in X pass and lint is clean") over a vibe-check.
- **Your understanding rots.** The faster the loop ships code you didn't write, the bigger the gap between what exists and what you understand — *comprehension debt*. A smooth loop grows it faster unless you **read what the loop made.** When a sub-agent lands a change, read it before you trust it.
- **The comfortable posture is the dangerous one.** When the loop runs itself it's tempting to stop having an opinion and take whatever it hands back — *cognitive surrender*. Designing the loop is the cure when you do it with judgment, and the accelerant when you do it to avoid thinking. Same action, opposite result. **Keep an opinion.** Two people can run the same loop and get opposite outcomes; the loop doesn't know the difference — you do.

## Pre-flight checklist — run this before any dev work in this project

Before writing or changing code here, walk through these and answer them out loud. Most tasks need only a few; the point is to decide *deliberately*, not to ritualize every item.

1. **Goal & stopping condition** — What does "done" look like, and is it *verifiable* (a test, a lint pass, a command exit code)? Write it down. This is what a run-until-done reviewer — or you, later — will grade against.
2. **One-shot or loop?** Is this a five-minute task I should just do, or recurring / parallel / long-running work that earns a loop? Don't over-loop.
3. **What knowledge should become a skill?** Is a convention, gotcha, or repeated explanation emerging here? Capture it in `.claude/skills/` before it becomes intent debt.
4. **Parallel?** If two agents or two features run at once → **worktree isolation** so they don't collide.
5. **Maker and checker** — Who writes it and who verifies it? If it matters, use a separate sub-agent to verify against the spec and tests, not the same one that wrote it.
6. **Where does state live?** Update `.loop/progress.md` (or the agreed board) so the next run picks up. State on disk, not in context.
7. **Can the loop act, or just report?** If it should open a PR / update a ticket / notify, wire the connector instead of handing me a checklist.
8. **How do I stay the engineer?** What will I read, run, or verify myself before I trust this? Name the verification step explicitly.

## What one loop looks like

The canonical shape, made concrete — adapt the cadence and tools to the task:

1. An **automation** (`/loop` or cron) fires on a cadence and calls a **triage skill**.
2. Triage reads yesterday's CI failures, open issues, recent commits → writes findings into **state** (`.loop/progress.md` or a board).
3. For each finding worth doing: open a **worktree** → a **sub-agent** drafts the fix → a second **sub-agent** reviews it against the project skills and tests.
4. **Connectors** open the PR and update the ticket. Anything the loop can't handle lands in a triage inbox.
5. **State** remembers what was tried, what passed, what's open — so the next run picks up where this one stopped.

Notice what you did *not* do: you did not prompt any of those steps. You designed the loop once. That's the whole point.

## Stay the engineer

This project's leverage is loop design, not prompt writing. But the leverage only pays out if you keep your hands on it:

- Loop to move faster on work you **understand deeply**, not to avoid understanding it at all.
- Read the diffs. Run the tests. Confirm it works before you call it done.
- Prompting the agent directly is still effective and often right — balance is the skill, not maximal looping.

Two engineers can build the identical loop and get opposite results. The loop doesn't know the difference. **You do.**
