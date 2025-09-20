#!/bin/bash
set -euo pipefail

# Configuration
C3X_IP="192.168.86.85"
C3X_USER="comma"
SSH_KEY="~/.ssh/opensshkey"
REMOTE_DRIVES="/data/media/0/realdata"
LOCAL_RAW="/srv/dev-disk-by-uuid-b502f01f-739c-464b-8f02-8037fe760b79/openpilot_data/raw"
LOCAL_STITCHED="/srv/dev-disk-by-uuid-b502f01f-739c-464b-8f02-8037fe760b79/openpilot_data/stitched"
LOG_FILE="/srv/dev-disk-by-uuid-b502f01f-739c-464b-8f02-8037fe760b79/openpilot_data/logs/c3x_sync.log"

MIN_FREE_GB=75
# End Configuration

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"; }

# ping device ip to check if online or not
if ! ping -c 1 -W 2 "$C3X_IP" >/dev/null 2>&1; then
    log "C3X not reachable at $C3X_IP"
    exit 0
fi

# FUNCTION: check free space
check_space() {
    avail_gb=$(df -BG "$LOCAL_RAW" | awk 'NR==2 {gsub("G","",$4); print $4}')
    echo "$avail_gb"
}

# FUNCTION: cleanup oldest routes
cleanup_routes() {
    log "Free space below ${MIN_FREE_GB}GB, cleaning up old routes..."
    for route_dir in $(find "$LOCAL_STITCHED" -mindepth 1 -maxdepth 1 -type d | sort); do
        if [ -f "$route_dir/.preserve" ]; then
            log "Skipping preserved route $(basename "$route_dir")"
            continue
        fi

        log "Deleting route $(basename "$route_dir")..."
        rm -rf "$route_dir"
        rm -rf "$LOCAL_RAW"/*--"$(basename "$route_dir")"--*

        avail=$(check_space)
        if [ "$avail" -ge "$MIN_FREE_GB" ]; then
            log "Cleanup finished, free space now ${avail}GB"
            return
        fi
    done
}

# check free space before syncing
free_before=$(check_space)
log "Available space: ${free_before}GB"
if [ "$free_before" -lt "$MIN_FREE_GB" ]; then
    cleanup_routes
fi

# use rsync to copy any new drives
# First: sync only log files
log "Syncing logs first..."
rsync -av -e "ssh -i $SSH_KEY" \
  --include="*/" \
  --include="*.zst" \
  --include="*.ts" \
  --exclude="*.hevc" \
  "$C3X_USER@$C3X_IP:$REMOTE_DRIVES/" "$LOCAL_RAW/" | tee -a "$LOG_FILE"

# Then: sync videos
log "Syncing video segments..."
rsync -av -e "ssh -i $SSH_KEY" --ignore-existing \
  "$C3X_USER@$C3X_IP:$REMOTE_DRIVES/" "$LOCAL_RAW/" | tee -a "$LOG_FILE"

# stitch together the drive videos into one video file per camera
routes=$(find "$LOCAL_RAW" -mindepth 1 -maxdepth 1 -type d \
           -not -name boot \
           -name "*--*" \
           -printf "%f\n" \
         | awk -F'--' '{print $1"--"$2}' \
         | sort -u)

for route_id in $routes; do
    stitched_path="$LOCAL_STITCHED/$route_id"
    [ -d "$stitched_path" ] && continue
    mkdir -p "$stitched_path"
    log "Stitching route $route_id..."

    # get the start time and save it to a text file
    first_seg=$(find "$LOCAL_RAW" -type d -name "$route_id--0" | sort -V | head -n1)
    if [ -n "$first_seg" ]; then
        route_time=$(stat -c %y "$first_seg" | cut -d'.' -f1)
        echo "$route_time" > "$stitched_path/start_time.txt"
        log "Route $route_id start time: $route_time"
    else
        log "No segment 0 found for route $route_id, skipping start_time metadata"
    fi

    # stitch the videos together for each camera
    for cam in fcamera ecamera dcamera; do
        output="$stitched_path/${cam}.mp4"
        filelist=$(mktemp)

        # find all segment folders for this route, sorted by segment number
        find "$LOCAL_RAW" -type d -name "$route_id--*" \
            | sort -V \
            | while read segdir; do
                hevc_file="$segdir/${cam}.hevc"
                [ -f "$hevc_file" ] && echo "file '$hevc_file'" >> "$filelist"
            done

        if [ -s "$filelist" ]; then
            log "Stitching $cam -> $output"
            ffmpeg -y -f concat -safe 0 -i "$filelist" -c copy "$output"

            # generate thumbnails
            thumbs_dir="$stitched_path/thumbs/$cam"
            mkdir -p "$thumbs_dir"

            duration=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration \
                       -of default=noprint_wrappers=1:nokey=1 "$output")

            # 3 thumbnails evenly spaced
            for i in 1 2 3; do
                ts=$(awk "BEGIN {print $duration*$i/4}")
                ffmpeg -y -ss "$ts" -i "$output" -frames:v 1 -s 320x180 "$thumbs_dir/thumb_$i.jpg"
            done
        else
            log "No $cam files found in route $route_id"
        fi

        rm "$filelist"
    done

    log "Finished stitching route $route_id"
done