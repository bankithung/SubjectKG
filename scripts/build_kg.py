#!/usr/bin/env python3
"""Build kg/math.json and viewer/kg-data.js from kg/spine.json + kg/bands/*.json
+ kg/classes/class-NN.json (per-class in-depth micro-skill graphs).

The spine is the source of truth for which macro nodes exist; band files carry the
macro content; class files carry the micro-skills that are attached to each macro node
under "micros" (array order = recommended teaching order). Nodes present in the spine
but missing from every band are included as stubs (flagged "stub": true) so the viewer
and tutor can still see them.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    spine = json.loads((ROOT / "kg" / "spine.json").read_text())
    spine_ids = [n["id"] for n in spine["nodes"]]
    spine_by_id = {n["id"]: n for n in spine["nodes"]}

    detailed = {}
    for band_file in sorted((ROOT / "kg" / "bands").glob("*.json")):
        band = json.loads(band_file.read_text())
        for node in band.get("nodes", []):
            if node["id"] in detailed:
                print(f"WARN: {node['id']} defined in two band files; keeping first", file=sys.stderr)
                continue
            detailed[node["id"]] = node

    nodes = []
    stubs = 0
    for nid in spine_ids:
        if nid in detailed:
            nodes.append(detailed[nid])
        else:
            stub = dict(spine_by_id[nid])
            stub.update({"stub": True, "prerequisites": [], "misconceptions": [], "questions": []})
            nodes.append(stub)
            stubs += 1

    extras = sorted(set(detailed) - set(spine_ids))
    if extras:
        print(f"WARN: band nodes not in spine (ignored): {extras}", file=sys.stderr)

    # attach per-class micro-skill graphs
    micros_by_parent: dict[str, list] = {}
    classes_dir = ROOT / "kg" / "classes"
    n_micros = 0
    if classes_dir.exists():
        for cf in sorted(classes_dir.glob("class-*.json")):
            cls = json.loads(cf.read_text())
            for m in cls.get("micros", []):
                parent = m.get("parent")
                if not parent:
                    print(f"WARN: micro without parent in {cf.name}: {m.get('id')}", file=sys.stderr)
                    continue
                micros_by_parent.setdefault(parent, []).append(m)
                n_micros += 1
    for node in nodes:
        if node["id"] in micros_by_parent:
            node["micros"] = micros_by_parent[node["id"]]
    orphan_parents = sorted(set(micros_by_parent) - {n["id"] for n in nodes})
    if orphan_parents:
        print(f"WARN: micros whose parent is not a spine node (ignored): {orphan_parents}",
              file=sys.stderr)

    # centrality: how many nodes (transitively) depend on this one - used by
    # /assess entry probe ordering and /plan milestone picking
    def _pid(p):
        return p if isinstance(p, str) else p["id"]
    dependents: dict[str, set] = {n["id"]: set() for n in nodes}
    children: dict[str, list] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for p in n.get("prerequisites", []):
            if _pid(p) in children:
                children[_pid(p)].append(n["id"])
    def collect(nid: str) -> set:
        if dependents[nid]:
            return dependents[nid]
        out = set()
        for c in children[nid]:
            out.add(c)
            out |= collect(c)
        dependents[nid] = out
        return out
    for n in nodes:
        n["centrality"] = len(collect(n["id"]))

    graph = {
        "version": spine["version"],
        "subject": spine["subject"],
        "strands": spine["strands"],
        "built_from": {"spine": "kg/spine.json", "bands": "kg/bands/*.json"},
        "nodes": nodes,
    }
    out = ROOT / "kg" / "math.json"
    out.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n")

    # Compact payload for the self-contained viewer (no questions - keeps the file small
    # and keeps answer keys out of student-facing pages).
    viewer_nodes = []
    for n in nodes:
        viewer_nodes.append({
            "id": n["id"],
            "title": n["title"],
            "grade": n["grade"],
            "strand": n["strand"],
            "description": n.get("description", ""),
            "prereqs": n.get("prerequisites", []),
            "outcomes": n.get("learning_outcomes", []),
            "difficulty": n.get("difficulty", 0),
            "est_minutes": n.get("est_minutes", 0),
            "centrality": n.get("centrality", 0),
            "stub": n.get("stub", False),
            "micros": [{
                "id": m["id"], "parent": m["parent"], "title": m["title"],
                "description": m.get("description", ""),
                "outcomes": m.get("outcomes", []), "prereqs": m.get("prereqs", []),
                "est_minutes": m.get("est_minutes", 0), "difficulty": m.get("difficulty", 0),
                "question": bool(m.get("question")),
            } for m in n.get("micros", [])],
        })
    payload = {"strands": spine["strands"],
               "strand_summaries": spine.get("strand_summaries", {}),
               "nodes": viewer_nodes}
    js = "// Generated by scripts/build_kg.py - do not edit by hand\nwindow.KG_DATA = " \
        + json.dumps(payload, ensure_ascii=False) + ";\n"
    (ROOT / "viewer" / "kg-data.js").write_text(js)

    n_micro_q = sum(1 for n in nodes for m in n.get("micros", []) if m.get("question"))
    n_macro_q = sum(len(n.get("questions", [])) for n in nodes)
    print(f"Built kg/math.json: {len(nodes)} nodes ({stubs} stubs), {n_micros} micro-skills, "
          f"{n_macro_q}+{n_micro_q}={n_macro_q + n_micro_q} questions, "
          f"{sum(len(n.get('misconceptions', [])) for n in nodes)} misconceptions")
    print("Built viewer/kg-data.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
