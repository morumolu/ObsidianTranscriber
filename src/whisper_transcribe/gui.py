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

try:
    from .model_cache import CachedModel, delete_cached_model, format_size, list_cached_models
    from .model_size import ModelSize
    from .recorder import SAMPLE_RATE, Recorder, RecorderError
    from .runner import SUPPORTED_EXTENSIONS, transcribe_file
except ImportError:  # 直接スクリプト実行時のフォールバック
    from model_cache import CachedModel, delete_cached_model, format_size, list_cached_models  # type: ignore[no-redef,import-not-found]
    from model_size import ModelSize  # type: ignore[no-redef,import-not-found]
    from recorder import SAMPLE_RATE, Recorder, RecorderError  # type: ignore[no-redef,import-not-found]
    from runner import SUPPORTED_EXTENSIONS, transcribe_file  # type: ignore[no-redef,import-not-found]

APP_TITLE = "Whisper - Audio Transcription"
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

# 録音の保存フォーマット (拡張子, 表示名)。メニューと保存ダイアログで共用
RECORD_FORMATS: list[tuple[str, str]] = [
    (".mp3", "MP3"),
    (".ogg", "OGG Vorbis"),
    (".flac", "FLAC (可逆圧縮)"),
    (".wav", "WAV (無圧縮)"),
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
            label="音声ファイルを開く...", accelerator="Ctrl+O", command=self._browse_input
        )
        file_menu.add_command(
            label="出力先を指定...", accelerator="Ctrl+S", command=self._browse_output
        )
        file_menu.add_separator()
        file_menu.add_command(label="終了", accelerator="Ctrl+Q", command=self.root.destroy)
        menubar.add_cascade(label="ファイル", menu=file_menu)

        tool_menu = tk.Menu(menubar, tearoff=False)
        tool_menu.add_command(label="文字起こし開始", accelerator="F5", command=self._start)
        tool_menu.add_command(label="録音開始/停止", accelerator="Ctrl+R", command=self._toggle_record)
        tool_menu.add_separator()
        tool_menu.add_command(label="モデルキャッシュ管理...", command=self._open_cache_dialog)
        tool_menu.add_separator()
        tool_menu.add_command(label="ログをクリア", command=self._clear_log)
        menubar.add_cascade(label="ツール", menu=tool_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        format_menu = tk.Menu(settings_menu, tearoff=False)
        for ext, label in RECORD_FORMATS:
            format_menu.add_radiobutton(
                label=f"{label} ({ext})", value=ext, variable=self.record_format_var
            )
        settings_menu.add_cascade(label="録音フォーマット", menu=format_menu)
        menubar.add_cascade(label="設定", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="バージョン情報", command=self._show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)

        self.root.config(menu=menubar)

        self.root.bind_all("<Control-o>", lambda _e: self._browse_input())
        self.root.bind_all("<Control-s>", lambda _e: self._browse_output())
        self.root.bind_all("<Control-q>", lambda _e: self.root.destroy())
        self.root.bind_all("<Control-r>", lambda _e: self._toggle_record())
        self.root.bind_all("<F5>", lambda _e: self._start())

    def _show_about(self) -> None:
        messagebox.showinfo(
            "バージョン情報",
            f"Whisper {APP_VERSION}\n\n"
            "faster-whisper によるローカル音声文字起こしツール。\n"
            "結果は Obsidian 向け Markdown として保存されます。",
        )

    # ------------------------------------------------------------------- UI
    def _build_widgets(self) -> None:
        # ドロップゾーン
        self.drop_zone = tk.Label(
            self.root,
            text="🎵 ここに音声ファイルをドラッグ&ドロップ\n"
                 f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}",
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
        ttk.Label(in_frame, text="入力:", width=6).pack(side="left")
        self.input_var = tk.StringVar(value="(未選択)")
        ttk.Label(in_frame, textvariable=self.input_var, foreground=ACCENT).pack(
            side="left", fill="x", expand=True, padx=6
        )

        # 出力ファイル名 (編集可能)
        out_frame = ttk.Frame(self.root)
        out_frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(out_frame, text="出力:", width=6).pack(side="left")
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(out_frame, textvariable=self.output_var)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=6)

        # オプション行
        opt_frame = ttk.Frame(self.root)
        opt_frame.pack(fill="x", padx=12, pady=4)

        ttk.Label(opt_frame, text="モデル:").pack(side="left")
        self.model_var = tk.StringVar(value=ModelSize.large_v3.value)
        model_box = ttk.Combobox(
            opt_frame,
            textvariable=self.model_var,
            values=[m.value for m in ModelSize],
            state="readonly",
            width=16,
        )
        model_box.pack(side="left", padx=(4, 12))

        ttk.Label(opt_frame, text="言語:").pack(side="left")
        self.language_var = tk.StringVar(value="ja")
        ttk.Entry(opt_frame, textvariable=self.language_var, width=6).pack(side="left", padx=(4, 12))

        self.timestamps_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="タイムスタンプ", variable=self.timestamps_var).pack(side="left")

        # 実行ボタン + 録音ボタン + レベルメータ
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=12, pady=8)
        self.record_button = ttk.Button(
            action_frame, text="● 録音開始", command=self._toggle_record
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
            action_frame, text="文字起こし開始", style="Accent.TButton", command=self._start
        )
        self.run_button.pack(side="left", fill="x", expand=True)

        # 進捗バー + ステータス
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=12, pady=(0, 4))
        self.status_var = tk.StringVar(value="待機中")
        ttk.Label(self.root, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w", padx=12)

        # 処理ログ
        ttk.Label(self.root, text="処理ログ:").pack(anchor="w", padx=12, pady=(8, 0))
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
            self._append_log("複数ファイルがドロップされました。先頭のみ対象にします。")

    def _browse_input(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        path = filedialog.askopenfilename(
            title="音声ファイルを選択",
            filetypes=[("Audio files", exts), ("All files", "*.*")],
        )
        if path:
            self._set_input(Path(path))

    def _set_input(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            messagebox.showwarning(
                "非対応の形式",
                f"'{path.suffix}' は非対応です。\n対応形式: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            )
            return
        self.input_path = path
        self.input_var.set(str(path))
        # デフォルト出力名 = 入力ファイルの拡張子を .md に変えたもの
        self.output_var.set(str(path.with_suffix(".md")))

    def _browse_output(self) -> None:
        initial = Path(self.output_var.get()) if self.output_var.get() else None
        path = filedialog.asksaveasfilename(
            title="保存先を選択",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
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
            messagebox.showinfo("処理中", "文字起こし中は録音できません。")
            return
        try:
            self.recorder.start()
        except RecorderError as exc:
            messagebox.showerror("録音エラー", str(exc))
            return
        self.record_button.configure(text="■ 録音停止", style="Record.TButton")
        self.run_button.configure(state="disabled")
        self._append_log("録音を開始しました。")
        self._update_record_elapsed()

    def _update_record_elapsed(self) -> None:
        if not self.recorder.is_recording:
            return
        self.status_var.set(f"録音中... {self.recorder.elapsed_seconds:.0f}s")
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
        self.record_button.configure(text="● 録音開始", style="TButton")
        self.run_button.configure(state="normal")
        self.level_meter.configure(value=0)
        self.status_var.set("待機中")

        if len(data) == 0:
            self._append_log("録音データがありません。")
            return

        duration = len(data) / SAMPLE_RATE
        ext = self.record_format_var.get()
        default_name = datetime.now().strftime(f"recording_%Y%m%d_%H%M%S{ext}")
        # 設定中のフォーマットを先頭にしてダイアログに渡す
        filetypes = sorted(
            ((f"{label} ({e})", f"*{e}") for e, label in RECORD_FORMATS),
            key=lambda t: not t[1].endswith(ext),
        )
        path_str = filedialog.asksaveasfilename(
            title="録音の保存先",
            defaultextension=ext,
            filetypes=filetypes,
            initialfile=default_name,
        )
        if not path_str:
            self._append_log("録音を破棄しました。")
            return

        try:
            path = Recorder.save(Path(path_str), data)
        except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
            messagebox.showerror("保存エラー", f"録音の保存に失敗しました:\n{exc}")
            return
        self._append_log(f"録音を保存しました: {path} ({duration:.1f}s)")
        self._set_input(path)

    # --------------------------------------------------------------- running
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if self.recorder.is_recording:
            messagebox.showinfo("録音中", "録音を停止してから文字起こしを開始してください。")
            return
        if not self.input_path:
            messagebox.showinfo("入力なし", "音声ファイルを選択してください。")
            return
        output = self.output_var.get().strip()
        if not output:
            messagebox.showinfo("出力なし", "出力ファイル名を入力してください。")
            return

        self.run_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.status_var.set("処理中...")
        self._clear_log()

        self.worker = threading.Thread(
            target=self._worker,
            kwargs=dict(
                input_path=self.input_path,
                output_path=Path(output),
                model_size=ModelSize(self.model_var.get()),
                language=self.language_var.get().strip() or "ja",
                timestamps=self.timestamps_var.get(),
            ),
            daemon=True,
        )
        self.worker.start()

    def _worker(
            self,
            input_path: Path,
            output_path: Path,
            model_size: ModelSize,
            language: str,
            timestamps: bool,
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
            )
            self.msg_queue.put(("done", str(output_path)))
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
                    self.status_var.set(f"処理中... {cur:.0f}s / {total:.0f}s ({pct:.0f}%)")
                elif kind == "done":
                    self.progress.configure(value=100)
                    self.status_var.set(f"完了: {payload}")
                    self.run_button.configure(state="normal")
                    messagebox.showinfo("完了", f"保存しました:\n{payload}")
                elif kind == "error":
                    self.progress.configure(value=0)
                    self.status_var.set(f"エラー: {payload}")
                    self.run_button.configure(state="normal")
                    messagebox.showerror("エラー", str(payload))
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
        self.title("モデルキャッシュ管理")
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
        self.tree.heading("#0", text="モデル")
        self.tree.heading("size", text="サイズ")
        self.tree.column("#0", width=240, anchor="w")
        self.tree.column("size", width=110, anchor="e")
        scroll = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.total_var = tk.StringVar(value="合計: -")
        ttk.Label(self, textvariable=self.total_var, style="Muted.TLabel").pack(anchor="w", padx=12)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=(6, 12))
        ttk.Button(btn_frame, text="閉じる", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="更新", command=self._refresh).pack(side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="選択したモデルを削除", command=self._delete_selected).pack(side="right")

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
            self._log(f"モデルキャッシュの取得に失敗しました: {exc}")
            cached = []

        total_bytes = 0
        for c in cached:
            item_id = self.tree.insert("", "end", text=c.model_size, values=(c.size_str,))
            self._items[item_id] = c
            total_bytes += c.size_bytes

        self.total_var.set(f"合計: {format_size(total_bytes)} ({len(cached)} 件)")

    def _delete_selected(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        selected = [self._items[i] for i in self.tree.selection() if i in self._items]
        if not selected:
            messagebox.showinfo("未選択", "削除するモデルを選択してください。", parent=self)
            return

        names = "\n".join(f"- {c.model_size} ({c.size_str})" for c in selected)
        if not messagebox.askyesno(
            "キャッシュ削除の確認",
            f"以下のモデルキャッシュを削除します。よろしいですか？\n\n{names}",
            parent=self,
        ):
            return

        self._worker = threading.Thread(target=self._delete_worker, args=(selected,), daemon=True)
        self._worker.start()

    def _delete_worker(self, cached_models: list[CachedModel]) -> None:
        for c in cached_models:
            try:
                delete_cached_model(c)
                self._queue.put(("log", f"モデルキャッシュを削除しました: {c.model_size} ({c.size_str})"))
            except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
                self._queue.put(("log", f"削除に失敗しました: {c.model_size}: {exc}"))
        self._queue.put(("refresh", None))

    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "refresh":
                    self._refresh()
        except queue.Empty:
            pass
        self.after(100, self._poll)


def main() -> None:
    root = TkinterDnD.Tk()
    WhisperGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
