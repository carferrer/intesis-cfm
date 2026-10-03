"""Build a HACS ZIP with integration files at the archive root."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", help="Require this release tag to match manifest.version"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "custom_components" / "intesisbox"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((root / "hacs.json").read_text(encoding="utf-8"))
    if args.tag and args.tag.removeprefix("v") != manifest["version"]:
        parser.error("Release tag must match manifest.json version")
    if hacs["filename"] != "intesisbox.zip" or not hacs["zip_release"]:
        parser.error("HACS archive configuration does not match the build")
    target = root / "dist" / hacs["filename"]
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".json", ".png"}:
                continue
            if path.name == "IntesisBoxEmulator.py":
                continue
            bundle.write(path, path.relative_to(source).as_posix())
        bundle.write(root / "LICENSE", "LICENSE")
    with ZipFile(target) as bundle:
        names = set(bundle.namelist())
        required = {
            "__init__.py",
            "manifest.json",
            "climate.py",
            "config_flow.py",
            "translations/en.json",
            "translations/es.json",
            "brand/icon.png",
            "LICENSE",
        }
        if missing := required - names:
            raise RuntimeError(f"Missing integration files: {sorted(missing)}")
        if any(
            name.startswith("custom_components/") or "__pycache__" in name
            for name in names
        ):
            raise RuntimeError("Incorrect HACS ZIP layout")
        if bundle.testzip() is not None:
            raise RuntimeError("Corrupt ZIP")
    print(
        f"Built and verified {target.name}: {len(names)} files, version {manifest['version']}"
    )


if __name__ == "__main__":
    main()
