"""
REGOG Terminal UI — Rich-powered dashboard with dark theme, red/crimson accents.
"""

from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.live import Live

from scoring.utils import parse_flags

console = Console()

REGOG_BANNER = """\
[bold red]
██████╗ ███████╗ ██████╗  ██████╗  ██████╗
██╔══██╗██╔════╝██╔════╝ ██╔═══██╗██╔════╝
██████╔╝█████╗  ██║  ███╗██║   ██║██║  ███╗
██╔══██╗██╔══╝  ██║   ██║██║   ██║██║   ██║
██║  ██║███████╗╚██████╔╝╚██████╔╝╚██████╔╝
╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝
[/bold red]
[dim]Real Estate Go / No-Go Scanner  |  v1.0[/dim]
"""


def print_banner():
    """Print the REGOG banner."""
    console.print(REGOG_BANNER)


def render_leads_table(properties: list[dict], title: str = "Leads") -> Table:
    """
    Render a table of properties with color-coded tiers.
    
    Tier colors:
    - 🔥 HOT → bold red
    - 🌡 WARM → bold yellow
    - ⚪ NEUTRAL → white
    - ⚠️ RISKY → bold magenta
    - 💀 SKIP → dim gray
    """
    table = Table(
        title=title,
        box=box.HEAVY_HEAD,
        border_style="red",
        header_style="bold red",
        show_lines=True,
        title_style="bold white",
    )

    table.add_column("TIER", width=14)
    table.add_column("SCORE", width=8, justify="right")
    table.add_column("ADDRESS", width=40)
    table.add_column("PRICE", width=14, justify="right")
    table.add_column("VS MEDIAN", width=12, justify="right")
    table.add_column("TYPE", width=14)
    table.add_column("DOM", width=6, justify="right")
    table.add_column("FLAGS", width=30)

    for prop in properties[:50]:  # Limit display
        tier = prop.get("lead_tier", "SKIP")
        score = prop.get("score_total") or 0
        address = prop.get("address") or "N/A"
        price = prop.get("list_price") or 0
        dev = prop.get("price_deviation_pct")
        scan_type = prop.get("scan_type", "?")
        dom = prop.get("days_on_market") or "?"
        flags = _format_flags(prop)

        # Tier styling
        tier_text, tier_icon = _tier_style(tier)

        # Score styling
        score_str = f"{score:.1f}"
        score_style = _score_color(score)

        # Price formatting
        price_str = f"${price:,}" if price else "N/A"

        # Deviation styling
        if dev is not None:
            dev_str = f"{dev:+.1f}%"
            dev_style = "green" if dev < 0 else "red"
        else:
            dev_str = "N/A"
            dev_style = "dim"

        table.add_row(
            tier_text,
            Text(score_str, style=score_style),
            address,
            Text(price_str, style="bold white"),
            Text(dev_str, style=dev_style),
            scan_type.capitalize(),
            str(dom),
            flags,
        )

    return table


def _tier_style(tier: str) -> tuple[Text, str]:
    """Get tier text and icon."""
    # NOTE: DISTRESSED_ prefix no longer in tier (Part 3 fix).
    # Brain classification is now stored separately.
    elif tier == "HOT":
        return Text(f"🔥 {tier}", style="bold red"), "🔥"
    elif tier == "WARM":
        return Text(f"🌡 {tier}", style="bold yellow"), "🌡"
    elif tier == "NEUTRAL":
        return Text(f"⚪ {tier}", style="white"), "⚪"
    elif tier == "RISKY":
        return Text(f"⚠️ {tier}", style="bold magenta"), "⚠️"
    else:
        return Text(f"💀 {tier}", style="dim"), "💀"


def _score_color(score: float) -> str:
    """Color code a score value."""
    if score >= 70:
        return "bold green"
    elif score >= 50:
        return "bold yellow"
    elif score >= 35:
        return "white"
    elif score >= 20:
        return "bold magenta"
    else:
        return "dim"


def _format_flags(prop: dict) -> str:
    """Format red/green flags as a short string."""
    flags = []
    red = parse_flags(prop.get("brain_red_flags"))
    green = parse_flags(prop.get("brain_green_flags"))

    if red:
        flags.append(f"[red]{red[0]}[/red]")
    if green:
        flags.append(f"[green]{green[0]}[/green]")

    brain = prop.get("brain_classification")
    if brain and brain != "standard":
        flags.append(f"[magenta]{brain}[/magenta]")

    return " | ".join(flags[:3]) if flags else "[dim]—[/dim]"


def render_stats_panel(stats: dict) -> Panel:
    """Render a stats summary panel."""
    content = (
        f"[bold white]Properties:[/bold white] {stats.get('total_properties', 0)}\n"
        f"[bold red]🔥 HOT:[/bold red] {stats.get('hot_leads', 0)}  "
        f"[bold yellow]🌡 WARM:[/bold yellow] {stats.get('warm_leads', 0)}\n"
        f"[dim]Sessions:[/dim] {stats.get('scan_sessions', 0)}  "
        f"[dim]Avg Score:[/dim] {stats.get('avg_score', 0)}"
    )
    return Panel(
        content,
        title="[bold red]📊 REGOG Stats[/bold red]",
        border_style="red",
        box=box.ROUNDED,
    )


def render_session_summary(session_id: str, scan_type: str, location: str, count: int, hot_count: int):
    """Print a scan session completion summary."""
    console.print()
    console.print(Panel(
        f"[bold white]Session ID:[/bold white] {session_id}\n"
        f"[bold white]Type:[/bold white] {scan_type.capitalize()}\n"
        f"[bold white]Location:[/bold white] {location}\n"
        f"[bold white]Properties Found:[/bold white] {count}\n"
        f"[bold red]🔥 HOT Leads:[/bold red] {hot_count}",
        title="[bold red]✓ Scan Complete[/bold red]",
        border_style="red",
        box=box.DOUBLE,
    ))


def render_error(message: str):
    """Print an error message."""
    console.print(f"\n[bold red]✗ Error:[/bold red] {message}")


def render_info(message: str):
    """Print an info message."""
    console.print(f"[dim]ℹ[/dim] {message}")


def render_success(message: str):
    """Print a success message."""
    console.print(f"[bold green]✓[/bold green] {message}")


def confirm_action(prompt: str) -> bool:
    """Ask the user for confirmation."""
    result = console.input(f"\n[bold yellow]?[/bold yellow] {prompt} [dim](y/N)[/dim] ")
    return result.lower() in ("y", "yes")
