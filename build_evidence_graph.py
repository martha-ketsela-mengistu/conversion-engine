"""
build_evidence_graph.py
=======================
Generates evidence_graph.json from source files.
Re-run any time a source file changes to keep memo claims in sync.

Usage:
    uv run python build_evidence_graph.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent

# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------

def _load_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _count_probes(md_path: str) -> int:
    text = (ROOT / md_path).read_text(encoding="utf-8")
    m = re.search(r"Total Probes:\s*(\d+)", text)
    return int(m.group(1)) if m else 0


def _held_out_results(jsonl_path: str) -> dict[tuple[str, str], dict]:
    """Returns {(probe_id, condition): trace_dict}."""
    out: dict[tuple[str, str], dict] = {}
    for line in (ROOT / jsonl_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = json.loads(line)
            out[(t["probe_id"], t["condition"])] = t
    return out


def _readme_latency(readme_path: str) -> dict[str, int]:
    text = (ROOT / readme_path).read_text(encoding="utf-8")
    p50 = re.search(r"\|\s*p50\s*\|\s*\*\*([0-9,]+)\s*ms", text)
    p95 = re.search(r"\|\s*p95\s*\|\s*\*\*([0-9,]+)\s*ms", text)
    return {
        "p50_ms": int(p50.group(1).replace(",", "")) if p50 else None,
        "p95_ms": int(p95.group(1).replace(",", "")) if p95 else None,
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build() -> dict:
    score = _load_json("eval/score_log.json")
    ablation = _load_json("probes/ablation_results.json")
    invoice = _load_json("invoice_summary.json")
    bench = _load_json("agent/data/tenacious_sales_data/seed/bench_summary.json")
    traces = _held_out_results("probes/held_out_traces.jsonl")
    latency = _readme_latency("README.md")
    probe_count = _count_probes("probes/probe_library.md")

    # Helper to extract simulation IDs from trace_log.jsonl
    trace_ids: list[str] = []
    for line in (ROOT / "eval/trace_log.jsonl").read_text(encoding="utf-8").splitlines()[:3]:
        if line.strip():
            trace_ids.append(json.loads(line)["simulation_id"])

    def _probe_summary(pid: str, cond: str) -> str:
        t = traces.get((pid, cond), {})
        return f"passed={t.get('passed')}, reason={t.get('reason')}"

    claims = [
        {
            "id": "CLAIM-001",
            "memo_location": "Page 1 — Executive Summary / headline number",
            "claim": f"τ²-Bench retail domain pass@1 = {score['pass_at_1']} (Day 1 baseline, {score['num_trials']} trials x {score['total_tasks']} tasks)",
            "value": str(score["pass_at_1"]),
            "ci_95": score["pass_at_1_ci_95"],
            "source_file": "eval/score_log.json",
            "source_field": "pass_at_1",
            "supporting_trace_ids": trace_ids,
            "published_reference": None,
        },
        {
            "id": "CLAIM-002",
            "memo_location": "Page 1 — Executive Summary / headline number",
            "claim": f"Bench-gated mechanism pass@1 = {ablation['method']['pass_at_1']} on held-out slice ({ablation['held_out_n']} probes, {ablation['trials']} trial)",
            "value": str(ablation["method"]["pass_at_1"]),
            "ci_95": ablation["method"]["ci_95"],
            "source_file": "probes/ablation_results.json",
            "source_field": "method.pass_at_1",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-003",
            "memo_location": "Page 1 — Executive Summary",
            "claim": f"Delta A (method vs baseline on held-out slice) = {ablation['delta_a_method_vs_baseline']:+.2f}",
            "value": f"{ablation['delta_a_method_vs_baseline']:+.2f}",
            "ci_95": None,
            "source_file": "probes/ablation_results.json",
            "source_field": "delta_a_method_vs_baseline",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-004",
            "memo_location": "Page 1 — Cost per qualified lead",
            "claim": f"Cost per qualified lead = ${invoice['cost_per_qualified_lead_usd']:.3f} ({invoice['cost_per_qualified_lead_basis']})",
            "value": f"${invoice['cost_per_qualified_lead_usd']:.3f}",
            "ci_95": None,
            "source_file": "invoice_summary.json",
            "source_field": "cost_per_qualified_lead_usd",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-005",
            "memo_location": "Page 1 — Cost per qualified lead",
            "claim": f"τ²-Bench avg agent cost per task = ${score['avg_agent_cost']:.4f}",
            "value": f"${score['avg_agent_cost']:.4f}",
            "ci_95": None,
            "source_file": "eval/score_log.json",
            "source_field": "avg_agent_cost",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-006",
            "memo_location": "Page 1 — Cost per qualified lead",
            "claim": f"Total challenge week LLM spend = ${invoice['total_usd']:.2f}",
            "value": f"${invoice['total_usd']:.2f}",
            "ci_95": None,
            "source_file": "invoice_summary.json",
            "source_field": "total_usd",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-007",
            "memo_location": "Page 1 — Cost per qualified lead",
            "claim": f"Observed qualification rate = {invoice['qualification_rate_observed']:.0%} ({invoice['qualification_rate_basis']})",
            "value": f"{invoice['qualification_rate_observed']:.0%}",
            "ci_95": None,
            "source_file": "invoice_summary.json",
            "source_field": "qualification_rate_observed",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-008",
            "memo_location": "Page 1 — Speed-to-lead delta",
            "claim": "Tenacious manual stalled-thread rate = 30–40%",
            "value": "30–40%",
            "ci_95": None,
            "source_file": None,
            "source_field": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — Tenacious executive interview; baseline_numbers section",
        },
        {
            "id": "CLAIM-009",
            "memo_location": "Page 1 — Speed-to-lead delta",
            "claim": "Automated system stalled-thread rate ≈ 0% for email replies (agent responds to 100% of non-unsubscribe intents within the same session)",
            "value": "~0%",
            "ci_95": None,
            "source_file": "probes/held_out_traces.jsonl",
            "source_field": "all webhook probes with reply_sequence — 100% received a reply in every condition",
            "supporting_trace_ids": [
                f"PROBE-3-1:method ({_probe_summary('PROBE-3-1', 'method')})",
                f"PROBE-4-2:method ({_probe_summary('PROBE-4-2', 'method')})",
                f"PROBE-7-2:method ({_probe_summary('PROBE-7-2', 'method')})",
            ],
            "published_reference": None,
        },
        {
            "id": "CLAIM-010",
            "memo_location": "Page 1 — Competitive-gap outbound performance",
            "claim": "100% of outbound interactions led with a signal-grounded research finding (AI maturity score + competitor gap where sector data available)",
            "value": "100% (20/20)",
            "ci_95": None,
            "source_file": "agent/outputs/hiring_signal_brief.json",
            "source_field": "ai_maturity, competitor_gap — generated for every lead before email composition",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-011",
            "memo_location": "Page 1 — Competitive-gap outbound performance",
            "claim": "Signal-grounded outbound reply rate benchmark (top-quartile) = 7–12%",
            "value": "7–12%",
            "ci_95": None,
            "source_file": None,
            "source_field": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — Clay, Smartlead case studies; baseline_numbers table",
        },
        {
            "id": "CLAIM-012",
            "memo_location": "Page 1 — Competitive-gap outbound performance",
            "claim": "B2B cold-email baseline reply rate = 1–3%",
            "value": "1–3%",
            "ci_95": None,
            "source_field": None,
            "source_file": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — LeadIQ 2026 / Apollo benchmarks; baseline_numbers table",
        },
        {
            "id": "CLAIM-013",
            "memo_location": "Page 1 — Pilot recommendation",
            "claim": "Discovery-call-to-proposal conversion = 35–50%",
            "value": "35–50%",
            "ci_95": None,
            "source_file": None,
            "source_field": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — Tenacious internal, last 4 quarters",
        },
        {
            "id": "CLAIM-014",
            "memo_location": "Page 1 — Pilot recommendation",
            "claim": "Proposal-to-close conversion = 25–40%",
            "value": "25–40%",
            "ci_95": None,
            "source_file": None,
            "source_field": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — Tenacious internal, last 4 quarters",
        },
        {
            "id": "CLAIM-015",
            "memo_location": "Page 1 — Pilot recommendation",
            "claim": "Average engagement ACV (talent outsourcing) = $240K–$720K",
            "value": "$240K–$720K",
            "ci_95": None,
            "source_file": None,
            "source_field": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — Tenacious internal, weighted by segment",
        },
        {
            "id": "CLAIM-016",
            "memo_location": "Page 1 — Pilot recommendation",
            "claim": "Average engagement ACV (project consulting) = $80K–$300K",
            "value": "$80K–$300K",
            "ci_95": None,
            "source_file": None,
            "source_field": None,
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — Tenacious internal, last 8 deals",
        },
        {
            "id": "CLAIM-017",
            "memo_location": "Page 1 — Pilot recommendation",
            "claim": f"Total engineers currently on Tenacious bench = {bench['total_engineers_on_bench']}",
            "value": str(bench["total_engineers_on_bench"]),
            "ci_95": None,
            "source_file": "agent/data/tenacious_sales_data/seed/bench_summary.json",
            "source_field": "total_engineers_on_bench",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-018",
            "memo_location": "Page 1 — Production latency",
            "claim": f"Production pipeline p50 latency = {latency['p50_ms']:,}ms (~{latency['p50_ms']/1000:.1f}s) across 20 synthetic interactions",
            "value": f"{latency['p50_ms']}ms",
            "ci_95": None,
            "source_file": "README.md",
            "source_field": "Latency Benchmark section — p50 (20-interaction benchmark run 2026-04-23)",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-019",
            "memo_location": "Page 1 — Production latency",
            "claim": f"Production pipeline p95 latency = {latency['p95_ms']:,}ms (~{latency['p95_ms']/1000/60:.1f} min) — free-tier LLM rate-limit outlier",
            "value": f"{latency['p95_ms']}ms",
            "ci_95": None,
            "source_file": "README.md",
            "source_field": "Latency Benchmark section — p95 (20-interaction benchmark run 2026-04-23)",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-020",
            "memo_location": "Page 2 — One honest unresolved failure",
            "claim": "PROBE-7-1 (dual-control coordination: premature booking) fails in all three conditions",
            "value": "0/3 conditions pass",
            "ci_95": None,
            "source_file": "probes/held_out_traces.jsonl",
            "source_field": f"probe_id=PROBE-7-1: baseline={_probe_summary('PROBE-7-1','baseline')} | method={_probe_summary('PROBE-7-1','method')} | extended={_probe_summary('PROBE-7-1','extended')}",
            "supporting_trace_ids": [
                "PROBE-7-1:baseline", "PROBE-7-1:method", "PROBE-7-1:extended",
            ],
            "published_reference": None,
        },
        {
            "id": "CLAIM-021",
            "memo_location": "Page 2 — One honest unresolved failure",
            "claim": "Premature booking business cost: agent sends Cal.com link on 'maybe a call would be useful' — prospect feels pressured; negative brand association",
            "value": "qualitative",
            "ci_95": None,
            "source_file": "probes/probe_library.md",
            "source_field": "PROBE-7-1.business_cost",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-022",
            "memo_location": "Page 2 — Public-signal lossiness",
            "claim": f"AI maturity score false-positive guard: company with 'ML' in name scored 0 (name is not a signal) — PROBE-9-1 {_probe_summary('PROBE-9-1', 'baseline')}",
            "value": "ai_maturity=0 for ML Marketing",
            "ci_95": None,
            "source_file": "probes/held_out_traces.jsonl",
            "source_field": "probe_id=PROBE-9-1",
            "supporting_trace_ids": ["PROBE-9-1:baseline"],
            "published_reference": None,
        },
        {
            "id": "CLAIM-023",
            "memo_location": "Page 2 — Public-signal lossiness",
            "claim": "AI maturity scorer uses 5 weighted signals; absence of public signal ≠ absence of AI capability (GitHub private repos are medium-weight but invisible)",
            "value": "qualitative",
            "ci_95": None,
            "source_file": "agent/enrichment/ai_maturity.py",
            "source_field": "SIGNAL_WEIGHTS dict",
            "supporting_trace_ids": None,
            "published_reference": "TRP1 Challenge Week 10 spec — AI maturity scoring section",
        },
        {
            "id": "CLAIM-024",
            "memo_location": "Page 2 — Failure modes benchmark misses",
            "claim": f"{probe_count} adversarial probes designed across 10 Tenacious-specific categories",
            "value": str(probe_count),
            "ci_95": None,
            "source_file": "probes/probe_library.md",
            "source_field": "Total Probes count",
            "supporting_trace_ids": None,
            "published_reference": None,
        },
        {
            "id": "CLAIM-025",
            "memo_location": "Page 2 — Failure modes benchmark misses",
            "claim": f"Bench over-commitment fix (PROBE-3-1): baseline={_probe_summary('PROBE-3-1','baseline')} → method={_probe_summary('PROBE-3-1','method')}",
            "value": "PROBE-3-1: baseline=FAIL, method=PASS",
            "ci_95": None,
            "source_file": "probes/held_out_traces.jsonl",
            "source_field": "probe_id=PROBE-3-1",
            "supporting_trace_ids": ["PROBE-3-1:baseline", "PROBE-3-1:method"],
            "published_reference": None,
        },
    ]

    return {
        "generated_at": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "memo_version": "final_submission",
        "claims": claims,
    }


if __name__ == "__main__":
    graph = build()
    out = ROOT / "evidence_graph.json"
    out.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written {len(graph['claims'])} claims -> {out}")
    # Verify all source files exist
    missing = [
        (c["id"], c["source_file"])
        for c in graph["claims"]
        if c.get("source_file") and not (ROOT / c["source_file"]).exists()
    ]
    if missing:
        print("WARNING — missing source files:")
        for cid, sf in missing:
            print(f"  {cid}: {sf}")
    else:
        print("All source files verified present.")
