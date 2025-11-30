# logger.py
import re
from datetime import datetime
from rich.console import Console
from rich.markup import escape
from field_meta import FIELD_META

# Shared Console Instance
console = Console()

# --- GLOBAL MASTER SWITCH ---
# Default to False (Silent) so we don't print during import/startup
_LOGGING_ENABLED = False 

def set_logging(enabled):
    """Globally enables or disables all logging output."""
    global _LOGGING_ENABLED
    _LOGGING_ENABLED = enabled

def _timestamp():
    return f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]"

def info(source, message, style="cyan"):
    if not _LOGGING_ENABLED: return
    safe_message = escape(str(message))
    tag_color = f"bold {style}"
    console.print(f"{_timestamp()} [{tag_color}]{source:<10}[/{tag_color}] {safe_message}")

def warn(source, message):
    if not _LOGGING_ENABLED: return
    safe_message = escape(str(message))
    console.print(f"{_timestamp()} [bold yellow]{source:<10}[/bold yellow] {safe_message}")

def error(source, message):
    if not _LOGGING_ENABLED: return
    safe_message = escape(str(message))
    console.print(f"{_timestamp()} [bold red]{source:<10}[/bold red] {safe_message}")

def telemetry(device_name, field, value, is_rtl=True):
    if not _LOGGING_ENABLED: return
    
    meta = FIELD_META.get(field, ("", "none", "", ""))
    unit = meta[0]
    
    display_val = f"{value}"
    if unit:
        display_val += f" {unit}"

    if is_rtl:
        icon = "📡"
        color_dev = "bold deep_sky_blue1"
        color_val = "bold white"
    else:
        icon = "🖥️ "
        color_dev = "dim blue"
        color_val = "dim white"

    safe_dev = escape(str(device_name))

    console.print(
        f"{_timestamp()} {icon} [{color_dev}]{safe_dev:<25}[/{color_dev}] "
        f"| [bold white]{field:<18}[/bold white] : [{color_val}]{display_val}[/{color_val}]"
    )

def raw_json(source, raw_str):
    if not _LOGGING_ENABLED: return
    
    s = raw_str
    s = s.replace('{', '§OB§').replace('}', '§CB§')
    s = s.replace('[', '§LB§').replace(']', '§RB§')
    s = s.replace(',', '§CM§')

    s = re.sub(r'"([^"]+)"\s*:', r'[dim]"[/dim][bold white]\1[/bold white][dim]":[/dim]', s)
    s = re.sub(r'(\[dim\]":\[/dim\]\s*)"([^"]+)"', r'\1[dim]"[/dim][bold cyan]\2[/bold cyan][dim]"[/dim]', s)
    s = re.sub(r'(\[dim\]":\[/dim\]\s*)([0-9.-]+|true|false|null)', r'\1[bold cyan]\2[/bold cyan]', s)

    s = s.replace('§OB§', '[dim]{[/dim]').replace('§CB§', '[dim]}[/dim]')
    s = s.replace('§LB§', '[dim][[/dim]').replace('§RB§', '[dim]][/dim]')
    s = s.replace('§CM§', '[dim],[/dim]')

    console.print(
        f"{_timestamp()} 🐛 [bold deep_sky_blue1]{source:<25}[/bold deep_sky_blue1] "
        f"| [bold cyan]RAW[/bold cyan]                : {s}"
    )