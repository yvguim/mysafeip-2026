# shellcheck shell=sh
set -eu

[ "${CI_PIPELINE_EVENT:-}" = push ]
[ "${CI_COMMIT_REF:-}" = refs/heads/main ]
[ "${CI_REPO:-}" = yvguim/mysafeip-2026 ]
: "${DOCKERHUB_RELEASE_TOKEN:?Approved release credential is not available}"

{
    IFS= read -r tag
    IFS= read -r commit
    IFS= read -r digest
} < mysafeip-release.txt
printf '%s\n' "$tag" | grep -Eq '^docker-v0\.13\.(0|[1-9][0-9]*)$'
printf '%s\n' "$digest" | grep -Eq '^sha256:[a-f0-9]{64}$'
[ "$commit" = "$CI_COMMIT_SHA" ]

umask 077
private=$(mktemp -d)
trap 'rm -rf -- "$private"' EXIT
auth="$private/auth.json"
source=oci-archive:mysafeip-ci.oci.tar
destination="docker://docker.io/yvguim/mysafeip:$tag"
skopeo inspect --raw "$source" > "$private/local.json"
[ "sha256:$(sha256sum < "$private/local.json" | cut -d ' ' -f 1)" = "$digest" ]
printf '%s\n' "$DOCKERHUB_RELEASE_TOKEN" |
    skopeo login --authfile "$auth" --username yvguim --password-stdin docker.io
unset DOCKERHUB_RELEASE_TOKEN

inspect() { skopeo inspect --authfile "$auth" --raw "$destination"; }
assert_digest() {
    actual="sha256:$(sha256sum < "$private/remote.json" | cut -d ' ' -f 1)"
    if [ "$actual" != "$digest" ]; then
        printf 'Refusing %s: registry digest %s does not match %s\n' "$tag" "$actual" "$digest" >&2
        exit 1
    fi
}

if inspect > "$private/remote.json" 2> "$private/inspect.error"; then
    assert_digest
else
    # Authorization, rate limits, and connectivity failures do not mean the tag is absent.
    if ! grep -qi 'manifest unknown' "$private/inspect.error"; then
        cat "$private/inspect.error" >&2
        exit 1
    fi
    # If a concurrent job filled an immutable tag, only the same digest counts as success.
    if ! skopeo copy --all --preserve-digests --dest-authfile "$auth" "$source" "$destination"; then
        printf 'Push failed; checking whether another run published the same digest.\n' >&2
    fi
    inspect > "$private/remote.json"
    assert_digest
fi
printf 'Verified on Docker Hub: yvguim/mysafeip:%s → %s → %s\n' "$tag" "$commit" "$digest"
