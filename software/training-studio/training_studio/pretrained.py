"""Pinned upstream policy inventory; these are references, never runnable jobs."""
import copy
import json
from pathlib import Path


_MODELS = json.loads(Path(__file__).with_name('pretrained_models.json').read_text(encoding='utf-8'))


def pretrained_models():
    return copy.deepcopy(_MODELS)
