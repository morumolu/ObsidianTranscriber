import math
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Any, Callable, cast

import ttkbootstrap as tb
from tkinterdnd2 import DND_FILES, TkinterDnD

from .config import (
    get_bool,
    get_record_filename_format,
    get_recording_cache_limit,
    get_recordings_cache_dir,
    get_str,
    get_vault_dir,
    set_record_filename_format,
    set_recording_cache_limit,
    set_value,
    set_vault_dir,
)
from .i18n import LANGUAGES, get_language, init_language, save_language, tr
from .model_cache import CachedModel, delete_cached_model, format_size, list_cached_models
from .model_size import ModelSize
from .recorder import SAMPLE_RATE, Recorder, RecorderError
from .runner import (
    SUPPORTED_EXTENSIONS,
    TranscriptionCancelled,
    transcribe_to_markdown,
    validate_output_path,
)

APP_TITLE = "SOTTO - Speech to Transcribed Obsidian"
APP_VERSION = "0.1.0"

# カラーパレット (ttkbootstrap "minty" テーマ準拠 + ダークなログ領域)
BG = "#ffffff"
SURFACE = "#ffffff"
BORDER = "#dce5e0"
TEXT = "#5a5a5a"
TEXT_MUTED = "#9aa8a1"
ACCENT = "#78c2ad"
DROP_BG = "#eaf7f2"
DROP_ACTIVE_BG = "#d5efe4"
LOG_BG = "#22332d"
LOG_FG = "#d8e2dc"

FONT_UI = ("Yu Gothic UI", 10)
FONT_TITLE = ("Yu Gothic UI", 18, "bold")
FONT_DROP = ("Yu Gothic UI", 11)
FONT_LOG = ("Consolas", 9)

# ワーカースレッドから GUI スレッドへ渡すメッセージ (種別, ペイロード)
Message = tuple[str, object]

# テスト書き起こしで処理する先頭の秒数
TEST_DURATION = 10.0

