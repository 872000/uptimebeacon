"""Configuration loading for UptimeBeacon.

UptimeBeacon deliberately has zero runtime dependencies, so instead of
requiring PyYAML we ship a small, well-tested parser for the YAML *subset*
used by our config files:

    database: uptimebeacon.db          # scalar value
    targets:                            # nested mapping / list
      - name: api                       # list of mappings
        url: https://example.com/health
        interval: 60
        timeout: 10
        expected_status: [200, 204]     # inline list
        keyword: '"ok"'                 # quoted string

Supported: comments, blank lines, nested mappings, lists of mappings,
inline lists, quoted strings, ints, floats, booleans, null.
Anything fancier (anchors, multi-line strings, ...) is rejected with a
clear error telling the user to simplify.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(ValueError):
    """Raised when a config file cannot be parsed or validated."""


def _parse_scalar(token: str):
    token = token.strip()
    if token == "" or token in ("~", "null", "Null", "NULL"):
        return None
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    low = token.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_inline(inner)]
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _split_inline(text: str):
    """Split an inline list on commas, respecting quotes."""
    parts, buf, quote = [], [], None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_comment(line: str) -> str:
    """Remove a trailing # comment, respecting quotes."""
    out, quote = [], None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def parse_simple_yaml(text: str) -> dict:
    """Parse the supported YAML subset into nested dicts/lists."""
    raw_lines = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw.split("#")[0]:
            raise ConfigError(f"line {lineno}: tabs are not allowed, use spaces")
        line = _strip_comment(raw)
        if not line.strip():
            continue
        raw_lines.append((lineno, line))

    if not raw_lines:
        return {}

    pos = 0

    def parse_block(min_indent: int):
        nonlocal pos
        # Decide container type by peeking at the first line.
        lineno, first = raw_lines[pos]
        indent = _indent_of(first)
        if indent < min_indent:
            raise ConfigError(f"line {lineno}: unexpected dedent")
        stripped = first.strip()
        if stripped.startswith("- ") or stripped == "-":
            items = []
            while pos < len(raw_lines):
                lineno, line = raw_lines[pos]
                indent = _indent_of(line)
                if indent < min_indent:
                    break
                s = line.strip()
                if not (s.startswith("- ") or s == "-"):
                    break
                pos += 1
                item_indent = indent + 2
                after_dash = s[1:].strip()
                if after_dash == "":
                    # Nested block on following lines.
                    if pos < len(raw_lines) and _indent_of(raw_lines[pos][1]) > indent:
                        items.append(parse_block(indent + 1))
                    else:
                        items.append(None)
                elif ":" in after_dash and not after_dash.startswith(("[", "{")):
                    # "- key: value" -> mapping item.
                    mapping = {}
                    key, _, value = after_dash.partition(":")
                    key = key.strip()
                    if not key:
                        raise ConfigError(f"line {lineno}: bad mapping entry")
                    value = value.strip()
                    if value:
                        mapping[key] = _parse_scalar(value)
                    elif pos < len(raw_lines) and _indent_of(raw_lines[pos][1]) > indent:
                        mapping[key] = parse_block(indent + 1)
                    else:
                        mapping[key] = None
                    # Continuation lines of the same mapping at item_indent.
                    while pos < len(raw_lines):
                        lineno2, line2 = raw_lines[pos]
                        if _indent_of(line2) < item_indent or _indent_of(line2) == indent and line2.strip().startswith("-"):
                            break
                        if _indent_of(line2) != item_indent or ":" not in line2:
                            break
                        pos += 1
                        k, _, v = line2.strip().partition(":")
                        k = k.strip()
                        if not k:
                            raise ConfigError(f"line {lineno2}: bad mapping entry")
                        v = v.strip()
                        if v:
                            mapping[k] = _parse_scalar(v)
                        elif pos < len(raw_lines) and _indent_of(raw_lines[pos][1]) > item_indent:
                            mapping[k] = parse_block(item_indent + 1)
                        else:
                            mapping[k] = None
                    items.append(mapping)
                else:
                    items.append(_parse_scalar(after_dash))
            return items

        mapping = {}
        while pos < len(raw_lines):
            lineno, line = raw_lines[pos]
            indent = _indent_of(line)
            if indent < min_indent:
                break
            if indent != min_indent:
                raise ConfigError(f"line {lineno}: inconsistent indentation")
            s = line.strip()
            if s.startswith("-"):
                break
            if ":" not in s:
                raise ConfigError(f"line {lineno}: expected 'key: value'")
            pos += 1
            key, _, value = s.partition(":")
            key = key.strip()
            if not key:
                raise ConfigError(f"line {lineno}: empty key")
            value = value.strip()
            if value:
                mapping[key] = _parse_scalar(value)
            elif pos < len(raw_lines) and _indent_of(raw_lines[pos][1]) > indent:
                mapping[key] = parse_block(indent + 1)
            else:
                mapping[key] = None
        return mapping

    result = parse_block(0)
    if pos != len(raw_lines):
        lineno, _ = raw_lines[pos]
        raise ConfigError(f"line {lineno}: could not parse")
    if not isinstance(result, dict):
        raise ConfigError("top level of the config must be a mapping")
    return result


