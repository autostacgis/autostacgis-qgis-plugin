import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / "dist").mkdir(exist_ok=True)
with zipfile.ZipFile(root / "dist/autostacgis-qgis.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for path in (root / "autostacgis_qgis").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(root))
print(root / "dist/autostacgis-qgis.zip")
