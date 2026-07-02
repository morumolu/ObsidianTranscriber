import math
import queue
import threading
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, cast

from tkinterdnd2 import DND_FILES, TkinterDnD

from .i18n import LANGUAGES, get_language, init_language, save_language, tr
from .model_cache import CachedModel, delete_cached_model, format_size, list_cached_models
from .model_size import ModelSize
from .recorder import SAMPLE_RATE, Recorder, RecorderError
from .runner import SUPPORTED_EXTENSIONS, TranscriptionCancelled, transcribe_file

APP_TITLE = "Whisper - Audio Transcription Tool For Obsidian"
APP_VERSION = "0.1.0"

# カラーパレット (目に優しい緑系ライトテーマ + ダークなログ領域)
BG = "#f2f6f2"
SURFACE = "#ffffff"
BORDER = "#d3ded4"
TEXT = "#24312a"
TEXT_MUTED = "#68766d"
ACCENT = "#4e9161"
ACCENT_ACTIVE = "#3f7a50"
ACCENT_DISABLED = "#a8cdb4"
DROP_BG = "#e8f2ea"
DROP_ACTIVE_BG = "#d7e9dc"
RECORD = "#e5484d"
RECORD_ACTIVE = "#c73840"
LEVEL_GREEN = "#6fbf73"
LOG_BG = "#202b24"
LOG_FG = "#d4ddd6"

FONT_UI = ("Yu Gothic UI", 10)
FONT_UI_BOLD = ("Yu Gothic UI", 10, "bold")
FONT_DROP = ("Yu Gothic UI", 11)
FONT_LOG = ("Consolas", 9)

# ワーカースレッドから GUI スレッドへ渡すメッセージ (種別, ペイロード)
Message = tuple[str, object]

