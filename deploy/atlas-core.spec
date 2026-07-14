# PyInstaller spec — freeze the ATLAS FastAPI core into a single binary that the
# Tauri shell runs as a sidecar (so end users need no Python). Build:
#   pyinstaller --clean -y deploy/atlas-core.spec
# The heavy optional native-audio deps (onnxruntime/whisper/sounddevice) are NOT
# bundled here — the shell ships with chat + browser voice; native audio is an
# opt-in local install, mirroring how Kokoro is optional.
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.dirname(SPECPATH)          # repo root (spec lives in deploy/)


def _p(rel):
    return os.path.join(ROOT, rel)


datas = []
# Bundled, non-gitignored assets the server serves / reads on a fresh run:
datas += [(_p("atlas/interface/web"), "atlas/interface/web")]
datas += [(_p("atlas/config/settings.example.json"), "atlas/config")]
datas += [(_p("atlas/connectors/registry.example.json"), "atlas/connectors")]
datas += [(_p("atlas/VERSION.json"), "atlas")]
datas += [(_p("atlas/core"), "atlas/core")]
datas += [(_p("atlas/memory/vault"), "atlas/memory/vault")]
datas += [(_p("atlas/orchestration/config.json"), "atlas/orchestration")]
datas += collect_data_files("anthropic")

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("anthropic")
hiddenimports += ["atlas.server.app", "atlas.server.__main__"]

a = Analysis(
    [_p("deploy/atlas_core_entry.py")],   # absolute-import launcher (keeps package context)
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "onnxruntime", "pywhispercpp", "openwakeword"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="atlas-core",
    console=True,          # stdout carries the ATLAS_READY line the shell reads
    strip=False,
    upx=False,
    target_arch=None,
)
