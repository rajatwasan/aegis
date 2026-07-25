#!/usr/bin/env python3
"""
aegis_selfscore.py — local-only builder-profile analysis for the Aegis repo.

Replicates the client-side layer of YC Paxel (deterministic stats + optional
5-axis LLM scoring) with ZERO reporting to any server.

Modes:
  default        fully offline; no network sockets are opened at all
  --score        one API call to api.anthropic.com using YOUR key
                 (env ANTHROPIC_API_KEY); nothing else leaves the machine

Usage (run from the aegis repo root, or pass --repo):
  python3 aegis_selfscore.py
  python3 aegis_selfscore.py --repo ~/code/aegis --since 90
  ANTHROPIC_API_KEY=sk-ant-... python3 aegis_selfscore.py --score

Output: human-readable report to stdout + aegis_profile.json next to the script.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- discovery

CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude" / "projects"))

# Tool names Paxel canonicalizes; we group them the same way for the mix.
EXPLORE_TOOLS = {"Read", "Grep", "Glob", "LS"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PLAN_TOOLS = {"ExitPlanMode", "EnterPlanMode"}

# Rough steering lexicon: user turns containing these read as course corrections.
STEER_RE = re.compile(
    r"\b(no[,.]|don'?t|stop|instead|actually|wrong|revert|undo|not what|"
    r"wait[,.]|hold on|scrap|redo|wrong file|why did you)\b",
    re.IGNORECASE,
)


def encode_claude_dir(path: str) -> str:
    # Claude Code names project dirs by replacing BOTH "/" and "." with "-".
    return re.sub(r"[/.]", "-", path)


def find_project_dirs(repo_root: Path) -> list[Path]:
    """Match transcript dirs to the repo by encoded path, then by cwd field."""
    matches = []
    if not CLAUDE_DIR.is_dir():
        sys.exit(f"error: {CLAUDE_DIR} not found — is Claude Code installed here?")
    encoded = encode_claude_dir(str(repo_root))
    for d in CLAUDE_DIR.iterdir():
        if not d.is_dir():
            continue
        if d.name == encoded:                      # exact workspace match
            matches.append(d)
            continue
        # Fallback: peek at the first JSONL's cwd (covers worktrees/renames).
        for jf in d.glob("*.jsonl"):
            cwd = first_cwd(jf)
            if cwd and (cwd == str(repo_root) or cwd.startswith(str(repo_root) + "/")):
                matches.append(d)
            break                                   # one file is enough to decide
    return matches


def first_cwd(jsonl: Path) -> str | None:
    try:
        with jsonl.open() as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj.get("cwd"), str):
                    return obj["cwd"]
    except OSError:
        pass
    return None

# ---------------------------------------------------------------- parsing


def parse_session(jsonl: Path, since_epoch: float | None):
    """One pass over a session file → per-session stats dict, or None if filtered."""
    if since_epoch and jsonl.stat().st_mtime < since_epoch:
        return None

    s = {
        "id": jsonl.stem,
        "user_prompts": [],       # real human turns (not tool_results)
        "prompt_lengths": [],
        "tools": Counter(),
        "steer_hits": 0,
        "plan_mode": False,
        "explore_before_edit": 0,  # Read/Grep/Glob calls before first edit
        "first_ts": None,
        "last_ts": None,
        "hours": Counter(),        # local hour-of-day histogram
        "edits": 0,
    }
    seen_edit = False
    with jsonl.open() as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_ts(obj.get("timestamp"))
            if ts:
                s["first_ts"] = min(filter(None, [s["first_ts"], ts]))
                s["last_ts"] = max(filter(None, [s["last_ts"], ts]))
                s["hours"][ts.astimezone().hour] += 1

            msg = obj.get("message") or {}
            content = msg.get("content")
            role = msg.get("role")

            if obj.get("type") == "user" and role == "user":
                text = extract_user_text(content)
                if text:                                   # skip tool_result turns
                    s["user_prompts"].append(text)
                    s["prompt_lengths"].append(len(text))
                    if STEER_RE.search(text):
                        s["steer_hits"] += 1

            if obj.get("type") == "assistant" and isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_use":
                        name = block.get("name", "tool")
                        s["tools"][name] += 1
                        if name in PLAN_TOOLS:
                            s["plan_mode"] = True
                        if name in EDIT_TOOLS:
                            seen_edit = True
                            s["edits"] += 1
                        elif name in EXPLORE_TOOLS and not seen_edit:
                            s["explore_before_edit"] += 1
    return s if s["user_prompts"] or s["tools"] else None


def extract_user_text(content) -> str | None:
    # content is either a plain string or a block list; tool_result-only turns
    # are the agent loop talking to itself, not the human — exclude them.
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
        joined = "\n".join(t for t in texts if t).strip()
        return joined or None
    return None


def parse_ts(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None

# ---------------------------------------------------------------- git layer


def git_stats(repo: Path, since_days: int | None):
    """Author-agnostic velocity from local git only; never touches a remote."""
    args = ["git", "-C", str(repo), "log", "--numstat", "--format=%H|%aI"]
    if since_days:
        args.append(f"--since={since_days} days ago")
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}
    commits, adds, dels, days = 0, 0, 0, set()
    for line in out.splitlines():
        if "|" in line and len(line.split("|")[0]) == 40:
            commits += 1
            days.add(line.split("|")[1][:10])
        else:
            m = re.match(r"^(\d+)\t(\d+)\t", line)
            if m:
                adds += int(m.group(1))
                dels += int(m.group(2))
    return {
        "commits": commits,
        "insertions": adds,
        "deletions": dels,
        "active_days": len(days),
        "churn_ratio": round(dels / adds, 2) if adds else 0,
        "commits_per_active_day": round(commits / len(days), 1) if days else 0,
    }

# ---------------------------------------------------------------- aggregate


def aggregate(sessions: list[dict], git: dict) -> dict:
    tools = Counter()
    hours = Counter()
    prompt_lengths, steer, plans, explore, edits, durations = [], 0, 0, 0, 0, []
    for s in sessions:
        tools.update(s["tools"])
        hours.update(s["hours"])
        prompt_lengths += s["prompt_lengths"]
        steer += s["steer_hits"]
        plans += int(s["plan_mode"])
        explore += s["explore_before_edit"]
        edits += s["edits"]
        if s["first_ts"] and s["last_ts"]:
            durations.append((s["last_ts"] - s["first_ts"]).total_seconds() / 3600)

    total_tools = sum(tools.values()) or 1
    n = len(sessions) or 1
    peak = [h for h, _ in hours.most_common(3)]
    prof = {
        "sessions": len(sessions),
        "total_prompts": len(prompt_lengths),
        "avg_prompt_chars": int(statistics.mean(prompt_lengths)) if prompt_lengths else 0,
        "median_prompt_chars": int(statistics.median(prompt_lengths)) if prompt_lengths else 0,
        "avg_session_hours": round(statistics.mean(durations), 2) if durations else 0,
        "plan_mode_ratio": round(plans / n, 2),
        "explore_to_edit_ratio": round(explore / edits, 2) if edits else float(explore),
        "steering_events": steer,
        "steering_per_session": round(steer / n, 2),
        "tool_mix_pct": {t: round(100 * c / total_tools, 1) for t, c in tools.most_common(8)},
        "peak_hours_local": peak,
        "git": git,
    }
    prof["archetype"] = archetype(prof)
    return prof


def archetype(p: dict) -> str:
    """Heuristic reimplementation — Paxel's real assignment is server-side."""
    late = sum(1 for h in p["peak_hours_local"] if h >= 22 or h <= 4)
    if p["plan_mode_ratio"] >= 0.3 or p["explore_to_edit_ratio"] >= 1.5:
        base = "Architect"
    elif p["git"].get("commits_per_active_day", 0) >= 5:
        base = "Velocity Machine"
    elif p["git"].get("churn_ratio", 1) <= 0.35 and p["steering_per_session"] >= 1:
        base = "Quality Guardian"
    else:
        base = "Balanced Builder"
    return f"{base} (Night Owl)" if late >= 2 else base

