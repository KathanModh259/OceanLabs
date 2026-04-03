# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],  # Changed to app.py
    pathex=['.'],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('resemblyzer_model/pretrained.pt', 'resemblyzer_model')
    ],
    hiddenimports=[
        'resemblyzer',
        'faster_whisper',
        'indicnlp',
        'sounddevice',
        'scipy.io',
        'scipy.signal', # Often a scipy hidden dependency
        'requests'
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TranscriberApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True, # Ensures console window appears for CLI interaction
    icon='icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TranscriberApp'
)