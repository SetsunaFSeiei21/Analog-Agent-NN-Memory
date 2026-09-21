#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_ROOT" rev-parse --show-toplevel)"
if [[ "$PROJECT_ROOT" == "$REPO_ROOT" ]]; then
    PROJECT_PATH=.
elif [[ "$PROJECT_ROOT" == "$REPO_ROOT/"* ]]; then
    PROJECT_PATH="${PROJECT_ROOT#"$REPO_ROOT"/}"
else
    echo "[ERROR] Analog-Agent 不在当前 Git 仓库内" >&2
    exit 1
fi

BRANCH="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD)" || {
    echo "[ERROR] 当前处于 detached HEAD，请先切换到要推送的分支" >&2
    exit 1
}
REMOTE="$(git -C "$REPO_ROOT" remote get-url origin)" || {
    echo "[ERROR] 当前仓库没有 origin 远端" >&2
    exit 1
}

if (( $# > 0 )); then
    COMMIT_MESSAGE="$*"
else
    COMMIT_FILE="$SCRIPT_DIR/commit_message.txt"
    [[ -s "$COMMIT_FILE" ]] || {
        echo "[ERROR] 请传入提交信息，或填写 $COMMIT_FILE" >&2
        exit 1
    }
fi

git -C "$REPO_ROOT" add -A -- "$PROJECT_PATH"
if [[ "$PROJECT_PATH" != . ]]; then
    mapfile -d '' -t STAGED < <(git -C "$REPO_ROOT" diff --cached --name-only -z)
    for path in "${STAGED[@]}"; do
        if [[ "$path" != "$PROJECT_PATH" && "$path" != "$PROJECT_PATH/"* ]]; then
            echo "[ERROR] 暂存区还有其他目录的文件：$path；请先单独处理" >&2
            exit 1
        fi
    done
fi

echo "仓库：$REPO_ROOT"
echo "推送目标：$REMOTE ($BRANCH)"
if git -C "$REPO_ROOT" diff --cached --quiet; then
    echo "Analog-Agent 没有新改动，跳过提交"
elif (( $# > 0 )); then
    git -C "$REPO_ROOT" commit -m "$COMMIT_MESSAGE"
else
    git -C "$REPO_ROOT" commit -F "$COMMIT_FILE"
fi

git -C "$REPO_ROOT" push -u origin "$BRANCH"