# ---------------------------------------------------------------- optional LLM

RUBRIC = """Score this developer's AI-agent usage 1-10 on five axes, JSON only:
execution_leverage (work delegated per unit of human input),
steering (quality/precision of course corrections),
engineering_quality (exploration before edits, low churn, tests),
product_thinking (prompts framed around user/business outcomes),
planning (plan-mode use, upfront decomposition).
Return {"scores": {axis: int}, "evidence": {axis: "one line"}, "growth_edge": "one line"}."""


def llm_score(profile: dict, sessions: list[dict]) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("--score needs ANTHROPIC_API_KEY in the environment")
    # Digest: stats + a bounded sample of first prompts and steering turns.
    # Truncation caps what leaves the machine even in this mode.
    sample = []
    for s in sessions[:15]:
        sample.append({
            "first_prompt": s["user_prompts"][0][:400] if s["user_prompts"] else "",
            "steering": [p[:200] for p in s["user_prompts"] if STEER_RE.search(p)][:3],
            "tools": dict(s["tools"].most_common(5)),
            "plan_mode": s["plan_mode"],
        })
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 800,
        "system": RUBRIC,
        "messages": [{"role": "user", "content": json.dumps(
            {"aggregate": profile, "session_sample": sample})}],
    }).encode()
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    text = "".join(b.get("text", "") for b in resp.get("content", []))
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}

# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="path to the aegis repo root")
    ap.add_argument("--since", type=int, default=None, help="days back (default: all)")
    ap.add_argument("--score", action="store_true",
                    help="run 5-axis LLM scoring via YOUR Anthropic key (opt-in egress)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    since_epoch = time.time() - args.since * 86400 if args.since else None

    dirs = find_project_dirs(repo)
    if not dirs:
        sys.exit(f"error: no Claude Code sessions found for {repo} under {CLAUDE_DIR}")

    sessions = []
    for d in dirs:
        for jf in sorted(d.glob("*.jsonl")):
            if jf.name.startswith("_"):
                continue
            parsed = parse_session(jf, since_epoch)
            if parsed:
                sessions.append(parsed)
    if not sessions:
        sys.exit("error: sessions found but none parseable in the requested window")

    profile = aggregate(sessions, git_stats(repo, args.since))
    if args.score:
        profile["llm_scores"] = llm_score(profile, sessions)

    out = Path(__file__).with_name("aegis_profile.json")
    out.write_text(json.dumps(profile, indent=2, default=str))

    p = profile
    print(f"\nAEGIS BUILDER PROFILE (local-only, nothing uploaded)")
    print(f"  Sessions: {p['sessions']}  Prompts: {p['total_prompts']}  "
          f"Avg prompt: {p['avg_prompt_chars']} chars")
    print(f"  Plan-mode ratio: {p['plan_mode_ratio']}  "
          f"Explore:edit: {p['explore_to_edit_ratio']}  "
          f"Steering/session: {p['steering_per_session']}")
    print(f"  Tool mix: {p['tool_mix_pct']}")
    print(f"  Git: {p['git']}")
    print(f"  Peak hours: {p['peak_hours_local']}")
    print(f"  Archetype (heuristic): {p['archetype']}")
    if "llm_scores" in p:
        print(f"  LLM 5-axis: {json.dumps(p['llm_scores'], indent=2)}")
    print(f"\n  Full JSON: {out}")


if __name__ == "__main__":
    main()