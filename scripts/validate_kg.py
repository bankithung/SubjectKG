#!/usr/bin/env python3
"""Validate the knowledge graph: schema shape, id integrity, DAG-ness, question quality.

Must pass before any KG change is committed (see CLAUDE.md). Exit code 0 = valid.
Uses only the stdlib (structural checks mirror harness/schemas/kg-node.schema.json).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^g([1-9]|1[0-2])\.(num|alg|geo|mea|dat|tri|cal|vec)\.[a-z0-9-]+$")
MICRO_ID_RE = re.compile(r"^g([1-9]|1[0-2])\.(num|alg|geo|mea|dat|tri|cal|vec)\.[a-z0-9-]+\.[a-z0-9-]+$")
MODALITIES = {"visual", "verbal", "worked-example", "manipulative", "interactive-html",
              "video", "story", "game", "practice-drill", "socratic"}
ROUTINES = {"see-think-wonder", "notice-wonder", "think-pair-share", "claim-support-question",
            "what-makes-you-say-that", "three-whys", "connect-extend-challenge", "headlines",
            "step-inside", "i-used-to-think-now-i-think", "convince-me", "always-sometimes-never"}
SKILLS = {"recall", "procedural", "conceptual", "application"}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def check_node(n: dict, spine_ids: set) -> None:
    nid = n.get("id", "<missing id>")
    if not ID_RE.match(nid):
        err(f"{nid}: bad id format")
    if n.get("stub"):
        return  # stubs only need identity
    for field in ("title", "description", "grade", "strand"):
        if not n.get(field) and n.get(field) != 0:
            err(f"{nid}: missing {field}")
    for p in n.get("prerequisites", []):
        if p not in spine_ids:
            err(f"{nid}: prerequisite '{p}' not in spine")
        if p == nid:
            err(f"{nid}: self-prerequisite")
    if len(n.get("learning_outcomes", [])) < 2:
        err(f"{nid}: needs >=2 learning_outcomes")

    mis_ids = set()
    for m in n.get("misconceptions", []):
        mid = m.get("id", "")
        if not re.match(r"^m\d+$", mid):
            err(f"{nid}: bad misconception id '{mid}'")
        if mid in mis_ids:
            err(f"{nid}: duplicate misconception id '{mid}'")
        mis_ids.add(mid)
        for field in ("description", "signal", "remedy"):
            if not m.get(field):
                err(f"{nid}.{mid}: missing {field}")
    if len(mis_ids) < 2:
        err(f"{nid}: needs >=2 misconceptions")

    t = n.get("teaching", {})
    bad_mod = set(t.get("modalities", [])) - MODALITIES
    if bad_mod:
        err(f"{nid}: unknown modalities {sorted(bad_mod)}")
    bad_rt = set(t.get("thinking_routines", [])) - ROUTINES
    if bad_rt:
        err(f"{nid}: unknown thinking routines {sorted(bad_rt)}")

    q_ids = set()
    if len(n.get("questions", [])) < 2:
        err(f"{nid}: needs >=2 questions")
    for q in n.get("questions", []):
        qid = q.get("id", "?")
        if qid in q_ids:
            err(f"{nid}: duplicate question id '{qid}'")
        q_ids.add(qid)
        if q.get("skill") not in SKILLS:
            err(f"{nid}.{qid}: bad skill '{q.get('skill')}'")
        opts = q.get("options", [])
        if len(opts) != 4:
            err(f"{nid}.{qid}: needs exactly 4 options, has {len(opts)}")
        correct = [o for o in opts if o.get("correct")]
        if len(correct) != 1:
            err(f"{nid}.{qid}: needs exactly 1 correct option, has {len(correct)}")
        for i, o in enumerate(opts):
            if o.get("correct"):
                continue
            mc, dg = o.get("misconception"), o.get("diagnosis")
            if not mc and not dg:
                err(f"{nid}.{qid} option {i}: distractor has neither misconception nor diagnosis tag")
            if mc and mc not in mis_ids:
                err(f"{nid}.{qid} option {i}: references unknown misconception '{mc}'")
        if not q.get("explanation"):
            err(f"{nid}.{qid}: missing explanation")


def check_dag(nodes: list) -> None:
    graph = {n["id"]: [p for p in n.get("prerequisites", [])] for n in nodes}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}
    def dfs(u: str, stack: list) -> None:
        color[u] = GREY
        for v in graph.get(u, []):
            if color.get(v) == GREY:
                err(f"prerequisite cycle: {' -> '.join(stack + [u, v])}")
            elif color.get(v) == WHITE:
                dfs(v, stack + [u])
        color[u] = BLACK
    for k in graph:
        if color[k] == WHITE:
            dfs(k, [])
    # prereqs should not point to a HIGHER grade (forward edges are suspicious)
    grade = {n["id"]: n["grade"] for n in nodes}
    for n in nodes:
        for p in n.get("prerequisites", []):
            if p in grade and grade[p] > n["grade"]:
                warn(f"{n['id']} (g{n['grade']}) depends on higher-grade {p} (g{grade[p]})")


def check_micros(nodes: list, spine_ids: set) -> None:
    """Validate per-class micro-skill graphs attached by build_kg.py."""
    all_micro_ids = set()
    for n in nodes:
        for m in n.get("micros", []):
            mid = m.get("id", "<missing>")
            if mid in all_micro_ids:
                err(f"duplicate micro id {mid}")
            all_micro_ids.add(mid)
    mis_by_node = {n["id"]: {mm.get("id") for mm in n.get("misconceptions", [])} for n in nodes}

    for n in nodes:
        for m in n.get("micros", []):
            mid = m.get("id", "<missing>")
            if not MICRO_ID_RE.match(mid):
                err(f"{mid}: bad micro id format")
            if m.get("parent") != n["id"]:
                err(f"{mid}: parent field '{m.get('parent')}' != attached node {n['id']}")
            if not mid.startswith(n["id"] + "."):
                err(f"{mid}: id is not parent id + '.slug'")
            for field in ("title", "description"):
                if not m.get(field):
                    err(f"{mid}: missing {field}")
            if not m.get("outcomes"):
                err(f"{mid}: needs >=1 outcome")
            for p in m.get("prereqs", []):
                if p not in all_micro_ids and p not in spine_ids:
                    err(f"{mid}: prereq '{p}' is neither a micro nor a spine id")
                if p == mid:
                    err(f"{mid}: self-prereq")
            for r in m.get("misconception_refs", []):
                if r not in mis_by_node.get(n["id"], set()):
                    err(f"{mid}: misconception_ref '{r}' not on parent node")
            q = m.get("question")
            if q:
                opts = q.get("options", [])
                if len(opts) != 4:
                    err(f"{mid}: question needs exactly 4 options")
                correct = [o for o in opts if o.get("correct")]
                if len(correct) != 1:
                    err(f"{mid}: question needs exactly 1 correct option")
                for i, o in enumerate(opts):
                    if o.get("correct"):
                        continue
                    if not o.get("misconception") and not o.get("diagnosis"):
                        err(f"{mid}: option {i} untagged distractor")
                    if o.get("misconception") and o["misconception"] not in mis_by_node.get(n["id"], set()):
                        err(f"{mid}: option {i} references unknown parent misconception '{o['misconception']}'")

    # micro-level cycle check (micro->micro edges only)
    graph = {}
    for n in nodes:
        for m in n.get("micros", []):
            graph[m["id"]] = [p for p in m.get("prereqs", []) if p in all_micro_ids]
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}
    def dfs(u, stack):
        color[u] = GREY
        for v in graph.get(u, []):
            if color.get(v) == GREY:
                err(f"micro prereq cycle: {' -> '.join(stack + [u, v])}")
            elif color.get(v) == WHITE:
                dfs(v, stack + [u])
        color[u] = BLACK
    for k in graph:
        if color[k] == WHITE:
            dfs(k, [])


def main() -> int:
    # Always rebuild first so validation never runs against a stale kg/math.json
    # (band/class edits would otherwise be committed "validated" without being checked).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_kg
    if build_kg.main() != 0:
        print("build failed - aborting validation")
        return 1

    spine = json.loads((ROOT / "kg" / "spine.json").read_text())
    spine_ids = {n["id"] for n in spine["nodes"]}
    graph = json.loads((ROOT / "kg" / "math.json").read_text())
    nodes = graph["nodes"]

    seen = set()
    for n in nodes:
        if n["id"] in seen:
            err(f"duplicate node id {n['id']}")
        seen.add(n["id"])
        check_node(n, spine_ids)
    missing = spine_ids - seen
    if missing:
        err(f"spine nodes missing from build: {sorted(missing)}")
    check_dag(nodes)
    check_micros(nodes, spine_ids)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    n_stub = sum(1 for n in nodes if n.get("stub"))
    n_micros = sum(len(n.get("micros", [])) for n in nodes)
    print(f"\n{len(nodes)} nodes ({n_stub} stubs), {n_micros} micro-skills | "
          f"{len(errors)} errors | {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
