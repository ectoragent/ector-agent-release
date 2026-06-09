#!/usr/bin/env bash
# Saída compacta do install: uma linha ✔ por passo (rótulos em português claro).
# ECTOR_INSTALL_VERBOSE=1 mostra stderr do comando quando um passo falha.

_install_verbose() {
    [ "${ECTOR_INSTALL_VERBOSE:-0}" = 1 ] || [ "${ECTOR_INSTALL_VERBOSE:-}" = true ]
}

_install_step_ok() {
    printf '✔ %s\n' "$1"
}

_install_step_fail() {
    printf '✗ %s\n' "$1" >&2
}

_install_step_warn() {
    printf '▲ %s\n' "$1" >&2
}

_install_show_fail_log() {
    local log="$1"
    [ -f "$log" ] || return 0
    if _install_verbose || [ -n "${ECTOR_NONINTERACTIVE:-}" ]; then
        tail -30 "$log" >&2 || true
    fi
}

_install_step() {
    local label="$1"
    shift
    local log rc=0

    if [ -n "${ECTOR_NONINTERACTIVE:-}" ] && ! _install_verbose; then
        printf '→ %s...\n' "$label"
    fi

    log="$(mktemp "${TMPDIR:-/tmp}/ector-install.XXXXXX")"
    if "$@" >"$log" 2>&1; then
        rm -f "$log"
        _install_step_ok "$label"
        return 0
    fi
    rc=$?
    _install_step_fail "$label"
    _install_show_fail_log "$log"
    rm -f "$log"
    return "$rc"
}

_install_step_try() {
    _install_step "$@" || true
}
