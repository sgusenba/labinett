# PyInstaller-Build:  pyinstaller labinett.spec
# Ergebnis: dist/labinett.exe (eine Datei). labinett.json und ergebnisse.csv
# werden beim ersten Start neben der .exe angelegt.
a = Analysis(
    ["start.py"],
    datas=[("labinett/static", "labinett/static")],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="labinett",
    console=True,
    upx=False,
)
