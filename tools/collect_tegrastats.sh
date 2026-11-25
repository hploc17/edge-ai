#!/usr/bin/env bash
# Run directly on the Jetson host. No Python, agent, MQTT or WebGIS required.
# Usage: bash tools/collect_tegrastats.sh [duration_seconds=60] [interval_ms=1000] [output_root=bench_results]
# duration_seconds=0: collect until Ctrl+C.
set -u

duration="${1:-60}"
interval="${2:-1000}"
output_root="${3:-bench_results}"
if [[ ! "$duration" =~ ^[0-9]+$ ]] || [[ ! "$interval" =~ ^[0-9]+$ ]] || (( 10#$interval < 100 )); then
    echo 'Usage: bash tools/collect_tegrastats.sh [seconds >= 0] [interval_ms >= 100] [output_root]' >&2
    exit 2
fi
duration=$((10#$duration))
interval=$((10#$interval))

binary="${TEGRASTATS_PATH:-}"
if [[ -z "$binary" ]]; then
    binary="$(command -v tegrastats 2>/dev/null || true)"
fi
if [[ -z "$binary" ]]; then
    for candidate in /usr/bin/tegrastats /usr/local/bin/tegrastats /usr/sbin/tegrastats /home/nvidia/tegrastats; do
        if [[ -x "$candidate" ]]; then binary="$candidate"; break; fi
    done
fi
if [[ -z "$binary" || ! -x "$binary" ]]; then
    echo 'Cannot find executable tegrastats in this environment.' >&2
    echo 'Run on the Jetson host where tegrastats works, or set TEGRASTATS_PATH to its absolute path.' >&2
    exit 127
fi

mkdir -p -- "$output_root" || exit 1
run_dir="$(mktemp -d "$output_root/manual_tegrastats_$(date +%Y%m%d_%H%M%S)_XXXXXX")" || exit 1
{
    printf 'started=%s\n' "$(date -Is)"
    printf 'binary=%s\nduration_seconds=%s\ninterval_ms=%s\n' "$binary" "$duration" "$interval"
    printf 'user=%s\n' "$(id -un)"
    uname -a
} > "$run_dir/session.txt"

child=''
timer=''
stop_child() {
    if [[ -n "$child" ]]; then kill -TERM "$child" 2>/dev/null || true; fi
}
trap stop_child INT TERM
echo "Saving to: $run_dir"
echo 'Collecting tegrastats. Ctrl+C stops this capture only.'
"$binary" --interval "$interval" > "$run_dir/tegrastats.log" 2> "$run_dir/tegrastats.stderr.log" &
child=$!
if (( duration > 0 )); then
    ( sleep "$duration"; kill -TERM "$child" 2>/dev/null || true ) &
    timer=$!
fi
wait "$child"
result=$?
# A signal can interrupt wait before the child finishes flushing its output.
wait "$child" 2>/dev/null || true
if [[ -n "$timer" ]]; then kill "$timer" 2>/dev/null || true; wait "$timer" 2>/dev/null || true; fi
trap - INT TERM
{
    printf 'finished=%s\nexit_code=%s\n' "$(date -Is)" "$result"
    printf 'ram_sample_lines=%s\n' "$(grep -c 'RAM ' "$run_dir/tegrastats.log" || true)"
} >> "$run_dir/session.txt"
echo "Finished. Raw measurements: $run_dir/tegrastats.log"
echo "Diagnostics: $run_dir/tegrastats.stderr.log and $run_dir/session.txt"
tail -n 5 "$run_dir/tegrastats.log"
if ! grep -q 'RAM ' "$run_dir/tegrastats.log"; then
    echo 'WARNING: no RAM measurement lines captured. Check stderr and executable/environment/permissions.' >&2
    cat "$run_dir/tegrastats.stderr.log" >&2
    exit 1
fi