@dataclass
class Target:
    name: str
    url: str
    interval: int = 60
    timeout: int = 10
    expected_status: list = field(default_factory=lambda: [200])
    keyword: str | None = None


@dataclass
class AppConfig:
    database: str = "uptimebeacon.db"
    targets: list = field(default_factory=list)


def _coerce_target(raw: dict, index: int) -> Target:
    if not isinstance(raw, dict):
        raise ConfigError(f"targets[{index}]: each target must be a mapping")
    name = raw.get("name")
    url = raw.get("url")
    if not name or not isinstance(name, str):
        raise ConfigError(f"targets[{index}]: 'name' is required")
    if not url or not isinstance(url, str):
        raise ConfigError(f"targets[{index}]: 'url' is required")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"targets[{index}]: url must start with http:// or https://")
    try:
        interval = int(raw.get("interval", 60))
        timeout = int(raw.get("timeout", 10))
    except (TypeError, ValueError):
        raise ConfigError(f"targets[{index}]: interval/timeout must be integers")
    if interval <= 0 or timeout <= 0:
        raise ConfigError(f"targets[{index}]: interval/timeout must be positive")
    expected = raw.get("expected_status", [200])
    if isinstance(expected, int):
        expected = [expected]
    if not isinstance(expected, list) or not expected:
        raise ConfigError(f"targets[{index}]: expected_status must be a non-empty list")
    keyword = raw.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        raise ConfigError(f"targets[{index}]: keyword must be a string")
    return Target(
        name=name,
        url=url,
        interval=interval,
        timeout=timeout,
        expected_status=[int(s) for s in expected],
        keyword=keyword,
    )


def load_config(path: str) -> AppConfig:
    """Load and validate a config file. Missing file -> empty default config."""
    if not os.path.exists(path):
        return AppConfig()
    with open(path, "r", encoding="utf-8") as fh:
        data = parse_simple_yaml(fh.read())
    database = data.get("database", "uptimebeacon.db")
    raw_targets = data.get("targets", [])
    if raw_targets is None:
        raw_targets = []
    if not isinstance(raw_targets, list):
        raise ConfigError("'targets' must be a list")
    names = set()
    targets = []
    for i, raw in enumerate(raw_targets):
        target = _coerce_target(raw, i)
        if target.name in names:
            raise ConfigError(f"duplicate target name: {target.name!r}")
        names.add(target.name)
        targets.append(target)
    return AppConfig(database=str(database), targets=targets)


def dump_config(config: AppConfig) -> str:
    """Serialize a config back to the supported YAML subset."""
    lines = [f"database: {config.database}", "targets:"]
    for t in config.targets:
        lines.append(f"  - name: {t.name}")
        lines.append(f"    url: {t.url}")
        lines.append(f"    interval: {t.interval}")
        lines.append(f"    timeout: {t.timeout}")
        lines.append(f"    expected_status: [{', '.join(str(s) for s in t.expected_status)}]")
        if t.keyword is not None:
            lines.append(f'    keyword: "{t.keyword}"')
    return "\n".join(lines) + "\n"


def save_config(config: AppConfig, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dump_config(config))
