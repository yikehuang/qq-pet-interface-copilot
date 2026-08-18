# -*- mode: python ; coding: utf-8 -*-
"""macOS 打包配置：单进程入口 main.py（菜单栏图标 + 主窗口 + 调度同进程）。"""

from PyInstaller.utils.hooks import collect_data_files

frida_tools_data = collect_data_files("frida_tools", includes=["bridges/java.js"])
frida_java_fallback = [(source, "hooks") for source, _destination in frida_tools_data]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("hooks/qqpet_mobile_read_agent.js", "hooks")] + frida_tools_data + frida_java_fallback,
    hiddenimports=[
        "encodings.idna",
        "frida",
        "frida_tools",
        "menubar_integration",
        "onepush",
        "onepush.providers.bark",
        "onepush.providers.pushplus",
        "onepush.providers.serverchanturbo",
        "onepush.providers.smtp",
        "onepush.providers.custom",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QQPetAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    name="QQPetAssistant",
)
app = BUNDLE(
    coll,
    name="QQ宠物助手.app",
    icon=None,
    bundle_identifier="com.qqpet.interfacecopilot",
    info_plist={
        "LSUIElement": True,  # 纯菜单栏，不占 Dock、无主窗口
        "NSHighResolutionCapable": True,
        "CFBundleDisplayName": "QQ宠物助手",
        "CFBundleName": "QQ宠物助手",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
    },
)
