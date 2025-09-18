import os
import json
from django.shortcuts import render
from pathlib import Path
from datetime import datetime
from django.views.decorators.http import require_POST
from django.shortcuts import redirect
from django.core.paginator import Paginator

DEFAULT_OLD_DATE = datetime(1900, 1, 1)

STITCHED_DIR = Path("/data/stitched")  # Mounted in Docker

CAMERA_LABELS = {
    "fcamera.mp4": "Front Camera",
    "ecamera.mp4": "Wide Camera",
    "dcamera.mp4": "Driver Camera",
}

METADATA_DIR = Path("/data/metadata")
METADATA_DIR.mkdir(exist_ok=True)
PRESERVED_FILE = METADATA_DIR / "preserved_routes.json"

def load_preserved_routes():
    if PRESERVED_FILE.exists():
        with open(PRESERVED_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_preserved_routes(preserved_set):
    with open(PRESERVED_FILE, "w") as f:
        json.dump(list(preserved_set), f)

def toggle_preserve(request, route_id):
    preserved = load_preserved_routes()
    if route_id in preserved:
        preserved.remove(route_id)
    else:
        preserved.add(route_id)
    save_preserved_routes(preserved)
    # redirect back to drive_list or referring page
    return redirect(request.META.get("HTTP_REFERER", "/"))

def drive_list(request):
    """List all drives. Limit to 20 per page."""
    drives = []
    cameras = ["fcamera", "ecamera", "dcamera"]
    thumb_indices = [1, 2, 3]

    preserved_routes = load_preserved_routes()
    show_preserved_only = request.GET.get("preserved") == "1"

    for route_dir in STITCHED_DIR.iterdir():
        if not route_dir.is_dir():
            continue

        start_time = None
        start_time_file = route_dir / "start_time.txt"
        if start_time_file.exists():
            with open(start_time_file) as f:
                ts = f.read().strip()
                try:
                    start_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    start_time = None

        if start_time is None:
            start_time = DEFAULT_OLD_DATE

        thumbnails = {
            cam: [
                f"{route_dir.name}/thumbs/{cam}/thumb_{i}.jpg"
                for i in thumb_indices
            ]
            for cam in cameras
        }

        drive = {
            "route_id": route_dir.name,
            "stitched_path": str(route_dir),
            "start_time": start_time,
            "thumbnails": thumbnails,
        }

        if show_preserved_only and route_dir.name not in preserved_routes:
            continue

        drives.append(drive)


    # sort newest first
    drives.sort(
        key=lambda d: d["start_time"] if d["start_time"] != DEFAULT_OLD_DATE else datetime.min,
        reverse=True
    )

    page_size = 20  # number of drives per page
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
    """Show stitched videos for a single route"""
    drive_path = STITCHED_DIR / route_id
    videos = []

    if drive_path.is_dir():
        for filename in sorted(os.listdir(drive_path)):
            if filename.endswith(".mp4"):
                videos.append({
                    "file": f"/media/{route_id}/{filename}",
                    "label": CAMERA_LABELS.get(filename, filename)
                })

    start_time = None
    start_time_file = drive_path / "start_time.txt"
    if start_time_file.exists():
        with open(start_time_file) as f:
            ts = f.read().strip()
            try:
                start_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                start_time = None
    if start_time is None:
        start_time = DEFAULT_OLD_DATE

    drive = {
        "route_id": route_id,
        "stitched_path": str(drive_path),
        "videos": videos,
        "start_time": start_time,
    }

    preserved_routes = load_preserved_routes()
    return render(request, "viewer/drive_detail.html", {"drive": drive, "preserved_routes": preserved_routes})