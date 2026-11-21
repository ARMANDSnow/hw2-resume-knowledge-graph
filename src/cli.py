"""CLI entry points for the pilot and the five-stage pipeline."""
import argparse

from .config import MANIFEST, PROCESSED, read_json, write_json


def extract_rows(manifest):
    from .stage2_extract import extract
    return extract(manifest["documents"], PROCESSED)


def resolve_graph(extraction):
    from . import stage3_coref, stage3_disambiguate
    return stage3_coref.resolve(stage3_disambiguate.resolve(extraction))


def pilot(size):
    from .stage1_collect import collect
    from .pilot_audit import write_audit
    if size != 12:
        raise ValueError("本规格要求试点为 12 份")
    manifest = collect(pilot=True, size=size)
    graph = resolve_graph(extract_rows(manifest))
    write_json(PROCESSED / "pilot_graph.json", graph)
    write_audit(manifest, graph)
    print(PROCESSED / "pilot_audit.md")


def reviewed():
    from .provenance import sha256
    review = read_json(PROCESSED / "pilot_review.json")
    audit = PROCESSED / "pilot_audit.md"
    if (not review.get("approved") or not audit.exists() or
        review.get("audit_sha256") != sha256(audit.read_bytes()) or
        review["cohort_hash"] != read_json(PROCESSED / "pilot_manifest.json")["cohort_hash"]):
        raise RuntimeError("请核对本次试点并运行 pilot-review。")


def execute(stage, focus_ids):
    if stage == 1:
        from .stage1_collect import collect
        reviewed()
        collect()
    elif stage == 2:
        graph = extract_rows(read_json(MANIFEST))
        write_json(PROCESSED / "extractions.json", graph)
    elif stage == 3:
        from .stage3_neo4j import load_graph
        graph = resolve_graph(read_json(PROCESSED / "extractions.json"))
        write_json(PROCESSED / "resolved_kg.json", graph)
        load_graph(graph=graph)
    elif stage == 4:
        from .stage4_rules import run
        run(focus_ids=focus_ids)
    elif stage == 5:
        from .stage5_query import run_stage5
        reports = run_stage5()
        print({k:len(v["strict_matches"]) for k,v in reports.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pilot").add_argument("--size", "--pilot", type=int, default=12)
    review = commands.add_parser("pilot-review")
    review.add_argument("--note", required=True, help="核对试点原文和抽取后的结论")
    for name in ["run-all", *(f"stage{i}" for i in range(1,6))]:
        commands.add_parser(name).add_argument("--focus-ids", nargs=3)
    for name in ["sync-check","stats"]:
        commands.add_parser(name)
    args = parser.parse_args()
    cmd = args.command
    if cmd == "pilot":
        pilot(args.size)
    elif cmd == "pilot-review":
        from .provenance import sha256
        from .pilot_audit import review_ready
        manifest = read_json(PROCESSED / "pilot_manifest.json")
        review_ready(manifest, read_json(PROCESSED / "pilot_graph.json"))
        if not args.note.strip():
            parser.error("请记录抽查结论")
        write_json(PROCESSED / "pilot_review.json", dict(approved=True, note=args.note,
                   cohort_hash=manifest["cohort_hash"], audit_sha256=sha256((PROCESSED / "pilot_audit.md").read_bytes())))
    elif cmd == "stats":
        from .stage3_neo4j import graph_stats
        import json
        print(json.dumps(graph_stats(),ensure_ascii=False,indent=2))
    elif cmd == "sync-check":
        from .stage4_rules import sync_check
        r = sync_check()
        print(len(r["threshold_changes"]), "threshold changes;", sum(x["changed"] for x in r["anchors"]), "changed anchors")
    else:
        for stage in range(1,6) if cmd == "run-all" else [int(cmd[-1])]:
            execute(stage, args.focus_ids)


if __name__ == "__main__":
    main()
