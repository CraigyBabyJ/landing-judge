# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('templates', 'templates'),
        # Explicitly include icon.png to ensure it exists in dist/static/icons
        ('static/icons/icon.png', 'static/icons'),
        # Ensure default quotes are available in the EXE for full messages
        ('quotes.default.json', '.')
    ],
    hiddenimports=['markupsafe._speedups'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Generate a multi-size ICO from the PNG so Windows can display larger icons
try:
    from PIL import Image
    import os
    os.makedirs('build', exist_ok=True)
    _png_icon = 'static/icons/icon.png'
    _ico_out = os.path.join('build', 'app-icon.ico')
    img = Image.open(_png_icon).convert('RGBA')
    img.save(_ico_out, format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    _icon_path = _ico_out
except Exception:
    _icon_path = 'static/icons/icon.png'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LandingJudge',
    icon=_icon_path,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LandingJudge',
)
