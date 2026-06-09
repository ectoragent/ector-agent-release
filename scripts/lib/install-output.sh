#!/usr/bin/env bash
# Saída compacta do install: uma linha ✔ por passo (rótulos em português claro).
# ECTOR_INSTALL_VERBOSE=1 mostra stderr do comando quando um passo falha.

_install_verbose() {
    [ "${ECTOR_INSTALL_VERBOSE:-0}" = 1 ] || [ "${ECTOR_INSTALL_VERBOSE:-}" = true ]
}

_install_update_progress() {
    [ -n "${ECTOR_UPDATE_PROGRESS:-}" ]
}

_install_step_ok() {
    if _install_update_progress; then
        printf 'ECTOR_UPDATE:ok:%s\n' "$1"
    else
        printf '✔ %s\n' "$1"
    fi
}

_install_step_fail() {
    if _install_update_progress; then
        printf 'ECTOR_UPDATE:fail:%s\n' "$1" >&2
    else
        printf '✗ %s\n' "$1" >&2
    fi
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

    if [ -n "${ECTOR_NONINTERACTIVE:-}" ] && ! _install_verbose && ! _install_update_progress; then
        printf '→ %s...\n' "$label"
    fi

    if _install_update_progress; then
        printf 'ECTOR_UPDATE:start:%s\n' "$label"
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
