"""Verify the exact OCI index to publish and assign its commit-based tag."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

BASE = "f6fd6dc61040c6eb94019e8721cdb909a4f926a4"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
PLATFORMS = [("linux", "amd64"), ("linux", "arm64")]


def release_tag(first_parent_history, base=BASE):
    distance = first_parent_history.index(base)
    if not distance:
        raise ValueError("The release commit must follow the publication baseline")
    return f"docker-v0.13.{distance - 1}"


def _read(archive, path):
    try:
        handle = archive.extractfile(path)
    except KeyError as exc:
        raise ValueError(f"Missing OCI member: {path}") from exc
    if handle is None:
        raise ValueError(f"Invalid OCI member: {path}")
    with handle:
        return handle.read()


def _read_descriptor(archive, descriptor, media_type):
    digest = descriptor["digest"]
    if descriptor["mediaType"] != media_type or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", digest
    ):
        raise ValueError(f"Invalid OCI descriptor for {media_type}")
    content = _read(archive, "blobs/" + digest.replace(":", "/", 1))
    if "sha256:" + hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"The OCI digest does not match the archive: {digest}")
    return json.loads(content)


def verified_digest(path):
    with tarfile.open(path) as archive:
        [descriptor] = json.loads(_read(archive, "index.json"))["manifests"]
        index = _read_descriptor(archive, descriptor, OCI_INDEX)
        platforms = []
        for entry in index["manifests"]:
            platform = entry["platform"]
            pair = (platform["os"], platform["architecture"])
            manifest = _read_descriptor(archive, entry, OCI_MANIFEST)
            config = _read_descriptor(archive, manifest["config"], OCI_CONFIG)
            if pair != (config["os"], config["architecture"]):
                raise ValueError(f"Image config disagrees with descriptor for {pair}")
            platforms.append(pair)
        platforms.sort()
    if platforms != PLATFORMS:
        raise ValueError(f"Expected {PLATFORMS}, got {platforms}")
    return descriptor["digest"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    history = subprocess.check_output(
        ["git", "rev-list", "--first-parent", "HEAD"], text=True
    ).splitlines()
    commit = os.environ["CI_COMMIT_SHA"]
    if history[0] != commit:
        raise SystemExit("The checkout does not match CI_COMMIT_SHA")
    tag = release_tag(history)
    digest = verified_digest(args.archive)
    args.record.write_text(f"{tag}\n{commit}\n{digest}\n", encoding="ascii")
    print(
        f"Verified release candidate: {tag} → {commit} → {digest} (linux/amd64, linux/arm64)"
    )


if __name__ == "__main__":
    main()
