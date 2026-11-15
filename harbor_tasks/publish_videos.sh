#!/bin/bash
# For every trial under the given dirs, publish artifacts/rollout.mp4 as agent/recording.mp4,
# which the Harbor viewer plays in the trial page's "Recording" tab. (The viewer's file
# browser cannot open .mp4 files.) Re-muxed to a plain faststart mp4 for browser playback.
cd "$(dirname "$0")/.."
FF=$(.venv/bin/python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
for d in "$@"; do
  find "$d" -path "*/artifacts/rollout.mp4" | while read -r v; do
    t=$(dirname "$(dirname "$v")"); mkdir -p "$t/agent"
    "$FF" -y -loglevel error -i "$v" -c copy -movflags +faststart "$t/agent/recording.mp4" </dev/null \
      || cp "$v" "$t/agent/recording.mp4"
    echo "published $t/agent/recording.mp4"
  done
done
