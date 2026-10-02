#!/bin/sh
# Install claude-accounts:
#   curl -fsSL https://raw.githubusercontent.com/Spshulem/claude-accounts/main/install.sh | sh
set -eu
[ "$(uname -s)" = Darwin ] || { echo "claude-accounts supports macOS only." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (xcode-select --install)." >&2; exit 1; }
command -v claude >/dev/null || { echo "Install Claude Code first: https://docs.anthropic.com/en/docs/claude-code" >&2; exit 1; }
ref="${CLAUDE_ACCOUNTS_REF:-main}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://github.com/Spshulem/claude-accounts/archive/refs/heads/$ref.tar.gz" | tar -xz -C "$tmp" --strip-components 1
python3 "$tmp/claude-accounts" install "$@"
