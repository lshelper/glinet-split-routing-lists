#!/usr/bin/env bash
set -euo pipefail

ROUTER="root@192.168.8.1"
SECTION=""
DRY_RUN=0
RESTART=1

usage() {
  cat <<'EOF'
Usage:
  scripts/glinet-add-vpn-domain.sh [options] DOMAIN

Options:
  -r, --router USER@HOST   SSH target for the GL.iNet router.
                           Default: root@192.168.8.1
  -s, --section SECTION    UCI vpnpolicy section to update.
                           Default: auto-detect, preferring "domain".
                           Examples: domain, @policy[0]
  -n, --dry-run            Show what would change, but do not write config.
      --no-restart         Do not restart vpnpolicy after writing.
  -h, --help               Show this help.

Examples:
  scripts/glinet-add-vpn-domain.sh gosuslugi.ru
  scripts/glinet-add-vpn-domain.sh -r root@192.168.1.1 mos.ru
  scripts/glinet-add-vpn-domain.sh -s domain --dry-run nalog.ru

The script updates /etc/config/vpnpolicy on the router, creates a timestamped
backup next to it, commits UCI changes, and restarts vpnpolicy-apply.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

validate_domain() {
  local domain="$1"

  [[ "$domain" != *"://"* ]] || return 1
  [[ "$domain" != *"/"* ]] || return 1
  [[ "$domain" != .* ]] || return 1
  [[ "$domain" != *. ]] || return 1
  [[ "$domain" == *.* ]] || return 1
  [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]] || return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--router)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      ROUTER="$2"
      shift 2
      ;;
    -s|--section)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      SECTION="$2"
      shift 2
      ;;
    -n|--dry-run)
      DRY_RUN=1
      shift
      ;;
    --no-restart)
      RESTART=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      break
      ;;
  esac
done

[[ $# -eq 1 ]] || {
  usage >&2
  exit 2
}

DOMAIN="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
validate_domain "$DOMAIN" || die "invalid domain: $1"

REMOTE_SCRIPT='
set -eu

domain="$1"
section="$2"
dry_run="$3"
restart_policy="$4"
config="/etc/config/vpnpolicy"

log() {
  printf "%s\n" "$*"
}

fail() {
  printf "error: %s\n" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command on router: $1"
}

uci_get() {
  uci -q get "$1" 2>/dev/null || true
}

uci_section_exists() {
  uci -q show "vpnpolicy.$1" >/dev/null 2>&1
}

detect_section() {
  if [ -n "$section" ]; then
    uci_section_exists "$section" || fail "vpnpolicy section not found: $section"
    printf "%s\n" "$section"
    return 0
  fi

  if uci_section_exists "domain"; then
    printf "%s\n" "domain"
    return 0
  fi

  detected="$(uci -q show vpnpolicy | sed -n "s/^vpnpolicy\.\([^.=]*\)=policy$/\1/p" | head -n 1)"
  if [ -n "$detected" ]; then
    printf "%s\n" "$detected"
    return 0
  fi

  detected="$(uci -q show vpnpolicy | sed -n "s/^vpnpolicy\.\(@policy\[[0-9][0-9]*\]\)=policy$/\1/p" | head -n 1)"
  if [ -n "$detected" ]; then
    printf "%s\n" "$detected"
    return 0
  fi

  fail "could not find a vpnpolicy policy section"
}

restart_vpnpolicy() {
  if [ "$restart_policy" != "1" ]; then
    log "restart skipped (--no-restart)"
    return 0
  fi

  if command -v service >/dev/null 2>&1 && service vpnpolicy-apply restart >/dev/null 2>&1; then
    log "restarted vpnpolicy-apply via service"
    return 0
  fi

  if [ -x /etc/init.d/vpnpolicy-apply ] && /etc/init.d/vpnpolicy-apply restart >/dev/null 2>&1; then
    log "restarted vpnpolicy-apply via init.d"
    return 0
  fi

  if command -v route_policy >/dev/null 2>&1; then
    proxy_mode="$(uci_get vpnpolicy.route_policy.proxy_mode)"
    if [ -n "$proxy_mode" ] && route_policy "$proxy_mode" >/dev/null 2>&1; then
      log "reloaded vpnpolicy via route_policy $proxy_mode"
      return 0
    fi
  fi

  log "warning: could not restart vpnpolicy automatically; restart it from the UI or reboot the router"
}

require_cmd uci
[ -f "$config" ] || fail "$config not found"

target_section="$(detect_section)"
current_values="$(uci_get "vpnpolicy.$target_section.domain")"

tmp_values="$(mktemp)"
trap "rm -f \"$tmp_values\"" EXIT

if [ -n "$current_values" ]; then
  printf "%s\n" "$current_values" | tr " " "\n" | sed "/^$/d" | sort -u > "$tmp_values"
else
  : > "$tmp_values"
fi

if grep -Fxq "$domain" "$tmp_values"; then
  log "$domain already exists in vpnpolicy.$target_section.domain"
  exit 0
fi

log "router section: vpnpolicy.$target_section"
log "adding domain: $domain"

if [ "$dry_run" = "1" ]; then
  log "dry-run: no changes written"
  exit 0
fi

backup="$config.codex-backup.$(date +%Y%m%d-%H%M%S)"
cp "$config" "$backup"
log "backup: $backup"

uci -q delete "vpnpolicy.$target_section.domain" 2>/dev/null || true

if [ -s "$tmp_values" ]; then
  while IFS= read -r value; do
    [ -n "$value" ] || continue
    uci add_list "vpnpolicy.$target_section.domain=$value"
  done < "$tmp_values"
fi

uci add_list "vpnpolicy.$target_section.domain=$domain"
uci commit vpnpolicy
restart_vpnpolicy

log "done"
'

ssh "$ROUTER" sh -s -- "$DOMAIN" "$SECTION" "$DRY_RUN" "$RESTART" <<EOF
$REMOTE_SCRIPT
EOF
