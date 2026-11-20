#!/bin/sh
# Create .env from .env.example, replacing each __GENERATE__ with a distinct random secret.
# Idempotent: an existing .env is never overwritten.
set -eu

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists — leaving it untouched."
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate secrets (bundled with Git for Windows, macOS and most Linux distros)." >&2
  exit 1
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    *=__GENERATE__)
      # 32 random bytes, hex-encoded: safe in URLs, DSNs and shell without quoting.
      printf '%s=%s\n' "${line%%=*}" "$(openssl rand -hex 32)" >>"$tmp"
      ;;
    *)
      printf '%s\n' "$line" >>"$tmp"
      ;;
  esac
done <.env.example

mv "$tmp" .env
trap - EXIT
echo "Created .env with freshly generated secrets."
