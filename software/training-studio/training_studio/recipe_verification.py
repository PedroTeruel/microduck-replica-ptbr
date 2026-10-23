"""Checked-in successful local evidence, keyed by stable Studio recipe ID.

Each record may contain verification_state="pipeline", verification_label,
verification_evidence (nonempty list of repository evidence paths), and validation.
An empty mapping deliberately keeps every newly adapted recipe unverified.
"""

RECIPE_VERIFICATION = {}
