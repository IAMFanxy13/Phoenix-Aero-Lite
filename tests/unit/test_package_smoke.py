def test_package_exposes_version():
    import phoenix_aero_lite

    assert phoenix_aero_lite.__version__ == "0.1.0.dev0"


def test_pep639_license_expression_does_not_mix_deprecated_license_classifier():
    from pathlib import Path
    import tomllib

    project = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["license"] == "GPL-3.0-or-later"
    assert not any(
        classifier.startswith("License ::")
        for classifier in project.get("classifiers", ())
    )
