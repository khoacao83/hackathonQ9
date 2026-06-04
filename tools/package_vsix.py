from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile


CONTENT_TYPES_XML = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"json\" ContentType=\"application/json\" />
  <Default Extension=\"js\" ContentType=\"application/javascript\" />
  <Default Extension=\"md\" ContentType=\"text/markdown\" />
  <Default Extension=\"txt\" ContentType=\"text/plain\" />
  <Default Extension=\"xml\" ContentType=\"text/xml\" />
  <Override PartName=\"/extension.vsixmanifest\" ContentType=\"text/xml\" />
</Types>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package a VS Code extension folder into a .vsix archive.",
    )
    parser.add_argument(
        "--extension-dir",
        default="tools/copilot-lm-bridge-extension",
        help="Path to the extension root containing package.json.",
    )
    parser.add_argument(
        "--output",
        default="dist/copilot-lm-bridge-extension.vsix",
        help="Output .vsix path.",
    )
    return parser.parse_args()


def load_package_json(extension_dir: Path) -> dict:
    package_json = extension_dir / "package.json"
    return json.loads(package_json.read_text(encoding="utf-8"))


def build_vsix_manifest(package: dict) -> str:
    publisher = escape(package["publisher"])
    name = escape(package["name"])
    version = escape(package["version"])
    display_name = escape(package.get("displayName", package["name"]))
    description = escape(package.get("description", ""))
    engine = escape(package.get("engines", {}).get("vscode", "*"))
    categories = ", ".join(package.get("categories", []))

    assets = [
        '    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />',
    ]

    if package.get("main"):
        assets.append(
            '    <Asset Type="Microsoft.VisualStudio.Services.Content" Path="extension/extension.js" Addressable="true" />'
        )

    return f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
<PackageManifest Version=\"2.0.0\" xmlns=\"http://schemas.microsoft.com/developer/vsx-schema/2011\">
  <Metadata>
    <Identity Id=\"{publisher}.{name}\" Version=\"{version}\" Publisher=\"{publisher}\" Language=\"en-US\" />
    <DisplayName>{display_name}</DisplayName>
    <Description xml:space=\"preserve\">{description}</Description>
    <Categories>{escape(categories)}</Categories>
    <Properties>
      <Property Id=\"Microsoft.VisualStudio.Code.Engine\" Value=\"{engine}\" />
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id=\"Microsoft.VisualStudio.Code\" />
  </Installation>
  <Dependencies />
  <Assets>
{chr(10).join(assets)}
  </Assets>
</PackageManifest>
"""


def iter_extension_files(extension_dir: Path):
    ignored_names = {".git", ".gitignore", ".vscode", "__pycache__"}
    ignored_suffixes = {".pyc", ".pyo", ".vsix"}

    for path in sorted(extension_dir.rglob("*")):
        if path.is_dir():
            continue
        if any(part in ignored_names for part in path.parts):
            continue
        if path.suffix.lower() in ignored_suffixes:
            continue
        yield path


def build_vsix(extension_dir: Path, output_path: Path) -> Path:
    package = load_package_json(extension_dir)
    manifest = build_vsix_manifest(package)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("extension.vsixmanifest", manifest)

        for file_path in iter_extension_files(extension_dir):
            archive.write(file_path, Path("extension") / file_path.relative_to(extension_dir))

    return output_path


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    extension_dir = (repo_root / args.extension_dir).resolve()
    output_path = (repo_root / args.output).resolve()

    if not extension_dir.exists():
        raise SystemExit(f"Extension directory not found: {extension_dir}")
    if not (extension_dir / "package.json").exists():
        raise SystemExit(f"package.json not found under: {extension_dir}")

    vsix_path = build_vsix(extension_dir, output_path)
    print(vsix_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())