# テスト書き起こしで処理する先頭の秒数
TEST_DURATION = 10.0

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
        self.root.geometry("720x640")
        self.root.minsize(560, 480)
        self.root.configure(bg=BG)

        self.input_path: Path | None = None
        self.msg_queue: queue.Queue[Message] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.recorder = Recorder()
        self._record_timer: str | None = None
        self.record_format_var = tk.StringVar(value=".mp3")
        self.ui_language_var = tk.StringVar(value=get_language())
        self.cancel_event: threading.Event | None = None

        self._setup_style()
        self._build_menu()
        self._build_widgets()
        self.root.after(100, self._poll_queue)

    # ---------------------------------------------------------------- style
    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=TEXT, font=FONT_UI)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED)

        style.configure(
            "TButton",
            background=SURFACE,
            foreground=TEXT,
            bordercolor=BORDER,
            focusthickness=1,
            padding=(10, 4),
        )
        style.map("TButton", background=[("active", "#e3ede5")])

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            bordercolor=ACCENT,
            font=FONT_UI_BOLD,
            padding=(12, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", ACCENT_DISABLED), ("active", ACCENT_ACTIVE)],
            foreground=[("disabled", "#f0f0f0")],
        )

        style.configure(
            "Record.TButton",
            background=RECORD,
            foreground="#ffffff",
            bordercolor=RECORD,
            font=FONT_UI_BOLD,
            padding=(12, 8),
        )
        style.map("Record.TButton", background=[("active", RECORD_ACTIVE)])

        style.configure(
            "TLabelframe",
            background=BG,
            bordercolor=BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabelframe.Label", background=BG, foreground=TEXT_MUTED, font=FONT_UI)

        style.configure(
            "TEntry",
            fieldbackground=SURFACE,
            bordercolor=BORDER,
            padding=4,
        )
        style.configure("TCombobox", fieldbackground=SURFACE, bordercolor=BORDER, padding=4)

        style.configure(
            "Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            bordercolor=BORDER,
            rowheight=24,
        )
        style.configure("Treeview.Heading", background="#e3ede5", foreground=TEXT, font=FONT_UI)
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#e1eae3",
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
        style.configure(
            "Level.Horizontal.TProgressbar",
            troughcolor="#e1eae3",
            background=LEVEL_GREEN,
            bordercolor=BORDER,
            lightcolor=LEVEL_GREEN,
            darkcolor=LEVEL_GREEN,
        )

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

    def _show_about(self) -> None:
        messagebox.showinfo(tr("about_title"), tr("about_text", version=APP_VERSION))

    # ------------------------------------------------------------------- UI
    def _build_widgets(self) -> None:
        # ドロップゾーン
        self.drop_zone = tk.Label(
            self.root,
            text=tr("drop_zone", exts=", ".join(sorted(SUPPORTED_EXTENSIONS))),
            relief="flat",
            height=4,
            bg=DROP_BG,
            fg=ACCENT,
            font=FONT_DROP,
            highlightthickness=2,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.drop_zone.pack(fill="x", padx=12, pady=(12, 8))
        dnd_zone = cast(Any, self.drop_zone)
        dnd_zone.drop_target_register(DND_FILES)
        dnd_zone.dnd_bind("<<Drop>>", self._on_drop)
        dnd_zone.dnd_bind("<<DropEnter>>", self._on_drop_enter)
        dnd_zone.dnd_bind("<<DropLeave>>", self._on_drop_leave)

        # 入力ファイル表示
        in_frame = ttk.Frame(self.root)
        in_frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(in_frame, text=tr("label_input"), width=8).pack(side="left")
        self.input_var = tk.StringVar(value=tr("not_selected"))
        ttk.Label(in_frame, textvariable=self.input_var, foreground=ACCENT).pack(
            side="left", fill="x", expand=True, padx=6
        )

        # 出力ファイル名 (編集可能)
        out_frame = ttk.Frame(self.root)
        out_frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(out_frame, text=tr("label_output"), width=8).pack(side="left")
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(out_frame, textvariable=self.output_var)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=6)

        # オプション行
        opt_frame = ttk.Frame(self.root)
        opt_frame.pack(fill="x", padx=12, pady=4)

        ttk.Label(opt_frame, text=tr("label_model")).pack(side="left")
        self.model_var = tk.StringVar(value=ModelSize.large_v3.value)
        model_box = ttk.Combobox(
            opt_frame,
            textvariable=self.model_var,
            values=[m.value for m in ModelSize],
            state="readonly",
            width=16,
        )
        model_box.pack(side="left", padx=(4, 12))

        ttk.Label(opt_frame, text=tr("label_language")).pack(side="left")
        self.language_var = tk.StringVar(value="ja")
        ttk.Entry(opt_frame, textvariable=self.language_var, width=6).pack(side="left", padx=(4, 12))

        self.timestamps_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text=tr("check_timestamps"), variable=self.timestamps_var).pack(side="left")

        # 実行ボタン + 録音ボタン + レベルメータ
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=12, pady=8)
        self.record_button = ttk.Button(
            action_frame, text=tr("btn_record_start"), command=self._toggle_record
        )
        self.record_button.pack(side="left", padx=(0, 8), ipady=4)
        self.level_meter = ttk.Progressbar(
            action_frame,
            style="Level.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
            length=120,
        )
        self.level_meter.pack(side="left", padx=(0, 8))
        self.run_button = ttk.Button(
            action_frame, text=tr("btn_start"), style="Accent.TButton", command=self._start
        )
        self.run_button.pack(side="left", fill="x", expand=True)
        self.test_button = ttk.Button(
            action_frame,
            text=tr("btn_test", sec=f"{TEST_DURATION:.0f}"),
            command=lambda: self._start(test=True),
        )
        self.test_button.pack(side="left", padx=(8, 0), ipady=4)
        self.cancel_button = ttk.Button(
            action_frame, text=tr("btn_cancel"), state="disabled", command=self._cancel
        )
        self.cancel_button.pack(side="left", padx=(8, 0), ipady=4)

        # 進捗バー + ステータス
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=12, pady=(0, 4))
        self.status_var = tk.StringVar(value=tr("status_idle"))
        ttk.Label(self.root, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w", padx=12)

        # 処理ログ
        ttk.Label(self.root, text=tr("label_log")).pack(anchor="w", padx=12, pady=(8, 0))
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            height=12,
            state="disabled",
            bg=LOG_BG,
            fg=LOG_FG,
            font=FONT_LOG,
            relief="flat",
            padx=8,
            pady=6,
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
        # デフォルト出力名 = 入力ファイルの拡張子を .md に変えたもの
        self.output_var.set(str(path.with_suffix(".md")))

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
        self.record_button.configure(text=tr("btn_record_stop"), style="Record.TButton")
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
        self.record_button.configure(text=tr("btn_record_start"), style="TButton")
        self.run_button.configure(state="normal")
        self.level_meter.configure(value=0)
        self.status_var.set(tr("status_idle"))

        if len(data) == 0:
            self._append_log(tr("log_record_none"))
            return

        duration = len(data) / SAMPLE_RATE
        ext = self.record_format_var.get()
        default_name = datetime.now().strftime(f"recording_%Y%m%d_%H%M%S{ext}")
        # 設定中のフォーマットを先頭にしてダイアログに渡す
        filetypes = sorted(
            ((f"{label} ({e})", f"*{e}") for e, label in record_formats()),
            key=lambda t: not t[1].endswith(ext),
        )
        path_str = filedialog.asksaveasfilename(
            title=tr("dlg_record_save"),
            defaultextension=ext,
            filetypes=filetypes,
            initialfile=default_name,
        )
        if not path_str:
            self._append_log(tr("log_record_discard"))
            return

        try:
            path = Recorder.save(Path(path_str), data)
        except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
            messagebox.showerror(tr("dlg_save_error_title"), tr("dlg_save_error_msg", msg=exc))
            return
        self._append_log(tr("log_record_saved", path=path, sec=f"{duration:.1f}"))
        self._set_input(path)

    # --------------------------------------------------------------- running
    def _set_running(self, running: bool) -> None:
        """実行中/待機中に応じてボタンの有効・無効を切り替える。"""
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.test_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")

    def _start(self, test: bool = False) -> None:
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
    ) -> None:
        """別スレッドで実行。tk には触れず queue 経由で通知する。"""
        try:
            transcribe_file(
                input_path,
                output_path,
                model_size=model_size,
                language=language,
                timestamps=timestamps,
                progress=lambda cur, total: self.msg_queue.put(("progress", (cur, total))),
                log=lambda msg: self.msg_queue.put(("log", msg)),
                cancel_event=cancel_event,
                max_duration=TEST_DURATION if test else None,
                save_output=not test,
            )
            self.msg_queue.put(("test_done" if test else "done", str(output_path)))
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

    # ---------------------------------------------------------- model cache
    def _open_cache_dialog(self) -> None:
        CacheDialog(self.root, self._append_log)

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
        ttk.Button(btn_frame, text=tr("btn_close"), command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_frame, text=tr("btn_refresh"), command=self._refresh).pack(side="right", padx=(6, 0))
        ttk.Button(btn_frame, text=tr("btn_delete_selected"), command=self._delete_selected).pack(side="right")

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


def main() -> None:
    init_language()
    root = TkinterDnD.Tk()
    WhisperGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
