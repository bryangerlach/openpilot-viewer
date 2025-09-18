import os
from django import template
from pathlib import Path

register = template.Library()

STITCHED_DIR = Path("/data/stitched")

@register.filter
def file_exists_relative_url(path):
    """
    Check if a relative media path exists under /data/stitched.
    Example input: "abcd123/thumbs/fcamera/thumb_1.jpg"
    """
    filepath = STITCHED_DIR / Path(path)
    exists = filepath.exists()
    return exists

@register.filter
def dict_get(d, key):
    """
    Get dictionary value by key in templates.
    Always returns a list (so safe to use in {% for %} loops).
    """
    if isinstance(d, dict):
        val = d.get(key, [])
        # If it's a string (single path), wrap in list
        if isinstance(val, str):
            return [val]
        return val or []
    return []