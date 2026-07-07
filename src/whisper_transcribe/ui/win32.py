"""Windows 固有の調整 (DPI・IME・タスクバー・アイコンパス)。

各関数は Windows 以外では何もしない。GUI の動作自体には必須でないため、
失敗しても例外を外へ出さない方針。
"""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Any

APP_USER_MODEL_ID = "Moru.SOTTO"


def icon_path() -> Path:
    """アプリアイコン (.ico) のパスを返す。開発時はパッケージ内、exe では _internal 内。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "whisper_transcribe" / "ui" / "assets" / "icon.ico"
    return Path(__file__).parent / "assets" / "icon.ico"


def enable_dpi_awareness() -> None:
    """プロセスを DPI 対応にする。

    DPI 非対応のままだと表示スケーリング環境で通常の文字は仮想 96DPI で
    拡大描画される一方、IME の変換中文字列は実 DPI で描画されるため、
    変換中だけ文字が大きく見える。Tk 生成前に呼ぶこと。
    """
    if sys.platform != "win32":
        return

    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # noqa per-monitor DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # noqa
        except (AttributeError, OSError):
            pass


def setup_taskbar_identity(root: tk.Misc) -> None:
    """タスクバーへのピン留めでカスタムアイコンが使われるようにする。

    ピン留めのショートカットは既定でプロセス実行ファイルのアイコンを使うため、
    Python ランチャー経由の起動では Tk 既定アイコンになってしまう。
    ウィンドウのプロパティストアに AppUserModelID と Relaunch 情報
    (起動コマンド・表示名・アイコン) を設定して解決する。
    """
    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    # 再起動コマンド: exe ならそれ自身、開発時は venv の sotto-gui.exe
    if getattr(sys, "frozen", False):
        relaunch_exe = Path(sys.executable)
    else:
        relaunch_exe = Path(sys.executable).parent / "sotto-gui.exe"
    icon = icon_path()
    if not (relaunch_exe.exists() and icon.exists()):
        return

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

        def __init__(self, guid_str: str) -> None:
            super().__init__()
            body = guid_str.strip("{}").split("-")
            self.Data1 = int(body[0], 16)
            self.Data2 = int(body[1], 16)
            self.Data3 = int(body[2], 16)
            rest = bytes.fromhex(body[3] + body[4])
            for i, b in enumerate(rest):
                self.Data4[i] = b

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", wintypes.USHORT),
            ("wReserved1", wintypes.USHORT),
            ("wReserved2", wintypes.USHORT),
            ("wReserved3", wintypes.USHORT),
            ("pwszVal", ctypes.c_wchar_p),
            ("_pad", ctypes.c_void_p),
        ]

    VT_LPWSTR = 31
    PKEY_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"  # System.AppUserModel.*
    props: list[tuple[int, str]] = [
        (5, APP_USER_MODEL_ID),  # ID
        (2, f'"{relaunch_exe}"'),  # RelaunchCommand
        (4, "SOTTO"),  # RelaunchDisplayNameResource
        (3, str(icon)),  # RelaunchIconResource
    ]

    try:
        ctypes.windll.ole32.CoInitialize(None)  # noqa
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)  # noqa

        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)  # noqa GA_ROOT
        iid = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")  # IID_IPropertyStore
        store = ctypes.c_void_p()
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(  # noqa
            hwnd, ctypes.byref(iid), ctypes.byref(store)
        )
        if hr != 0 or not store:
            return

        # IPropertyStore vtable: 6=SetValue, 7=Commit, 2=Release
        vtbl = ctypes.cast(
            ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )
        set_value = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p,
            ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT),
        )(vtbl[6])
        commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])

        try:
            for pid, value in props:
                key = PROPERTYKEY(GUID(PKEY_FMTID), pid)
                var = PROPVARIANT()
                var.vt = VT_LPWSTR
                var.pwszVal = value
                set_value(store, ctypes.byref(key), ctypes.byref(var))
            commit(store)
        finally:
            release(store)
    except (OSError, AttributeError):
        pass  # 失敗してもアプリ動作には影響しない


def bind_ime_font_fix(widget: tk.Widget) -> None:
    """IME の変換中文字列のフォントをウィジェットに合わせる。

    未確定文字列は IME が独自の「コンポジションフォント」で描画するため、
    何もしないとウィジェットの文字と大きさが揃わない。フォーカス取得時に
    ImmSetCompositionFontW でウィジェットと同じフォント・ピクセル高を設定する。
    """
    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    class LOGFONTW(ctypes.Structure):
        _fields_ = [
            ("lfHeight", wintypes.LONG),
            ("lfWidth", wintypes.LONG),
            ("lfEscapement", wintypes.LONG),
            ("lfOrientation", wintypes.LONG),
            ("lfWeight", wintypes.LONG),
            ("lfItalic", wintypes.BYTE),
            ("lfUnderline", wintypes.BYTE),
            ("lfStrikeOut", wintypes.BYTE),
            ("lfCharSet", wintypes.BYTE),
            ("lfOutPrecision", wintypes.BYTE),
            ("lfClipPrecision", wintypes.BYTE),
            ("lfQuality", wintypes.BYTE),
            ("lfPitchAndFamily", wintypes.BYTE),
            ("lfFaceName", ctypes.c_wchar * 32),
        ]

    def apply(_event: Any = None) -> None:
        try:
            spec = widget.cget("font") or "TkTextFont"
            f = tkfont.Font(font=spec)
            family = str(f.actual("family"))
            size = int(f.actual("size"))
            # 正のサイズはポイント。Tk と同じ換算でピクセル高に変換する
            px = abs(size) if size < 0 else round(widget.winfo_fpixels(f"{size}p"))

            imm32 = ctypes.windll.imm32
            hwnd = widget.winfo_id()

            himc = imm32.ImmGetContext(hwnd)  # noqa
            if not himc:
                return
            try:
                lf = LOGFONTW()
                lf.lfHeight = -int(px)
                lf.lfCharSet = 1  # DEFAULT_CHARSET
                lf.lfFaceName = family[:31]
                imm32.ImmSetCompositionFontW(himc, ctypes.byref(lf))  # noqa
            finally:
                imm32.ImmReleaseContext(hwnd, himc)  # noqa
        except Exception:  # noqa: BLE001 - IME調整の失敗は入力自体には影響しない
            pass

    widget.bind("<FocusIn>", apply, add="+")
