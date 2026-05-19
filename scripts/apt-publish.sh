#!/usr/bin/env bash
# Ingest a freshly built .deb into the APT repository hosted on the
# `gh-pages` branch.
#
# Usage:
#     scripts/apt-publish.sh [PATH/TO/file.deb]
#
# When no argument is given, the most recent .deb produced by
# `make deb` is picked up from the parent directory.
#
# The script never pushes — it only commits to a worktree. Run
# `git -C <worktree> push origin gh-pages` (or `make apt-push`) to publish.
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_DIR="${REPO_ROOT}/.gh-pages"
GH_PAGES_BRANCH="gh-pages"
APT_DIR="apt"                 # relative to the worktree root
DISTRIBUTION="stable"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
command -v reprepro >/dev/null \
    || { echo "error: reprepro is not installed (sudo apt install reprepro)" >&2; exit 1; }
command -v gpg >/dev/null \
    || { echo "error: gpg is not installed" >&2; exit 1; }

# Locate the .deb to ingest.
if [[ $# -gt 0 ]]; then
    DEB="$1"
else
    # `make deb` drops the file in the parent directory.
    DEB="$(ls -1t "${REPO_ROOT}/.."/process-media_*_*.deb 2>/dev/null | head -n1 || true)"
    if [[ -z "${DEB}" ]]; then
        echo "error: no .deb found; run 'make deb' first or pass the file as argument" >&2
        exit 1
    fi
fi

if [[ ! -f "${DEB}" ]]; then
    echo "error: ${DEB} is not a file" >&2
    exit 1
fi

DEB_BASENAME="$(basename "${DEB}")"
echo ">>> Publishing ${DEB_BASENAME} to the APT repository"

# ---------------------------------------------------------------------------
# Worktree management
# ---------------------------------------------------------------------------
# Create (or refresh) a git worktree pinned to gh-pages so we can edit it
# without leaving the current branch.
if [[ ! -d "${WORKTREE_DIR}" ]]; then
    echo ">>> Creating worktree at ${WORKTREE_DIR}"
    git -C "${REPO_ROOT}" worktree add "${WORKTREE_DIR}" "${GH_PAGES_BRANCH}"
fi

# Make sure the worktree is on the right branch and clean before we touch it.
WT_BRANCH="$(git -C "${WORKTREE_DIR}" rev-parse --abbrev-ref HEAD)"
if [[ "${WT_BRANCH}" != "${GH_PAGES_BRANCH}" ]]; then
    echo "error: worktree ${WORKTREE_DIR} is on '${WT_BRANCH}', expected '${GH_PAGES_BRANCH}'" >&2
    exit 1
fi
if [[ -n "$(git -C "${WORKTREE_DIR}" status --porcelain)" ]]; then
    echo "error: worktree ${WORKTREE_DIR} has uncommitted changes; commit or stash them first" >&2
    git -C "${WORKTREE_DIR}" status --short
    exit 1
fi

# Pull the latest gh-pages so we don't try to re-add a package that was
# already published from another machine.
echo ">>> Updating worktree from origin/${GH_PAGES_BRANCH}"
git -C "${WORKTREE_DIR}" fetch origin "${GH_PAGES_BRANCH}" --quiet
git -C "${WORKTREE_DIR}" pull --ff-only --quiet origin "${GH_PAGES_BRANCH}" || {
    echo "warning: could not fast-forward worktree (no upstream?), continuing"
}

# ---------------------------------------------------------------------------
# Ingest via reprepro
# ---------------------------------------------------------------------------
APT_ROOT="${WORKTREE_DIR}/${APT_DIR}"
if [[ ! -d "${APT_ROOT}" ]]; then
    echo "error: ${APT_ROOT} does not exist on the gh-pages branch" >&2
    exit 1
fi

# Refuse to re-add a version already present (reprepro would error out
# anyway, but the message here is friendlier).
DEB_VERSION="$(dpkg-deb -f "${DEB}" Version)"
if reprepro -b "${APT_ROOT}" list "${DISTRIBUTION}" process-media 2>/dev/null \
        | grep -qE " ${DEB_VERSION}\$"; then
    echo "error: version ${DEB_VERSION} is already in the repository" >&2
    echo "       bump debian/changelog and rebuild." >&2
    exit 1
fi

echo ">>> Ingesting via reprepro"
reprepro -b "${APT_ROOT}" --keepunreferencedfiles includedeb "${DISTRIBUTION}" "${DEB}"

# Drop any newly-unreferenced files (older versions superseded by the
# import above) and refresh the indices.
reprepro -b "${APT_ROOT}" deleteunreferenced

# ---------------------------------------------------------------------------
# Commit on gh-pages
# ---------------------------------------------------------------------------
if [[ -z "$(git -C "${WORKTREE_DIR}" status --porcelain)" ]]; then
    echo ">>> Nothing to commit (repository already up to date)"
    exit 0
fi

echo ">>> Committing on ${GH_PAGES_BRANCH}"
git -C "${WORKTREE_DIR}" add -A
git -C "${WORKTREE_DIR}" commit -m "apt: publish ${DEB_BASENAME}"

cat <<EOF

>>> Done. The new package is staged on the local '${GH_PAGES_BRANCH}' branch.
    Review with:   git -C ${WORKTREE_DIR} log -1 --stat
    Publish with:  git -C ${WORKTREE_DIR} push origin ${GH_PAGES_BRANCH}
                   (or: make apt-push)
EOF
