"""Release tags and artifacts must stay tied to a commit and OCI index."""

import hashlib
import io
import json
import tarfile

import pytest

from scripts import release_image as release


def test_release_tags_follow_first_parent_and_retries_are_stable():
    base = "1" * 40
    first = "2" * 40
    second = "3" * 40
    assert release.release_tag([first, base], base) == "docker-v0.13.0"
    assert release.release_tag([second, first, base], base) == "docker-v0.13.1"
    assert release.release_tag([first, base], base) == "docker-v0.13.0"


def test_release_requires_a_commit_after_the_known_base():
    with pytest.raises(ValueError):
        release.release_tag(["1" * 40], "1" * 40)
    with pytest.raises(ValueError):
        release.release_tag(["2" * 40], "1" * 40)


def make_archive(
    path, archs, *, corrupt=False, wrong_config=False, missing_manifest=False
):
    index_type = "application/vnd.oci.image.index.v1+json"
    blobs = {}

    def blob(body, media_type):
        data = json.dumps(body).encode()
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        return {"mediaType": media_type, "digest": digest}

    manifests = []
    for arch in archs:
        config = blob(
            {"os": "linux", "architecture": "386" if wrong_config else arch},
            "application/vnd.oci.image.config.v1+json",
        )
        manifest = blob(
            {"config": config, "layers": []},
            "application/vnd.oci.image.manifest.v1+json",
        )
        if missing_manifest:
            blobs.pop(manifest["digest"], None)
        manifests.append(
            {**manifest, "platform": {"os": "linux", "architecture": arch}}
        )
    index = blob({"manifests": manifests}, index_type)
    digest = index["digest"]
    if corrupt:
        blobs[digest] += b" "
    root = json.dumps({"manifests": [index]}).encode()
    with tarfile.open(path, "w") as archive:
        for name, data in [
            ("index.json", root),
            *(
                ("blobs/" + key.replace(":", "/", 1), data)
                for key, data in blobs.items()
            ),
        ]:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return digest


def test_verifies_exact_multiarch_index_digest(tmp_path):
    artifact = tmp_path / "image.tar"
    expected = make_archive(artifact, ["amd64", "arm64"])
    assert release.verified_digest(artifact) == expected


@pytest.mark.parametrize(
    "archs, corrupt", [(["amd64"], False), (["amd64", "arm64"], True)]
)
def test_refuses_invalid_release_artifact(tmp_path, archs, corrupt):
    artifact = tmp_path / "image.tar"
    make_archive(artifact, archs, corrupt=corrupt)
    with pytest.raises(ValueError):
        release.verified_digest(artifact)


@pytest.mark.parametrize("fault", ["wrong_config", "missing_manifest"])
def test_refuses_unverified_platform_descriptors(tmp_path, fault):
    artifact = tmp_path / "image.tar"
    make_archive(artifact, ["amd64", "arm64"], **{fault: True})
    with pytest.raises(ValueError):
        release.verified_digest(artifact)
