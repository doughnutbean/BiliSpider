# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


project_root = Path(SPECPATH).parent
if project_root.name == "packaging":
    project_root = project_root.parent

datas = []
datas += collect_data_files("certifi")
datas += collect_data_files("curl_cffi")
datas += copy_metadata("curl_cffi")
datas += copy_metadata("qrcode")
datas += copy_metadata("Pillow")
datas += copy_metadata("openpyxl")
datas += copy_metadata("jieba")
datas += copy_metadata("wordcloud")

binaries = []
binaries += collect_dynamic_libs("curl_cffi")

hiddenimports = []
hiddenimports += [
    "curl_cffi.requests",
    "curl_cffi._wrapper",
    "PIL.Image",
    "PIL.ImageTk",
    "qrcode",
    "qrcode.image.pil",
    "openpyxl",
    "jieba",
    "wordcloud",
    "wordcloud.wordcloud",
]


def _keep_packaged_data(item):
    target = str(item[0]).replace("\\", "/").lower()
    source = str(item[1]).replace("\\", "/").lower() if len(item) > 1 else ""
    combined = f"{target} {source}"
    blocked = (
        "/data/",
        "comments.db",
        "cookies.json",
        "config.json",
        "crawl_queue.json",
        "wordcloud_stopwords.txt",
        ".jsonl",
        "datasets/",
        "jieba/analyse/",
        "jieba/posseg/",
        "jieba/lac_small/",
    )
    return not any(part in combined for part in blocked)


a = Analysis(
    [str(project_root / "gui.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "black",
        "docutils",
        "matplotlib",
        "notebook",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "pytest",
        "sphinx",
    ],
    noarchive=False,
    optimize=0,
)
a.datas = [item for item in a.datas if _keep_packaged_data(item)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BiliSpider",
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
    name="BiliSpider",
)
