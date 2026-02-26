"""
Smart content parsing — auto-detect and parse drop content.

Supports: JSON, CSV, YAML, XML, and plain text.
Returns typed Python objects:
  - JSON  → dict / list
  - CSV   → list[list[str]]
  - YAML  → dict / list  (only if PyYAML installed)
  - XML   → dict          (stdlib xml.etree)
  - text  → str
"""

import csv
import io
import json


# ── Content-type detection ────────────────────────────────────────────────────

def detect_format(text: str) -> str:
    """
    Guess the format of *text*.
    Returns one of: 'json', 'csv', 'yaml', 'xml', 'text'.
    """
    stripped = text.strip()

    # JSON
    if (stripped.startswith('{') and stripped.endswith('}')) or \
       (stripped.startswith('[') and stripped.endswith(']')):
        try:
            json.loads(stripped)
            return 'json'
        except (json.JSONDecodeError, ValueError):
            pass

    # XML
    if stripped.startswith('<?xml') or stripped.startswith('<'):
        # Quick sanity: must have a matching close tag or be self-closing
        if stripped.endswith('>') and ('</' in stripped or '/>' in stripped):
            return 'xml'

    # CSV — at least 2 rows with consistent comma/tab delimiters
    lines = stripped.splitlines()
    if len(lines) >= 2:
        try:
            dialect = csv.Sniffer().sniff(stripped[:4096])
            # Only accept common delimiters — reject letters/digits the
            # sniffer sometimes picks (e.g. 's' in "import sys").
            if dialect.delimiter in (',', '\t', ';', '|'):
                reader = csv.reader(io.StringIO(stripped), dialect)
                rows = list(reader)
                if len(rows) >= 2 and all(len(r) == len(rows[0]) for r in rows[:10]):
                    return 'csv'
        except csv.Error:
            pass

    # YAML (only if it looks like key: value or list items)
    yaml_ish = any(
        line.lstrip().startswith('- ') or ': ' in line
        for line in lines[:10]
        if line.strip() and not line.strip().startswith('#')
    )
    if yaml_ish and not stripped.startswith('http'):
        try:
            import yaml  # noqa: F811
            result = yaml.safe_load(stripped)
            if isinstance(result, (dict, list)):
                return 'yaml'
        except Exception:
            pass

    return 'text'


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_json(text: str):
    """Parse JSON string → dict or list."""
    return json.loads(text.strip())


def parse_csv(text: str) -> list:
    """Parse CSV string → list of lists."""
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = 'excel'
    reader = csv.reader(io.StringIO(text.strip()), dialect)
    return [row for row in reader]


def parse_yaml(text: str):
    """Parse YAML string → dict or list. Returns text if PyYAML not installed."""
    try:
        import yaml
        return yaml.safe_load(text.strip())
    except ImportError:
        return text
    except Exception:
        return text


