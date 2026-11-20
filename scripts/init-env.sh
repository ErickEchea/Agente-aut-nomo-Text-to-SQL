#!/bin/sh
# Create .env from .env.example, replacing each __GENERATE__ with a distinct random secret.
# If .env already exists, only APPEND keys that are missing (new settings from a newer version);
# existing values are never modified.
set -eu

cd "$(dirname "$0")/.."

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate secrets (bundled with Git for Windows, macOS and most Linux distros)." >&2
  exit 1
fi

render_line() {
  # $1 = one line of .env.example
  case "$1" in
    *=__GENERATE__)
      # 32 random bytes, hex-encoded: safe in URLs, DSNs and shell without quoting.
      printf '%s=%s\n' "${1%%=*}" "$(openssl rand -hex 32)"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

if [ ! -f .env ]; then
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' EXIT
  while IFS= read -r line || [ -n "$line" ]; do
    render_line "$line" >>"$tmp"
  done <.env.example
  mv "$tmp" .env
  trap - EXIT
  echo "Created .env with freshly generated secrets."
  exit 0
fi

added=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  key=${line%%=*}
  if ! grep -q "^${key}=" .env; then
    render_line "$line" >>.env
    added="$added $key"
  fi
done <.env.example

if [ -n "$added" ]; then
  echo "Added missing settings to .env:$added"
else
  echo ".env is up to date."
fi
