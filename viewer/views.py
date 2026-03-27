import os
import json
import re
import capnp
import zstandard as zstd
import io
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from django.shortcuts import render, redirect
from django.core.paginator import Paginator

from django.views.decorators.http import require_POST
from django.contrib import messages
import shutil

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


def get_route_start_time(route_id: str) -> datetime:
    """
    Try to determine route start time.
    Priority:
      1. start_time.txt in stitched folder
      2. mtime of segment 0 folder in raw
    """
    stitched_path = STITCHED_DIR / route_id
    start_time_file = stitched_path / "start_time.txt"

    # Case 1: stitched has start_time.txt
    if start_time_file.exists():
        try:
            with open(start_time_file) as f:
                ts = f.read().strip()
                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # Case 2: use segment 0 folder mtime
    seg0 = RAW_DIR / f"{route_id}--0"
    if seg0.exists() and seg0.is_dir():
        ts = datetime.fromtimestamp(seg0.stat().st_mtime)
        return ts

    # Fallback
    return DEFAULT_OLD_DATE

# Recreate stitched video
@require_POST
def recreate_stitched(request, route_id):
    """Delete stitched folder so it can be regenerated."""
    stitched_path = STITCHED_DIR / route_id
    if stitched_path.exists() and stitched_path.is_dir():
        shutil.rmtree(stitched_path)
        messages.success(request, f"Stitched video for {route_id} will be recreated on next sync.")
    else:
        messages.warning(request, f"No stitched video exists for {route_id} to recreate.")

    return redirect("drive_detail", route_id=route_id)


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
        start_time = get_route_start_time(route_id)
        if start_time is None:
            start_time = DEFAULT_OLD_DATE

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
    start_time = get_route_start_time(route_id)

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

def segment_list(request, route_id):
    """Lists all available segments (minutes) for a route that have logs."""
    segments = []
    
    # Search RAW_DIR for folders matching "route_id--N"
    # We use glob to find all segment folders for this route
    for segment_folder in sorted(RAW_DIR.glob(f"{route_id}--*")):
        if segment_folder.is_dir():
            qlog_path = segment_folder / "qlog.zst"
            rlog_path = segment_folder / "rlog.zst"
            
            # Determine which log to favor (qlog is better for web)
            log_file = None
            if qlog_path.exists():
                log_file = "qlog.zst"
            elif rlog_path.exists():
                log_file = "rlog.zst"
                
            if log_file:
                # Extract the segment number (the "N" in route--N)
                seg_num = segment_folder.name.split("--")[-1]
                segments.append({
                    "number": seg_num,
                    "folder_name": segment_folder.name,
                    "log_type": log_file
                })

    return render(request, "viewer/segment_list.html", {
        "route_id": route_id,
        "segments": segments
    })

def log_detail(request, route_id, segment_num):
    """Parses and displays a specific log file."""
    # Construct path to qlog.zst
    segment_folder = f"{route_id}--{segment_num}"
    log_path = RAW_DIR / segment_folder / "qlog.zst"

    if not log_path.exists():
        return render(request, "error.html", {"message": "Log file not found."})

    # Load Schema
    CURRENT_DIR = Path(__file__).resolve().parent
    CEREAL_DIR = CURRENT_DIR / "cereal"
    LOG_CAPNP_PATH = CEREAL_DIR / "log.capnp"

    if LOG_CAPNP_PATH.exists():
        log_capnp = capnp.load(str(LOG_CAPNP_PATH), imports=[str(CEREAL_DIR)])
    else:
        log_capnp = None
        print(f"WARNING: log.capnp not found at {LOG_CAPNP_PATH}")

    events = []
    dctx = zstd.ZstdDecompressor()
    
    try:
        with open(log_path, 'rb') as f:
            with dctx.stream_reader(f) as reader:
                data = reader.read()
            
            # Parse messages
            log_events = log_capnp.Event.read_multiple_bytes(data)
            
            for event in log_events:
                msg_type = event.which()
                # Whitelist common display types to keep the page snappy
                if msg_type in ['carState', 'carControl', 'modelV2', 'pandaStates', 'deviceState']:
                    events.append({
                        "type": msg_type,
                        "time": event.logMonoTime,
                        "data": event.to_dict()[msg_type]
                    })
    except Exception as e:
        return render(request, "error.html", {"message": f"Parsing Error: {e}"})

    return render(request, "viewer/log_detail.html", {
        "route_id": route_id,
        "segment_num": segment_num,
        "events": events
    })
