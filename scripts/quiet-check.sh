#!/bin/sh
# Keep successful checks silent; replay diagnostics and preserve the exit code on failure.
set -eu

if [ "$#" -eq 0 ]; then
    printf 'Usage: %s COMMAND [ARG ...]\n' "$0" >&2
    exit 2
fi

log=$(mktemp)
trap 'rm -f -- "$log"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if "$@" >"$log" 2>&1; then
    exit 0
else
    status=$?
    cat -- "$log" >&2 || :
    exit "$status"
fi
