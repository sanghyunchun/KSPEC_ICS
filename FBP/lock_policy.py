import json
from pathlib import Path


DEFAULT_LOCK_PATH = Path(__file__).resolve().parents[1] / 'Lib' / 'fbp_default_locks.json'
AXIS_MAP_PATH = Path(__file__).resolve().parents[1] / 'Lib' / 'positioner_axis_map.json'


def normalize_positioners(positioners, available):
    if isinstance(positioners, str):
        positioners = [item.strip() for item in positioners.split(',') if item.strip()]
    if not isinstance(positioners, list) or any(not isinstance(item, str) for item in positioners):
        raise ValueError('Positioner IDs must be a list of strings.')
    normalized = {item.strip().upper() for item in positioners}
    if '' in normalized:
        raise ValueError('Positioner IDs must not be empty.')
    unknown = normalized - set(available)
    if unknown:
        raise ValueError(f'Unknown positioner IDs: {", ".join(sorted(unknown))}')
    return normalized


def load_default_locks(path=DEFAULT_LOCK_PATH, axis_map_path=AXIS_MAP_PATH):
    with open(axis_map_path, encoding='utf-8') as file:
        available = json.load(file)
    with open(path, encoding='utf-8') as file:
        config = json.load(file)
    if not isinstance(config, dict) or 'positioners' not in config:
        raise ValueError('Default lock file must contain a positioners list.')
    if not isinstance(config['positioners'], list):
        raise ValueError('Default lock positioners must be a list.')
    defaults = normalize_positioners(config['positioners'], available)
    if not defaults:
        raise ValueError('Configure at least one default-locked positioner before FBP motion.')
    return defaults, set(available)
