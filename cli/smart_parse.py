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

def format_parsed(fmt: str, value, indent: int = 2) -> str:
    """Format a parsed value for human-readable display."""
    if fmt == 'json':
        return json.dumps(value, indent=indent, ensure_ascii=False)
    if fmt == 'csv':
        lines = []
        for row in value:
            lines.append(' | '.join(str(c) for c in row))
        return '\n'.join(lines)
    if fmt == 'yaml':
        try:
            import yaml
            return yaml.dump(value, default_flow_style=False).rstrip()
        except ImportError:
            return str(value)
    if fmt == 'xml':
        return json.dumps(value, indent=indent, ensure_ascii=False)
    return str(value)
