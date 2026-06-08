"""
HTML Report Generator — generates beautiful dark-themed HTML reports from scan data.
Uses Jinja2 templating with the report.html.j2 template.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_report(
    properties: list[dict],
    session_info: dict,
    output_path: str = "regog_report.html",
) -> str:
    """
    Generate an HTML report from a list of properties and session info.

    Args:
        properties: List of property dicts (from DB query).
        session_info: Dict with session metadata (id, scan_type, search_params, etc.).
        output_path: Path to write the HTML file.

    Returns:
        Path to the generated HTML file.
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html.j2")

    # Sort properties by score descending
    sorted_props = sorted(properties, key=lambda p: p.get("score_total") or 0, reverse=True)

    # Prepare stats
    hot_count = sum(1 for p in sorted_props if p.get("lead_tier") == "HOT")
    warm_count = sum(1 for p in sorted_props if p.get("lead_tier") == "WARM")
    neutral_count = sum(1 for p in sorted_props if p.get("lead_tier") == "NEUTRAL")
    risky_count = sum(1 for p in sorted_props if p.get("lead_tier", "").startswith("RISKY") or p.get("lead_tier") == "DISTRESSED")
    avg_score = (
        round(sum(p.get("score_total") or 0 for p in sorted_props) / len(sorted_props), 1)
        if sorted_props
        else 0
    )

    html = template.render(
        properties=sorted_props,
        session=session_info,
        stats={
            "total": len(sorted_props),
            "hot": hot_count,
            "warm": warm_count,
            "neutral": neutral_count,
            "risky": risky_count,
            "avg_score": avg_score,
        },
        generated_at=datetime.utcnow().isoformat(),
    )

    output_path = Path(output_path)
    output_path.write_text(html)
    return str(output_path.resolve())
