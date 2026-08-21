/* ---------------------------------------------------------------------
   Hand-curated facts about each tracked tool -- pricing, platform
   support, standout feature, and so on. Deliberately NOT scraped or
   Gemini-generated: this kind of fact changes slowly enough that manual
   upkeep is more reliable than an automated pipeline, and it keeps
   compare.html at zero incremental API cost - every other number on
   that page comes from data this site already collects (signals.json,
   news.json), not a new fetch or LLM call.

   IMPORTANT: pricing and feature claims below reflect a point-in-time
   best effort, not a live, verified source - vendors change pricing and
   plans often. Re-check each row against the vendor's own site before
   treating this as authoritative, and bump "verified" when you do.
   compare.html surfaces that date on-page so it's never presented as
   more current than it is.

   Colors intentionally match TREND_COLORS in index.html/leaderboard.html,
   so a tool's color means the same thing on every page.
--------------------------------------------------------------------- */

const TOOL_PROFILES = {
  "Claude Code": {
    color: "#e8a86a",
    tagline: "The agentic terminal collaborator",
    bestFor: "Developers who want an agent that plans, edits, and runs commands across a whole codebase from the terminal.",
    pricing: "Included with Claude Pro/Max plans, or pay-as-you-go via the API",
    platform: "Terminal (macOS/Linux/WSL), plus VS Code and JetBrains extensions",
    autonomy: "High — multi-file edits, runs shell commands, plans multi-step tasks",
    standout: "Deep codebase awareness without manually selecting files for context",
    watchOut: "Terminal-first workflow has a learning curve if you're used to an IDE-centric flow",
    verified: "2026-08-17",
  },
  "Codex": {
    color: "#85c99e",
    tagline: "OpenAI's cloud + CLI coding agent",
    bestFor: "Teams who want a cloud-sandboxed agent that can work on several tasks in parallel, reviewable as pull requests.",
    pricing: "Included with ChatGPT Plus/Pro/Team plans, or pay-as-you-go via the API",
    platform: "Web/cloud sandbox, CLI, and a VS Code extension",
    autonomy: "High — runs in an isolated cloud sandbox and opens PRs for review",
    standout: "Parallel task execution in the cloud, not tied to any one machine",
    watchOut: "The cloud-sandbox model means less direct, moment-to-moment control than a local agent",
    verified: "2026-08-17",
  },
  "Cursor": {
    color: "#8ab8d6",
    tagline: "The AI-native code editor",
    bestFor: "Developers who want AI woven directly into a full IDE, not bolted onto whatever editor they already use.",
    pricing: "Free tier available; paid plans from roughly $20/month",
    platform: "Standalone editor (a VS Code fork) — macOS, Windows, and Linux",
    autonomy: "Medium-high — an Agent mode for multi-file changes, plus fine-grained manual control",
    standout: "A full IDE experience designed around AI from the ground up, not an add-on",
    watchOut: "Means switching editors entirely if you're attached to your current one",
    verified: "2026-08-17",
  },
  "GitHub Copilot": {
    color: "#9a8f7f",
    tagline: "The ubiquitous in-editor assistant",
    bestFor: "Teams already living in VS Code, JetBrains, or GitHub who want assistance with minimal setup.",
    pricing: "Free tier available; paid plans from roughly $10/month, often bundled via a GitHub org plan",
    platform: "VS Code, JetBrains, Visual Studio, Neovim, and GitHub.com",
    autonomy: "Medium — autocomplete plus a chat/agent mode; less autonomous by default than the others",
    standout: "The broadest editor support and the tightest GitHub integration",
    watchOut: "Less aggressively autonomous out of the box unless you opt into its agent mode",
    verified: "2026-08-17",
  },
  "Windsurf": {
    color: "#6fb8a8",
    tagline: "The other AI-native code editor",
    bestFor: "Developers who want an AI-first IDE with a strong multi-file \"Cascade\" agent flow, as an alternative to Cursor.",
    pricing: "Free tier available; paid plans from roughly $15/month",
    platform: "Standalone editor (a VS Code fork) — macOS, Windows, and Linux",
    autonomy: "Medium-high — an agent mode for multi-file changes, plus manual control",
    standout: "Deep multi-file change tracking (\"Cascade\") designed to keep large edits coherent",
    watchOut: "Smaller plugin/extension ecosystem than more established editors",
    verified: "2026-08-17",
  },
  "Replit Agent": {
    color: "#d97a6c",
    tagline: "Build and ship an app from a prompt, in the browser",
    bestFor: "People who want to go from an idea to a deployed app without setting up a local dev environment at all.",
    pricing: "Usage-based credits on top of Replit's free/paid plans",
    platform: "Browser only — Replit's own hosted platform, no local install",
    autonomy: "High within its sandbox — plans, writes, and deploys an app end to end",
    standout: "Zero local setup - write a prompt and get a running, deployed app",
    watchOut: "Tied to Replit's hosted environment rather than your own codebase/toolchain",
    verified: "2026-08-17",
  },
  "Devin": {
    color: "#a893c9",
    tagline: "The autonomous \"AI software engineer\"",
    bestFor: "Teams wanting to hand off a well-scoped, self-contained ticket for an agent to complete with minimal supervision.",
    pricing: "Seat-based subscription, priced for teams rather than individual hobbyists",
    platform: "Cloud/web platform, integrates with GitHub, Slack, and Linear",
    autonomy: "Very high — designed to work a ticket largely unsupervised and open a PR",
    standout: "Positioned as a full teammate (plans, codes, tests, opens PRs) rather than an in-editor assistant",
    watchOut: "Premium, team-oriented pricing compared to the other tools here; less useful for quick one-off edits",
    verified: "2026-08-17",
  },
  "Lovable": {
    color: "#e0a5c4",
    tagline: "Prompt-to-app builder for non-engineers and engineers alike",
    bestFor: "Designers, founders, and developers who want to go from a description to a working web app UI fast.",
    pricing: "Free tier available; paid plans from roughly $20/month",
    platform: "Browser only — a hosted builder, with the option to export/sync code to GitHub",
    autonomy: "High for scaffolding a new app; more manual for deep, precise logic changes",
    standout: "Strong at fast, good-looking UI generation from a plain-language prompt",
    watchOut: "Better suited to greenfield app scaffolding than intricate changes in a large existing codebase",
    verified: "2026-08-17",
  },
};
