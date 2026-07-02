import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tkinterdnd2 import DND_FILES, TkinterDnD

try:
    from .model_size import ModelSize
    from .runner import SUPPORTED_EXTENSIONS, transcribe_file
except ImportError:  # 直接スクリプト実行時のフォールバック
    from model_size import ModelSize
    from runner import SUPPORTED_EXTENSIONS, transcribe_file


class WisperGui:
    """音声ファイルをドラッグ&ドロップして文字起こしする GUI。"""

    def __init__(self, root: TkinterDnD.Tk) -> None:
        self.root = root
        self.root.title("Wisper - Audio Transcription")
        self.root.geometry("720x620")
        self.root.minsize(560, 480)

        self.input_path: Path | None = None
        self.msg_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_widgets()
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 4}

        # ドロップゾーン
        self.drop_zone = tk.Label(
            self.root,
            text="ここに音声ファイルをドラッグ&ドロップ\n"
                 f"({', '.join(sorted(SUPPORTED_EXTENSIONS))})",
            relief="ridge",
            borderwidth=2,
            height=4,
            bg="#f0f0f0",
            fg="#555555",
        )
        self.drop_zone.pack(fill="x", padx=10, pady=(10, 6))
        self.drop_zone.drop_target_register(DND_FILES)
        self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)

        # 入力ファイル表示 + 参照
        in_frame = ttk.Frame(self.root)
        in_frame.pack(fill="x", **pad)
        ttk.Label(in_frame, text="入力:").pack(side="left")
        self.input_var = tk.StringVar(value="(未選択)")
        ttk.Label(in_frame, textvariable=self.input_var, foreground="#0066cc").pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(in_frame, text="参照...", command=self._browse_input).pack(side="right")

        # 出力ファイル名（編集可能）+ 参照
        out_frame = ttk.Frame(self.root)
        out_frame.pack(fill="x", **pad)
        ttk.Label(out_frame, text="出力:").pack(side="left")
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(out_frame, textvariable=self.output_var)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(out_frame, text="参照...", command=self._browse_output).pack(side="right")

        # オプション行
        opt_frame = ttk.Frame(self.root)
        opt_frame.pack(fill="x", **pad)

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

        # 実行ボタン
        self.run_button = ttk.Button(self.root, text="文字起こし開始", command=self._start)
        self.run_button.pack(fill="x", padx=10, pady=6)

        # 進捗バー
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 4))
        self.status_var = tk.StringVar(value="待機中")
        ttk.Label(self.root, textvariable=self.status_var, foreground="#666666").pack(anchor="w", padx=10)

        # 処理ログ
        ttk.Label(self.root, text="処理ログ:").pack(anchor="w", padx=10, pady=(6, 0))
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(log_frame, wrap="word", height=12, state="disabled", bg="#1e1e1e", fg="#dddddd")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ------------------------------------------------------------ file input
    def _on_drop(self, event) -> None:
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

    # --------------------------------------------------------------- running
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
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

        args = dict(
            input_path=self.input_path,
            output_path=Path(output),
            model_size=ModelSize(self.model_var.get()),
            language=self.language_var.get().strip() or "ja",
            timestamps=self.timestamps_var.get(),
        )
        self.worker = threading.Thread(target=self._worker, kwargs=args, daemon=True)
        self.worker.start()

    def _worker(self, **kwargs) -> None:
        """別スレッドで実行。tk には触れず queue 経由で通知する。"""
        try:
            transcribe_file(
                progress=lambda cur, total: self.msg_queue.put(("progress", (cur, total))),
                log=lambda msg: self.msg_queue.put(("log", msg)),
                **kwargs,
            )
            self.msg_queue.put(("done", str(kwargs["output_path"])))
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
                    cur, total = payload
                    pct = (cur / total * 100) if total else 0
                    self.progress.configure(value=pct)
                    self.status_var.set(f"処理中... {cur:.0f}s / {total:.0f}s ({pct:.0f}%)")
                elif kind == "done":
                    self.progress.configure(value=100)
                    self.status_var.set(f"完了: {payload}")
                    self.run_button.configure(state="normal")
                    messagebox.showinfo("完了", f"保存しました:\n{payload}")
                elif kind == "error":
                    self.status_var.set(f"エラー: {payload}")
                    self.run_button.configure(state="normal")
                    messagebox.showerror("エラー", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ log
    def _append_log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


def main() -> None:
    root = TkinterDnD.Tk()
    WisperGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
