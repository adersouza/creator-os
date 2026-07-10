from pathlib import Path

from PIL import Image
from reel_factory.perceptual import ALGORITHM, enrich_lineage_identity, media_identity


def test_image_identity_is_real_deterministic_phash(tmp_path: Path):
    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (64, 64), "white")
    for x in range(16, 48):
        for y in range(20, 44):
            image.putpixel((x, y), (20, 40, 180))
    image.save(image_path)

    first = media_identity(image_path)
    second = media_identity(image_path)

    assert first == second
    assert first["perceptualAlgorithm"] == ALGORITHM
    assert first["perceptualFingerprint"].startswith("phash64:")
    assert len(first["contentFingerprint"]) == 64


def test_source_family_is_carried_from_learning_lineage(tmp_path: Path):
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (32, 32), "black").save(image_path)

    enriched = enrich_lineage_identity(
        {"schema": "reel_factory.generated_asset_lineage.v1"},
        image_path,
        source_lineage={"learning": {"clusterKey": "gold-cluster-7"}},
    )

    assert enriched["sourceFamilyId"] == "gold-cluster-7"
