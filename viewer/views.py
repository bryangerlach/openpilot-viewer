import os
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from django.shortcuts import render, redirect
from django.core.paginator import Paginator

DEFAULT_OLD_DATE = datetime(1900, 1, 1)

STITCHED_DIR = Path("/data/stitched")  # Mounted in Docker
RAW_DIR = Path("/data/raw")

SEGMENT_RE = re.compile(r"^(.*?)(--\d+)?$")

CAMERA_LABELS = {
    "fcamera.mp4": "Front Camera",
    "ecamera.mp4": "Wide Camera",
    "dcamera.mp4": "Driver Camera",
}

METADATA_DIR = Path("/data/metadata")
METADATA_DIR.mkdir(exist_ok=True)
PRESERVED_FILE = METADATA_DIR / "preserved_routes.json"


# ----------------------
# Helpers
# ----------------------

def normalize_route_id(name: str) -> str:
    """Remove --N suffix from segment folder names."""
    match = SEGMENT_RE.match(name)
    return match.group(1) if match else name


def load_preserved_routes():
    if PRESERVED_FILE.exists():
        with open(PRESERVED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_preserved_routes(preserved_set):
    with open(PRESERVED_FILE, "w") as f:
        json.dump(list(preserved_set), f)


# ----------------------
# Views
# ----------------------

def toggle_preserve(request, route_id):
    preserved = load_preserved_routes()
    if route_id in preserved:
        preserved.remove(route_id)
    else:
        preserved.add(route_id)
    save_preserved_routes(preserved)
    return redirect(request.META.get("HTTP_REFERER", "/"))


def drive_list(request):
    """List all drives (logs-only or stitched). Limit to 20 per page."""
    drives = []
    cameras = ["fcamera", "ecamera", "dcamera"]
    thumb_indices = [1, 2, 3]

    preserved_routes = load_preserved_routes()
    show_preserved_only = request.GET.get("preserved") == "1"

    # collect raw routes, grouped by base route_id
    raw_routes_grouped = defaultdict(list)
    for d in RAW_DIR.iterdir():
        if not d.is_dir():
            continue
        base_id = normalize_route_id(d.name)
        raw_routes_grouped[base_id].append(d)

    # collect stitched routes
    stitched_routes = {d.name: d for d in STITCHED_DIR.iterdir() if d.is_dir()}

    # union of both sets
    all_route_ids = set(raw_routes_grouped.keys()) | set(stitched_routes.keys())

    for route_id in all_route_ids:
        stitched_path = stitched_routes.get(route_id)
        raw_paths = raw_routes_grouped.get(route_id, [])

        # try to determine start_time
        start_time = DEFAULT_OLD_DATE
        for base_path in ([stitched_path] if stitched_path else []) + raw_paths:
            start_time_file = base_path / "start_time.txt"
            if start_time_file.exists():
                with open(start_time_file) as f:
                    ts = f.read().strip()
                    try:
                        start_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
                break

        thumbnails = {}
        if stitched_path:
            thumbnails = {
                cam: [
                    f"{route_id}/thumbs/{cam}/thumb_{i}.jpg"
                    for i in thumb_indices
                ]
                for cam in cameras
            }

        drive = {
            "route_id": route_id,
            "stitched": bool(stitched_path),
            "start_time": start_time,
            "thumbnails": thumbnails,
        }

        if show_preserved_only and route_id not in preserved_routes:
            continue

        drives.append(drive)

    # sort newest first
    drives.sort(
        key=lambda d: d["start_time"] if d["start_time"] != DEFAULT_OLD_DATE else datetime.min,
        reverse=True
    )

    page_size = 20
    paginator = Paginator(drives, page_size)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "viewer/drive_list.html", {
        "page_obj": page_obj,
        "cameras": cameras,
        "camera_labels": CAMERA_LABELS,
        "thumb_indices": thumb_indices,
        "preserved_routes": preserved_routes,
        "show_preserved_only": show_preserved_only,
    })


def drive_detail(request, route_id):
    """Show stitched videos if available, otherwise logs-only route detail."""
    drive_path = STITCHED_DIR / route_id
    videos = []

    if drive_path.is_dir():
        for filename in sorted(os.listdir(drive_path)):
            if filename.endswith(".mp4"):
                videos.append({
                    "file": f"/media/{route_id}/{filename}",
                    "label": CAMERA_LABELS.get(filename, filename)
                })

    # check stitched first, then raw segments for start_time
    start_time = None
    if drive_path.is_dir():
        start_time_file = drive_path / "start_time.txt"
        if start_time_file.exists():
            with open(start_time_file) as f:
                ts = f.read().strip()
                try:
                    start_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass

    if start_time is None:
        for segdir in RAW_DIR.glob(f"{route_id}--*"):
            start_time_file = segdir / "start_time.txt"
            if start_time_file.exists():
                with open(start_time_file) as f:
                    ts = f.read().strip()
                    try:
                        start_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
                break

    if start_time is None:
        start_time = DEFAULT_OLD_DATE

    drive = {
        "route_id": route_id,
        "stitched": drive_path.is_dir(),
        "videos": videos,
        "start_time": start_time,
    }

    preserved_routes = load_preserved_routes()
    return render(request, "viewer/drive_detail.html", {
        "drive": drive,
        "preserved_routes": preserved_routes
    })