def icon_path() -> Path:
    """アプリアイコン (.ico) のパスを返す。開発時はパッケージ内、exe では _internal 内。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "whisper_transcribe" / "assets" / "icon.ico"
    return Path(__file__).parent / "assets" / "icon.ico"


APP_USER_MODEL_ID = "Moru.SOTTO"


def setup_taskbar_identity(root: tk.Misc) -> None:
    """タスクバーへのピン留めでカスタムアイコンが使われるようにする (Windows)。

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
        (5, APP_USER_MODEL_ID),               # ID
        (2, f'"{relaunch_exe}"'),             # RelaunchCommand
        (4, "SOTTO"),                         # RelaunchDisplayNameResource
        (3, str(icon)),                       # RelaunchIconResource
    ]

    try:
        ctypes.windll.ole32.CoInitialize(None)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)

        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
        iid = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")  # IID_IPropertyStore
        store = ctypes.c_void_p()
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(
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
    """IME の変換中文字列のフォントをウィジェットに合わせる (Windows)。

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
            himc = imm32.ImmGetContext(hwnd)
            if not himc:
                return
            try:
                lf = LOGFONTW()
                lf.lfHeight = -int(px)
                lf.lfCharSet = 1  # DEFAULT_CHARSET
                lf.lfFaceName = family[:31]
                imm32.ImmSetCompositionFontW(himc, ctypes.byref(lf))
            finally:
                imm32.ImmReleaseContext(hwnd, himc)
        except Exception:  # noqa: BLE001 - IME調整の失敗は入力自体には影響しない
            pass

    widget.bind("<FocusIn>", apply, add="+")


# 録音の保存フォーマット (拡張子, 表示名)。メニューと保存ダイアログで共用
def record_formats() -> list[tuple[str, str]]:
    return [
        (".mp3", "MP3"),
        (".ogg", "OGG Vorbis"),
        (".flac", tr("fmt_flac")),
        (".wav", tr("fmt_wav")),
    ]


class WhisperGui:
    """音声ファイルをドラッグ&ドロップして文字起こしする GUI。"""

    def __init__(self, root: TkinterDnD.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x700")
        self.root.minsize(600, 540)
        self.root.configure(bg=BG)
        try:
            # default= で以後の Toplevel (プレビュー等) にも適用される
            self.root.iconbitmap(default=str(icon_path()))
        except tk.TclError:
            pass  # アイコンが無くても起動は継続

        self.input_path: Path | None = None
        self.msg_queue: queue.Queue[Message] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.recorder = Recorder()
        self._record_timer: str | None = None
        self.record_format_var = tk.StringVar(value=get_str("record_format", ".mp3"))
        self.auto_transcribe_var = tk.BooleanVar(value=get_bool("auto_transcribe", False))
        self.ui_language_var = tk.StringVar(value=get_language())
        self.cancel_event: threading.Event | None = None

        self._setup_style()
        self._build_menu()
        self._build_widgets()
        self._bind_setting_persistence()
        self.root.update_idletasks()
        setup_taskbar_identity(self.root)
        self.root.after(100, self._poll_queue)

    def _bind_setting_persistence(self) -> None:
        """設定項目の変更を config に保存し、次回起動時に復元できるようにする。"""
        persist: list[tuple[tk.Variable, str]] = [
            (self.record_format_var, "record_format"),
            (self.model_var, "model_size"),
            (self.language_var, "audio_language"),
            (self.timestamps_var, "timestamps"),
            (self.auto_transcribe_var, "auto_transcribe"),
        ]
        for var, key in persist:
            var.trace_add("write", lambda *_a, v=var, k=key: set_value(k, v.get()))

    # ---------------------------------------------------------------- style
    def _setup_style(self) -> None:
        style = tb.Style(theme="minty")

        # アプリ全体の既定フォントを Yu Gothic UI に統一
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family="Yu Gothic UI", size=10)

        style.configure("Muted.TLabel", foreground=TEXT_MUTED, font=FONT_UI)
        style.configure("AppTitle.TLabel", foreground=ACCENT, font=FONT_TITLE)
        style.configure("Treeview", rowheight=26)
        self.root.configure(bg=style.colors.bg)

    # ----------------------------------------------------------------- menu
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(
            label=tr("menu_open_audio"), accelerator="Ctrl+O", command=self._browse_input
        )
        file_menu.add_command(
            label=tr("menu_set_output"), accelerator="Ctrl+S", command=self._browse_output
        )
        file_menu.add_separator()
        file_menu.add_command(label=tr("menu_quit"), accelerator="Ctrl+Q", command=self.root.destroy)
        menubar.add_cascade(label=tr("menu_file"), menu=file_menu)

        tool_menu = tk.Menu(menubar, tearoff=False)
        tool_menu.add_command(label=tr("menu_start"), accelerator="F5", command=self._start)
        tool_menu.add_command(
            label=tr("menu_test", sec=f"{TEST_DURATION:.0f}"),
            command=lambda: self._start(test=True),
        )
        tool_menu.add_command(label=tr("menu_cancel"), accelerator="Esc", command=self._cancel)
        tool_menu.add_command(
            label=tr("menu_record_toggle"), accelerator="Ctrl+R", command=self._toggle_record
        )
        tool_menu.add_separator()
        tool_menu.add_command(label=tr("menu_cache"), command=self._open_cache_dialog)
        tool_menu.add_command(
            label=tr("menu_open_recording_cache"), command=self._open_recording_cache_dir
        )
        tool_menu.add_separator()
        tool_menu.add_command(label=tr("menu_clear_log"), command=self._clear_log)
        menubar.add_cascade(label=tr("menu_tools"), menu=tool_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        format_menu = tk.Menu(settings_menu, tearoff=False)
        for ext, label in record_formats():
            format_menu.add_radiobutton(
                label=f"{label} ({ext})", value=ext, variable=self.record_format_var
            )
        settings_menu.add_cascade(label=tr("menu_record_format"), menu=format_menu)
        settings_menu.add_command(
            label=tr("menu_record_filename"), command=self._set_record_filename_format
        )
        settings_menu.add_command(label=tr("menu_vault"), command=self._set_vault_dir)
        settings_menu.add_command(
            label=tr("menu_recording_cache_limit"), command=self._set_recording_cache_limit
        )
        settings_menu.add_checkbutton(
            label=tr("menu_auto_transcribe"), variable=self.auto_transcribe_var
        )
        settings_menu.add_separator()
        language_menu = tk.Menu(settings_menu, tearoff=False)
        for code, name in LANGUAGES:
            language_menu.add_radiobutton(
                label=name,
                value=code,
                variable=self.ui_language_var,
                command=self._change_language,
            )
        settings_menu.add_cascade(label=tr("menu_language"), menu=language_menu)
        menubar.add_cascade(label=tr("menu_settings"), menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label=tr("menu_about"), command=self._show_about)
        menubar.add_cascade(label=tr("menu_help"), menu=help_menu)

        self.root.config(menu=menubar)

        self.root.bind_all("<Control-o>", lambda _e: self._browse_input())
        self.root.bind_all("<Control-s>", lambda _e: self._browse_output())
        self.root.bind_all("<Control-q>", lambda _e: self.root.destroy())
        self.root.bind_all("<Control-r>", lambda _e: self._toggle_record())
        self.root.bind_all("<F5>", lambda _e: self._start())
        self.root.bind_all("<Escape>", lambda _e: self._cancel())

    def _change_language(self) -> None:
        save_language(self.ui_language_var.get())
        messagebox.showinfo(tr("lang_restart_title"), tr("lang_restart_msg"))

    def _set_record_filename_format(self) -> None:
        current = get_record_filename_format()
        fmt = simpledialog.askstring(
            tr("dlg_filename_format_title"),
            tr("dlg_filename_format_prompt", example=datetime.now().strftime("%Y%m%d_%H%M")),
            initialvalue=current,
            parent=self.root,
        )
        if not fmt or fmt == current:
            return
        try:
            example = datetime.now().strftime(fmt)
            invalid = set('<>:"/\\|?*') & set(example)
            if invalid or not example.strip():
                raise ValueError(f"invalid characters: {' '.join(sorted(invalid)) or 'empty'}")
        except ValueError as exc:
            messagebox.showerror(
                tr("dlg_filename_format_invalid_title"),
                tr("dlg_filename_format_invalid_msg", msg=exc),
            )
            return
        set_record_filename_format(fmt)
        self._append_log(tr("log_filename_format_set", fmt=fmt, example=example))

    def _set_vault_dir(self) -> None:
        current = get_vault_dir()
        path_str = filedialog.askdirectory(
            title=tr("dlg_vault_title"),
            initialdir=str(current) if current else "",
        )
        if not path_str:
            return
        set_vault_dir(Path(path_str))
        self._append_log(tr("log_vault_set", path=path_str))

    def _set_recording_cache_limit(self) -> None:
        limit = simpledialog.askinteger(
            tr("dlg_recording_cache_limit_title"),
            tr("dlg_recording_cache_limit_prompt", dir=get_recordings_cache_dir()),
            initialvalue=get_recording_cache_limit(),
            minvalue=1,
            maxvalue=999,
            parent=self.root,
        )
        if limit is None or limit == get_recording_cache_limit():
            return
        set_recording_cache_limit(limit)
        self._append_log(tr("log_recording_cache_limit_set", limit=limit))
        self._prune_recording_cache()

    def _show_about(self) -> None:
        messagebox.showinfo(tr("about_title"), tr("about_text", version=APP_VERSION))

    # ------------------------------------------------------------------- UI
    def _build_widgets(self) -> None:
        # ヘッダー (アプリ名 + サブタイトル)
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(14, 4))
        ttk.Label(header, text="SOTTO", style="AppTitle.TLabel").pack(side="left")
        ttk.Label(header, text="Speech to Transcribed Obsidian", style="Muted.TLabel").pack(
            side="left", padx=(10, 0), pady=(10, 0)
        )

        # ドロップゾーン
        self.drop_zone = tk.Label(
            self.root,
            text=tr("drop_zone", exts=", ".join(sorted(SUPPORTED_EXTENSIONS))),
            relief="flat",
            height=4,
            bg=DROP_BG,
            fg=ACCENT,
            font=FONT_DROP,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.drop_zone.pack(fill="x", padx=16, pady=(8, 12))
        dnd_zone = cast(Any, self.drop_zone)
        dnd_zone.drop_target_register(DND_FILES)
        dnd_zone.dnd_bind("<<Drop>>", self._on_drop)
        dnd_zone.dnd_bind("<<DropEnter>>", self._on_drop_enter)
        dnd_zone.dnd_bind("<<DropLeave>>", self._on_drop_leave)

        # 入出力 (グリッドで揃える)
        io_frame = ttk.Frame(self.root)
        io_frame.pack(fill="x", padx=16, pady=2)
        io_frame.columnconfigure(1, weight=1)

        ttk.Label(io_frame, text=tr("label_input"), style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=4
        )
        self.input_var = tk.StringVar(value=tr("not_selected"))
        ttk.Label(io_frame, textvariable=self.input_var, foreground=ACCENT).grid(
            row=0, column=1, sticky="w"
        )

        ttk.Label(io_frame, text=tr("label_output"), style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=4
        )
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(io_frame, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew")
        bind_ime_font_fix(self.output_entry)

        # オプション行
        opt_frame = ttk.Frame(self.root)
        opt_frame.pack(fill="x", padx=16, pady=(10, 4))

        ttk.Label(opt_frame, text=tr("label_model"), style="Muted.TLabel").pack(side="left")
        saved_model = get_str("model_size", ModelSize.large_v3.value)
        if saved_model not in {m.value for m in ModelSize}:
            saved_model = ModelSize.large_v3.value
        self.model_var = tk.StringVar(value=saved_model)
        model_box = ttk.Combobox(
            opt_frame,
            textvariable=self.model_var,
            values=[m.value for m in ModelSize],
            state="readonly",
            width=16,
        )
        model_box.pack(side="left", padx=(6, 16))

        ttk.Label(opt_frame, text=tr("label_language"), style="Muted.TLabel").pack(side="left")
        self.language_var = tk.StringVar(value=get_str("audio_language", "ja"))
        ttk.Entry(opt_frame, textvariable=self.language_var, width=6).pack(side="left", padx=(6, 16))

        self.timestamps_var = tk.BooleanVar(value=get_bool("timestamps", False))
        tb.Checkbutton(
            opt_frame,
            text=tr("check_timestamps"),
            variable=self.timestamps_var,
            bootstyle="success-round-toggle",
        ).pack(side="left")

        # 実行ボタン + 録音ボタン + レベルメータ
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=16, pady=12)
        self.record_button = tb.Button(
            action_frame,
            text=tr("btn_record_start"),
            bootstyle="danger-outline",
            command=self._toggle_record,
        )
        self.record_button.pack(side="left", padx=(0, 8), ipady=2)
        self.level_meter = tb.Progressbar(
            action_frame,
            bootstyle="info",
            mode="determinate",
            maximum=100,
            length=110,
        )
        self.level_meter.pack(side="left", padx=(0, 12))
        self.run_button = tb.Button(
            action_frame,
            text=tr("btn_start"),
            bootstyle="success",
            command=self._start,
        )
        self.run_button.pack(side="left", fill="x", expand=True, ipady=2)
        self.test_button = tb.Button(
            action_frame,
            text=tr("btn_test", sec=f"{TEST_DURATION:.0f}"),
            bootstyle="success-outline",
            command=lambda: self._start(test=True),
        )
        self.test_button.pack(side="left", padx=(8, 0), ipady=2)
        self.cancel_button = tb.Button(
            action_frame,
            text=tr("btn_cancel"),
            bootstyle="secondary-outline",
            state="disabled",
            command=self._cancel,
        )
        self.cancel_button.pack(side="left", padx=(8, 0), ipady=2)

        # 進捗バー + ステータス
        self.progress = tb.Progressbar(
            self.root, bootstyle="success-striped", mode="determinate", maximum=100
        )
        self.progress.pack(fill="x", padx=16, pady=(0, 4))
        self.status_var = tk.StringVar(value=tr("status_idle"))
        ttk.Label(self.root, textvariable=self.status_var, style="Muted.TLabel").pack(
            anchor="w", padx=16
        )

        # 処理ログ
        ttk.Label(self.root, text=tr("label_log"), style="Muted.TLabel").pack(
            anchor="w", padx=16, pady=(10, 0)
        )
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(4, 14))
        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            height=12,
            state="disabled",
            bg=LOG_BG,
            fg=LOG_FG,
            font=FONT_LOG,
            relief="flat",
            padx=10,
            pady=8,
            insertbackground=LOG_FG,
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ------------------------------------------------------------ file input
    def _on_drop_enter(self, _event: Any) -> None:
        self.drop_zone.configure(bg=DROP_ACTIVE_BG)

    def _on_drop_leave(self, _event: Any) -> None:
        self.drop_zone.configure(bg=DROP_BG)

    def _on_drop(self, event: Any) -> None:
        self.drop_zone.configure(bg=DROP_BG)
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        self._set_input(Path(paths[0]))
        if len(paths) > 1:
            self._append_log(tr("log_multi_drop"))

    def _browse_input(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        path = filedialog.askopenfilename(
            title=tr("dlg_select_audio"),
            filetypes=[(tr("ft_audio"), exts), (tr("ft_all"), "*.*")],
        )
        if path:
            self._set_input(Path(path))

    def _set_input(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            messagebox.showwarning(
                tr("dlg_unsupported_title"),
                tr(
                    "dlg_unsupported_msg",
                    ext=path.suffix,
                    supported=", ".join(sorted(SUPPORTED_EXTENSIONS)),
                ),
            )
            return
        self.input_path = path
        self.input_var.set(str(path))
        self.output_var.set(str(self._default_output_for(path)))

    @staticmethod
    def _default_output_for(path: Path) -> Path:
        """デフォルトの Markdown 出力先を返す。

        録音キャッシュ由来の入力は Vault フォルダへ (成果物の md だけが Vault に残る)。
        それ以外 (D&D や参照で選んだファイル) は入力と同じ場所。
        """
        vault = get_vault_dir()
        if vault is not None and path.parent == get_recordings_cache_dir():
            return vault / path.with_suffix(".md").name
        return path.with_suffix(".md")

    def _browse_output(self) -> None:
        initial = Path(self.output_var.get()) if self.output_var.get() else None
        path = filedialog.asksaveasfilename(
            title=tr("dlg_select_output"),
            defaultextension=".md",
            filetypes=[(tr("ft_markdown"), "*.md"), (tr("ft_all"), "*.*")],
            initialfile=initial.name if initial else "",
            initialdir=str(initial.parent) if initial else "",
        )
        if path:
            self.output_var.set(path)

    # ------------------------------------------------------------- recording
    def _toggle_record(self) -> None:
        if self.recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(tr("dlg_busy_title"), tr("dlg_busy_msg"))
            return
        try:
            self.recorder.start()
        except RecorderError as exc:
            messagebox.showerror(tr("dlg_record_error_title"), str(exc))
            return
        self.record_button.configure(text=tr("btn_record_stop"), bootstyle="danger")
        self.run_button.configure(state="disabled")
        self._append_log(tr("log_record_start"))
        self._update_record_elapsed()

    def _update_record_elapsed(self) -> None:
        if not self.recorder.is_recording:
            return
        self.status_var.set(tr("status_recording", sec=f"{self.recorder.elapsed_seconds:.0f}"))
        # RMS を dB (-60〜0) に変換し 0〜100% で表示
        level = self.recorder.level
        db = 20.0 * math.log10(level) if level > 0 else -60.0
        pct = max(0.0, min(100.0, (db + 60.0) / 60.0 * 100.0))
        self.level_meter.configure(value=pct)
        self._record_timer = self.root.after(100, self._update_record_elapsed)

    def _stop_recording(self) -> None:
        if self._record_timer is not None:
            self.root.after_cancel(self._record_timer)
            self._record_timer = None

        data = self.recorder.stop()
        self.record_button.configure(text=tr("btn_record_start"), bootstyle="danger-outline")
        self.run_button.configure(state="normal")
        self.level_meter.configure(value=0)
        self.status_var.set(tr("status_idle"))

        if len(data) == 0:
            self._append_log(tr("log_record_none"))
            return

        duration = len(data) / SAMPLE_RATE
        ext = self.record_format_var.get()
        name = datetime.now().strftime(get_record_filename_format()) + ext
        # 録音は中間生成物としてキャッシュへ自動保存する (成果物は Markdown)
        target = self._unique_path(get_recordings_cache_dir() / name)

        try:
            path = Recorder.save(target, data)
        except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
            messagebox.showerror(tr("dlg_save_error_title"), tr("dlg_save_error_msg", msg=exc))
            return
        self._append_log(tr("log_record_saved", path=path, sec=f"{duration:.1f}"))
        self._prune_recording_cache()
        self._set_input(path)
        if self.auto_transcribe_var.get():
            self._start(auto=True)

    def _prune_recording_cache(self) -> None:
        """録音キャッシュが上限を超えていたら古い順に削除する。"""
        limit = get_recording_cache_limit()
        files = sorted(
            (f for f in get_recordings_cache_dir().iterdir() if f.is_file()),
            key=lambda f: f.stat().st_mtime,
        )
        for f in files[: max(0, len(files) - limit)]:
            try:
                f.unlink()
                self._append_log(tr("log_recording_pruned", name=f.name))
            except OSError as exc:
                self._append_log(tr("log_recording_prune_failed", name=f.name, msg=exc))

    @staticmethod
    def _unique_path(path: Path) -> Path:
        """既存ファイルと衝突しないパスを返す (同名なら _1, _2... を付与)。"""
        if not path.exists():
            return path
        for i in range(1, 1000):
            candidate = path.with_stem(f"{path.stem}_{i}")
            if not candidate.exists():
                return candidate
        return path

    # --------------------------------------------------------------- running
    def _set_running(self, running: bool) -> None:
        """実行中/待機中に応じてボタンの有効・無効を切り替える。"""
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.test_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")

    def _start(self, test: bool = False, auto: bool = False) -> None:
        if self.worker and self.worker.is_alive():
            return

        if self.recorder.is_recording:
            messagebox.showinfo(tr("dlg_recording_title"), tr("dlg_recording_msg"))
            return

        if not self.input_path:
            messagebox.showinfo(tr("dlg_no_input_title"), tr("dlg_no_input_msg"))
            return

        output = self.output_var.get().strip()
        if not output:
            messagebox.showinfo(tr("dlg_no_output_title"), tr("dlg_no_output_msg"))
            return
        try:
            validate_output_path(Path(output))
        except (OSError, ValueError) as exc:
            messagebox.showerror(tr("dlg_error_title"), str(exc))
            return

        self._set_running(True)
        self.progress.configure(value=0)
        self.status_var.set(tr("status_test_processing") if test else tr("status_processing"))
        self._clear_log()

        self.cancel_event = threading.Event()
        self.worker = threading.Thread(
            target=self._worker,
            kwargs=dict(
                input_path=self.input_path,
                output_path=Path(output),
                model_size=ModelSize(self.model_var.get()),
                language=self.language_var.get().strip() or "ja",
                timestamps=self.timestamps_var.get(),
                cancel_event=self.cancel_event,
                test=test,
                auto=auto,
            ),
            daemon=True,
        )

        assert self.worker is not None

        self.worker.start()

    def _cancel(self) -> None:
        if not (self.worker and self.worker.is_alive() and self.cancel_event):
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set(tr("status_cancelling"))

    def _worker(
            self,
            input_path: Path,
            output_path: Path,
            model_size: ModelSize,
            language: str,
            timestamps: bool,
            cancel_event: threading.Event,
            test: bool,
            auto: bool,
    ) -> None:
        """別スレッドで実行。tk には触れず queue 経由で通知する。

        test: 先頭のみ処理しログ表示だけ行う。
        auto: プレビューを出さず直接保存する。
        通常: 内容を生成しプレビューダイアログで確認後に保存する。
        """
        try:
            content = transcribe_to_markdown(
                input_path,
                model_size=model_size,
                language=language,
                timestamps=timestamps,
                progress=lambda cur, total: self.msg_queue.put(("progress", (cur, total))),
                log=lambda msg: self.msg_queue.put(("log", msg)),
                download_progress=lambda cur, total: self.msg_queue.put(("dl_progress", (cur, total))),
                cancel_event=cancel_event,
                max_duration=TEST_DURATION if test else None,
            )
            if test:
                self.msg_queue.put(("test_done", None))
            elif auto:
                output_path.write_text(content, encoding="utf-8")
                self.msg_queue.put(("done", str(output_path)))
            else:
                self.msg_queue.put(("result", (content, str(output_path))))
        except TranscriptionCancelled:
            self.msg_queue.put(("cancelled", None))
        except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
            self.msg_queue.put(("log", traceback.format_exc()))
            self.msg_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "progress":
                    cur, total = cast("tuple[float, float]", payload)
                    pct = (cur / total * 100) if total else 0.0
                    self.progress.configure(value=pct)
                    self.status_var.set(
                        tr("status_progress", cur=f"{cur:.0f}", total=f"{total:.0f}", pct=f"{pct:.0f}")
                    )
                elif kind == "dl_progress":
                    cur, total = cast("tuple[float, float]", payload)
                    pct = (cur / total * 100) if total else 0.0
                    self.progress.configure(value=pct)
                    self.status_var.set(
                        tr(
                            "status_downloading",
                            done=f"{cur / 1024 / 1024:.0f}",
                            total=f"{total / 1024 / 1024:.0f}",
                            pct=f"{pct:.0f}",
                        )
                    )
                elif kind == "done":
                    message: str = cast(str, payload)
                    self.progress.configure(value=100)
                    self.status_var.set(tr("status_done", path=message))
                    self._set_running(False)
                    messagebox.showinfo(tr("dlg_done_title"), tr("dlg_done_msg", path=message))
                elif kind == "test_done":
                    self.progress.configure(value=100)
                    self.status_var.set(tr("status_test_done"))
                    self._set_running(False)
                elif kind == "result":
                    content, out = cast("tuple[str, str]", payload)
                    self.progress.configure(value=100)
                    self.status_var.set(tr("status_preview"))
                    self._set_running(False)
                    PreviewDialog(
                        self.root,
                        content,
                        Path(out),
                        self._append_log,
                        on_saved=self._on_preview_saved,
                        on_discard=self._on_preview_discarded,
                    )
                elif kind == "cancelled":
                    self.progress.configure(value=0)
                    self.status_var.set(tr("status_cancelled"))
                    self._set_running(False)
                    self._append_log(tr("log_cancelled"))
                elif kind == "error":
                    error_message: str = cast(str, payload)
                    self.progress.configure(value=0)
                    self.status_var.set(tr("status_error", msg=error_message))
                    self._set_running(False)
                    messagebox.showerror(tr("dlg_error_title"), error_message)
        except queue.Empty:
            pass

        self.root.after(100, self._poll_queue)

    # --------------------------------------------------------------- preview
    def _on_preview_saved(self, path: Path) -> None:
        self.status_var.set(tr("status_done", path=path))
        self._append_log(tr("log_saved", path=path))

    def _on_preview_discarded(self) -> None:
        self.progress.configure(value=0)
        self.status_var.set(tr("status_idle"))

    # ---------------------------------------------------------- model cache
    def _open_cache_dialog(self) -> None:
        CacheDialog(self.root, self._append_log)

    def _open_recording_cache_dir(self) -> None:
        """録音キャッシュフォルダを OS のファイラーで開く。"""
        path = get_recordings_cache_dir()
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    # ------------------------------------------------------------------- log
    def _append_log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


class PreviewDialog(tk.Toplevel):
    """文字起こし結果を保存前に確認・編集するモーダルダイアログ。"""

    def __init__(
            self,
            parent: tk.Tk,
            content: str,
            output_path: Path,
            log: Callable[[str], None],
            on_saved: Callable[[Path], None],
            on_discard: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(tr("preview_title"))
        self.configure(bg=BG)
        self.geometry("640x520")
        self.minsize(480, 360)

        self._output_path = output_path
        self._log = log
        self._on_saved = on_saved
        self._on_discard = on_discard
        self._saved = False

        ttk.Label(self, text=str(output_path), style="Muted.TLabel").pack(
            anchor="w", padx=12, pady=(10, 2)
        )

        text_frame = ttk.Frame(self)
        text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.text = tk.Text(
            text_frame,
            wrap="word",
            font=FONT_UI,
            relief="flat",
            bg=SURFACE,
            fg=TEXT,
            padx=8,
            pady=6,
        )
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text.insert("1.0", content)
        bind_ime_font_fix(self.text)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=(6, 12))
        tb.Button(
            btn_frame, text=tr("btn_copy"), bootstyle="info-outline", command=self._copy
        ).pack(side="left")
        tb.Button(
            btn_frame, text=tr("btn_save"), bootstyle="success", command=self._save
        ).pack(side="right")
        tb.Button(
            btn_frame, text=tr("btn_discard"), bootstyle="secondary-outline", command=self._discard
        ).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._discard)
        self.transient(parent)
        self.grab_set()

    def _content(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _save(self) -> None:
        try:
            self._output_path.write_text(self._content(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(tr("dlg_error_title"), str(exc), parent=self)
            return
        self._saved = True
        self._on_saved(self._output_path)
        self.destroy()

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._content())
        self._log(tr("log_copied"))

    def _discard(self) -> None:
        if not self._saved:
            self._log(tr("log_preview_discarded"))
            self._on_discard()
        self.destroy()


class CacheDialog(tk.Toplevel):
    """モデルキャッシュを一覧・削除するモーダルダイアログ。"""

    def __init__(self, parent: tk.Tk, log: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.title(tr("cache_title"))
        self.configure(bg=BG)
        self.resizable(False, False)

        self._log = log
        self._queue: queue.Queue[Message] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._items: dict[str, CachedModel] = {}

        self._build_widgets()
        self._refresh()

        self.transient(parent)
        self.grab_set()
        self._center_over(parent)
        self.after(100, self._poll)

    def _build_widgets(self) -> None:
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        self.tree = ttk.Treeview(
            tree_frame, columns=("size",), show="tree headings", height=8, selectmode="extended"
        )
        self.tree.heading("#0", text=tr("cache_col_model"))
        self.tree.heading("size", text=tr("cache_col_size"))
        self.tree.column("#0", width=240, anchor="w")
        self.tree.column("size", width=110, anchor="e")
        scroll = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.total_var = tk.StringVar(value=tr("cache_total_empty"))
        ttk.Label(self, textvariable=self.total_var, style="Muted.TLabel").pack(anchor="w", padx=12)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=(6, 12))
        tb.Button(
            btn_frame, text=tr("btn_close"), bootstyle="secondary", command=self.destroy
        ).pack(side="right", padx=(6, 0))
        tb.Button(
            btn_frame, text=tr("btn_refresh"), bootstyle="info-outline", command=self._refresh
        ).pack(side="right", padx=(6, 0))
        tb.Button(
            btn_frame, text=tr("btn_delete_selected"), bootstyle="danger-outline", command=self._delete_selected
        ).pack(side="right")

    def _center_over(self, parent: tk.Tk) -> None:
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        self._items.clear()

        try:
            cached = list_cached_models()
        except Exception as exc:  # noqa: BLE001 - 一覧表示できなくてもダイアログは継続
            self._log(tr("log_cache_list_failed", msg=exc))
            cached = []

        total_bytes = 0
        for c in cached:
            item_id = self.tree.insert("", "end", text=c.model_size, values=(c.size_str,))
            self._items[item_id] = c
            total_bytes += c.size_bytes

        self.total_var.set(tr("cache_total", size=format_size(total_bytes), count=len(cached)))

    def _delete_selected(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        selected = [self._items[i] for i in self.tree.selection() if i in self._items]
        if not selected:
            messagebox.showinfo(tr("dlg_no_selection_title"), tr("dlg_no_selection_msg"), parent=self)
            return

        names = "\n".join(f"- {c.model_size} ({c.size_str})" for c in selected)
        if not messagebox.askyesno(
                tr("dlg_confirm_delete_title"),
                tr("dlg_confirm_delete_msg", names=names),
                parent=self,
        ):
            return

        self._worker = threading.Thread(target=self._delete_worker, args=(selected,), daemon=True)
        self._worker.start()

    def _delete_worker(self, cached_models: list[CachedModel]) -> None:
        for c in cached_models:
            try:
                delete_cached_model(c)
                self._queue.put(("log", tr("log_cache_deleted", name=c.model_size, size=c.size_str)))
            except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
                self._queue.put(("log", tr("log_cache_delete_failed", name=c.model_size, msg=exc)))
        self._queue.put(("refresh", None))

    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                message: str = cast(str, payload)
                if kind == "log":
                    self._log(message)
                elif kind == "refresh":
                    self._refresh()
        except queue.Empty:
            pass
        self.after(100, self._poll)


def _enable_windows_dpi_awareness() -> None:
    """プロセスを DPI 対応にする (Windows のみ)。

    DPI 非対応のままだと表示スケーリング環境で通常の文字は仮想 96DPI で
    拡大描画される一方、IME の変換中文字列は実 DPI で描画されるため、
    変換中だけ文字が大きく見える。Tk 生成前に呼ぶこと。
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main() -> None:
    _enable_windows_dpi_awareness()
    init_language()
    root = TkinterDnD.Tk()
    WhisperGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
