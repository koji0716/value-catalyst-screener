import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "value_screener.sqlite"
DISCLAIMER = "このアプリは投資助言ではありません。投資判断は自己責任であり、最終判断はユーザーが行ってください。"


def ensure_runtime_dirs():
    for rel in [
        "data",
        "data/raw/edinet",
        "data/raw/edgar",
        "data/raw/jquants",
        "data/raw/prices",
        "data/exports",
    ]:
        (PROJECT_ROOT / rel).mkdir(parents=True, exist_ok=True)


def load_env(path=None):
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if not env_path.exists():
        return {}
    loaded = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def get_db_path():
    load_env()
    configured = os.environ.get("DB_PATH")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return DEFAULT_DB_PATH


def parse_scalar(value):
    value = value.strip()
    if value == "":
        return ""
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "none"):
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_simple_yaml(path):
    """Small YAML subset parser used when PyYAML is unavailable."""
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        pass

    root = {}
    stack = [(-1, root)]
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(value)
    return root


def load_presets(path=None):
    preset_path = Path(path) if path else PROJECT_ROOT / "config" / "presets.yaml"
    return load_simple_yaml(preset_path)


def load_settings(path=None):
    settings_path = Path(path) if path else PROJECT_ROOT / "config" / "settings.yaml"
    if not settings_path.exists():
        return {}
    return load_simple_yaml(settings_path)

