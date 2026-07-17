#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
NODE_VERSION="22.17.1"
ARCH="$(uname -m)"

if command -v node >/dev/null 2>&1; then
  major=$(node --version | sed -E 's/^v([0-9]+).*/\1/')
  if [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 18 )); then
    exit 0
  fi
fi

if [[ "$(uname -s)" != "Linux" || "$ARCH" != "x86_64" ]]; then
  echo "Node.js 18+ is required; automatic provisioning supports Linux x86-64 only." >&2
  exit 2
fi

runtime_root="$REPO_ROOT/.runtime"
downloads="$runtime_root/downloads"
archive="node-v${NODE_VERSION}-linux-x64.tar.xz"
release_url="https://nodejs.org/dist/v${NODE_VERSION}"
version_root="$runtime_root/node-v${NODE_VERSION}-linux-x64"
mkdir -p "$downloads"

download() {
  local url="$1"
  local output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --output "$output" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --tries=3 --output-document="$output" "$url"
  else
    echo "curl or wget is required to provision Node.js." >&2
    exit 2
  fi
}

if [[ ! -f "$downloads/$archive" ]]; then
  echo "Downloading Node.js v${NODE_VERSION} for Linux x86-64."
  download "$release_url/$archive" "$downloads/$archive"
fi
download "$release_url/SHASUMS256.txt" "$downloads/SHASUMS256.txt"
(
  cd "$downloads"
  grep "  $archive\$" SHASUMS256.txt > "$archive.sha256"
  sha256sum --check "$archive.sha256"
)

if [[ ! -x "$version_root/bin/node" ]]; then
  tar -xJf "$downloads/$archive" -C "$runtime_root"
fi
ln -sfn "node-v${NODE_VERSION}-linux-x64" "$runtime_root/node"
"$runtime_root/node/bin/node" --version