def parse_xml(text: str) -> dict:
    """Parse XML string → nested dict (simple conversion)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text.strip())
    return _xml_to_dict(root)


def _xml_to_dict(el) -> dict:
    """Recursively convert an XML element to a dict."""
    result = {}
    if el.attrib:
        result['@attributes'] = dict(el.attrib)
    children = list(el)
    if not children:
        result['#text'] = el.text or ''
        if len(result) == 1 and '#text' in result:
            return result['#text']
        return result
    for child in children:
        child_data = _xml_to_dict(child)
        if child.tag in result:
            existing = result[child.tag]
            if not isinstance(existing, list):
                result[child.tag] = [existing]
            result[child.tag].append(child_data)
        else:
            result[child.tag] = child_data
    if el.text and el.text.strip():
        result['#text'] = el.text.strip()
    return result


# ── Smart parse (auto-detect + parse) ────────────────────────────────────────

def smart_parse(text: str):
    """
    Auto-detect format and parse content.

    Returns (format_name, parsed_value):
      ('json', {...})
      ('csv',  [[...], ...])
      ('yaml', {...})
      ('xml',  {...})
      ('text', 'raw string')
    """
    fmt = detect_format(text)
    try:
        if fmt == 'json':
            return 'json', parse_json(text)
        if fmt == 'csv':
            return 'csv', parse_csv(text)
        if fmt == 'yaml':
            return 'yaml', parse_yaml(text)
        if fmt == 'xml':
            return 'xml', parse_xml(text)
    except Exception:
        return 'text', text
    return 'text', text


# ── Dot-access for nested values ─────────────────────────────────────────────

def dot_access(data, path: str):
    """
    Navigate into nested data with dot-separated path.

    Examples:
      dot_access({'a': {'b': 1}}, 'a.b')  → 1
      dot_access({'items': [{'id': 1}]}, 'items.0.id')  → 1
    """
    parts = path.split('.')
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f'Key not found: {part}')
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                raise KeyError(f'Invalid index: {part}')
        else:
            raise KeyError(f'Cannot navigate into {type(current).__name__} with "{part}"')
    return current


# ── Pretty format for shell display ──────────────────────────────────────────

def _color_available() -> bool:
    """Check if ANSI color is available (uses same logic as cli.format)."""
    try:
        from cli.format import _ansi_on
        return _ansi_on()
    except Exception:
        return False


def _c(code: str, text: str) -> str:
    return f'\033[{code}m{text}\033[0m'


def _color_json(text: str) -> str:
    """Syntax-highlight JSON string with ANSI colors."""
    import re
    # Color keys (cyan), strings (green), numbers (yellow), bools/null (magenta)
    def _replacer(m):
        tok = m.group(0)
        if tok.startswith('"') and m.end() <= len(text):
            # Check if this is a key (followed by colon) or value
            rest = text[m.end():].lstrip()
            if rest.startswith(':'):
                return _c('1;36', tok)   # cyan key
            return _c('0;32', tok)       # green string value
        if tok in ('true', 'false'):
            return _c('1;35', tok)       # magenta bool
        if tok == 'null':
            return _c('2', tok)          # dim null
        # number
        try:
            float(tok)
            return _c('1;33', tok)       # yellow number
        except ValueError:
            return tok
    return re.sub(r'"(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', _replacer, text)


def _color_csv(rows: list) -> str:
    """Format CSV as an aligned table with box-drawing chars and colored header."""
    if not rows:
        return ''
    # Compute column widths
    col_count = max(len(r) for r in rows)
    widths = [0] * col_count
    for row in rows:
        for i, cell in enumerate(row):
            if i < col_count:
                widths[i] = max(widths[i], len(str(cell)))

    def _pad_row(row):
        cells = []
        for i in range(col_count):
            val = str(row[i]) if i < len(row) else ''
            cells.append(val.ljust(widths[i]))
        return cells

    lines = []
    horiz = '─'
    top    = '┌' + '┬'.join(horiz * (w + 2) for w in widths) + '┐'
    mid    = '├' + '┼'.join(horiz * (w + 2) for w in widths) + '┤'
    bottom = '└' + '┴'.join(horiz * (w + 2) for w in widths) + '┘'

    lines.append(top)
    # Header row (bold)
    hdr = _pad_row(rows[0])
    lines.append('│ ' + ' │ '.join(_c('1', c) for c in hdr) + ' │')
    lines.append(mid)
    # Data rows
    for row in rows[1:]:
        cells = _pad_row(row)
        lines.append('│ ' + ' │ '.join(cells) + ' │')
    lines.append(bottom)
    return '\n'.join(lines)


def detect_code_language(text: str, filename: str = ''):
    """
    Detect programming language using pygments.
    Returns lowercase language name (e.g. 'python') or None.
    Uses filename when available (reliable), falls back to guess_lexer.
    """
    try:
        from pygments.lexers import guess_lexer, get_lexer_for_filename, TextLexer
        if filename:
            try:
                lex = get_lexer_for_filename(filename)
                return lex.name.lower()
            except Exception:
                pass
        lex = guess_lexer(text)
        if isinstance(lex, TextLexer):
            return None
        return lex.name.lower()
    except Exception:
        return None


def _color_code(text: str, filename: str = '') -> str:
    """Syntax-highlight code with pygments ANSI output (if available)."""
    try:
        from pygments import highlight as _hl
        from pygments.lexers import guess_lexer, get_lexer_for_filename, TextLexer
        from pygments.formatters import Terminal256Formatter
        lexer = None
        if filename:
            try:
                lexer = get_lexer_for_filename(filename)
            except Exception:
                pass
        if not lexer:
            lexer = guess_lexer(text)
            if isinstance(lexer, TextLexer):
                return text
            # Require reasonable confidence to avoid coloring plain text
            if lexer.analyse_text(text) < 0.15:
                return text
        return _hl(text, lexer, Terminal256Formatter(style='monokai')).rstrip()
    except Exception:
        return text


def format_parsed(fmt: str, value, indent: int = 2, filename: str = '') -> str:
    """Format a parsed value for human-readable display."""
    color = _color_available()

    if fmt == 'json':
        text = json.dumps(value, indent=indent, ensure_ascii=False)
        return _color_json(text) if color else text
    if fmt == 'csv':
        if color:
            return _color_csv(value)
        lines = []
        for row in value:
            lines.append(' | '.join(str(c) for c in row))
        return '\n'.join(lines)
    if fmt == 'yaml':
        try:
            import yaml
            text = yaml.dump(value, default_flow_style=False).rstrip()
            if color:
                import re
                # Color keys (cyan), string values (green)
                text = re.sub(r'^(\s*)([\w.-]+)(:)',
                              lambda m: m.group(1) + _c('1;36', m.group(2)) + m.group(3),
                              text, flags=re.MULTILINE)
            return text
        except ImportError:
            return str(value)
    if fmt == 'xml':
        text = json.dumps(value, indent=indent, ensure_ascii=False)
        return _color_json(text) if color else text
    # Plain text — try pygments code highlighting
    if color:
        return _color_code(str(value), filename)
    return str(value)
