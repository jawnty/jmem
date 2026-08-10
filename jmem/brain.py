"""`jmem brain`: a generated, single-file, read-only HTML view of the
memory store. No server, no mutation surface — the maintainer regenerates
it hourly and `jmem brain --open` opens the latest render.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sqlite3
import subprocess
from pathlib import Path

from jmem import core


KIND_COLORS = {
    "preference": "#2563eb",
    "decision": "#7c3aed",
    "project_fact": "#0d9488",
    "correction": "#dc2626",
    "todo": "#d97706",
    "general": "#6b7280",
}

STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  margin: 0; padding: 2rem 1rem 4rem; background: #fafafa; color: #1a1a2e; }
@media (prefers-color-scheme: dark) {
  body { background: #101014; color: #e8e8ee; }
  .item { background: #1a1a22 !important; border-color: #2a2a35 !important; }
  .meta, .sub { color: #9a9aa8 !important; }
  input#q { background: #1a1a22; color: #e8e8ee; border-color: #2a2a35; }
}
.wrap { max-width: 880px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 0.2rem; }
.sub { color: #667; font-size: 0.85rem; margin-bottom: 1.2rem; }
.statline { font-size: 0.9rem; margin-bottom: 1.5rem; line-height: 1.6; }
.statline b { font-variant-numeric: tabular-nums; }
input#q { width: 100%; padding: 0.6rem 0.8rem; font-size: 1rem;
  border: 1px solid #ccc; border-radius: 8px; margin-bottom: 1.5rem; }
h2 { font-size: 1.05rem; margin: 1.8rem 0 0.6rem; }
h2 .count { color: #888; font-weight: normal; font-size: 0.85rem; }
.item { background: #fff; border: 1px solid #e4e4ea; border-radius: 8px;
  padding: 0.6rem 0.8rem; margin-bottom: 0.5rem; line-height: 1.45; }
.badge { display: inline-block; font-size: 0.7rem; font-weight: 600;
  color: #fff; border-radius: 4px; padding: 0.1rem 0.45rem;
  margin-right: 0.5rem; vertical-align: 1px; }
.meta { color: #778; font-size: 0.78rem; margin-top: 0.25rem;
  font-variant-numeric: tabular-nums; }
.hidden { display: none; }
"""

SCRIPT = """
const q = document.getElementById('q');
q.addEventListener('input', () => {
  const needle = q.value.toLowerCase();
  document.querySelectorAll('.item').forEach(el => {
    el.classList.toggle('hidden', !el.textContent.toLowerCase().includes(needle));
  });
  document.querySelectorAll('section').forEach(sec => {
    const visible = sec.querySelectorAll('.item:not(.hidden)').length;
    sec.classList.toggle('hidden', visible === 0);
    const c = sec.querySelector('.count');
    if (c) c.textContent = '(' + visible + ')';
  });
});
"""


def _scope_label(scope: str) -> str:
    if scope == "global":
        return "Global"
    return scope.removeprefix("project:")


def render_brain_html(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT text, kind, scope, status, confidence, evidence_count, last_seen_at
        FROM memory_items
        WHERE status IN ('soft', 'canon')
        ORDER BY scope, confidence DESC, last_seen_at DESC
        """
    ).fetchall()
    kind_counts: dict[str, int] = {}
    scopes: dict[str, list[sqlite3.Row]] = {}
    fresh_cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    fresh = 0
    for row in rows:
        kind_counts[row["kind"]] = kind_counts.get(row["kind"], 0) + 1
        scopes.setdefault(str(row["scope"]), []).append(row)
        if str(row["last_seen_at"]) >= fresh_cutoff:
            fresh += 1

    grade_rows = conn.execute(
        "SELECT grade, COUNT(*) count FROM injection_grades WHERE kind='injection' GROUP BY grade"
    ).fetchall()
    grades = {r["grade"]: int(r["count"]) for r in grade_rows}
    graded = sum(grades.values())
    precision = (
        f"{100.0 * (grades.get('relevant', 0) + grades.get('partial', 0)) / graded:.0f}%"
        if graded else "n/a"
    )
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>John's Brain — jmem</title>",
        f"<style>{STYLE}</style></head><body><div class='wrap'>",
        "<h1>John's Brain</h1>",
        f"<div class='sub'>Generated {html.escape(generated)} · read-only view of jmem memory_items</div>",
        "<div class='statline'>",
        f"<b>{len(rows)}</b> memories across <b>{len(scopes)}</b> scopes · "
        f"<b>{fresh}</b> added or reinforced this week · "
        f"injection precision <b>{precision}</b> ({graded} graded)<br>",
        " · ".join(
            f"{html.escape(kind)} <b>{count}</b>"
            for kind, count in sorted(kind_counts.items(), key=lambda i: -i[1])
        ),
        "</div>",
        "<input id='q' type='search' placeholder='Search your brain…' autofocus>",
    ]

    ordered = sorted(scopes.items(), key=lambda item: (-len(item[1]), item[0]))
    for scope, items in ordered:
        parts.append("<section>")
        parts.append(
            f"<h2>{html.escape(_scope_label(scope))} "
            f"<span class='count'>({len(items)})</span></h2>"
        )
        for row in items:
            color = KIND_COLORS.get(str(row["kind"]), "#6b7280")
            canon = " ★ canon" if row["status"] == "canon" else ""
            seen = str(row["last_seen_at"])[:10]
            parts.append(
                "<div class='item'>"
                f"<span class='badge' style='background:{color}'>{html.escape(str(row['kind']))}</span>"
                f"{html.escape(str(row['text']))}"
                f"<div class='meta'>confidence {float(row['confidence']):.2f} · "
                f"evidence {row['evidence_count']} · last seen {html.escape(seen)}{canon}</div>"
                "</div>"
            )
        parts.append("</section>")

    parts.append(f"<script>{SCRIPT}</script></div></body></html>")
    return "".join(parts)


def write_brain_view() -> Path:
    conn = core.connect()
    core.init_db(conn)
    html_text = render_brain_html(conn)
    conn.close()
    path = core.ROOT / "brain.html"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(html_text, encoding="utf-8")
    tmp.replace(path)
    return path


def cmd_brain(args: argparse.Namespace) -> int:
    path = write_brain_view()
    print(path)
    if getattr(args, "open", False):
        subprocess.run(["open", str(path)], check=False)
    return 0
