# PyInstaller spec: builds engram.exe, for people who do not have Python.
#
#     pip install pyinstaller
#     pyinstaller engram.spec
#
# The result is dist/engram.exe. It is a console program, so `engram gui` still works and
# the error messages still have somewhere to go.

block_cipher = None

analysis = Analysis(
    ["run_engram.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["engram.gui", "tkinter", "tkinter.ttk", "tkinter.messagebox"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "pandas", "matplotlib", "PIL", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

archive = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="engram",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
