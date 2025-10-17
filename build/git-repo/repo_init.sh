#!/bin/sh

set -e

REPO_ROOT="/git"
REPO_LIST_FILE="/repo_list.txt"

if [ ! -f "$REPO_LIST_FILE" ]; then
  echo "ERROR: repo_list.txt not found!"
  exit 1
fi

# Read file line-by-line
while IFS= read -r repo_path || [ -n "$repo_path" ]; do
  # Skip empty lines or comments
  if [ -z "$repo_path" ] || [ "${repo_path#\#}" != "$repo_path" ]; then
    continue
  fi

  REPO_DIR="$REPO_ROOT/$repo_path.git"

  if [ -d "$REPO_DIR" ]; then
    echo "Repo already exists: $REPO_DIR"
    continue
  fi

  echo "Creating repo: $REPO_DIR"
  mkdir -p "$(dirname "$REPO_DIR")"
  git init --bare "$REPO_DIR"
  cd "$REPO_DIR"
  git config http.receivepack true
done < "$REPO_LIST_FILE"
