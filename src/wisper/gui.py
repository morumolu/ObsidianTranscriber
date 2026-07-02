import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tkinterdnd2 import DND_FILES, TkinterDnD

try:
    from .model_cache import CachedModel, delete_cached_model, format_size, list_cached_models
    from .model_size import ModelSize
    from .runner import SUPPORTED_EXTENSIONS, transcribe_file
except ImportError:  # 直接スクリプト実行時のフォールバック
    from model_cache import CachedModel, delete_cached_model, format_size, list_cached_models
    from model_size import ModelSize
    from runner import SUPPORTED_EXTENSIONS, transcribe_file


class WisperGui:
    """音声ファイルをドラッグ&ドロップして文字起こしする GUI。"""

    def __init__(self, root: TkinterDnD.Tk) -> None:
        self.root = root
        self.root.title("Wisper - Audio Transcription")
        self.root.geometry("720x760")
        self.root.minsize(560, 560)

        self.input_path: Path | None = None
        self.msg_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cache_worker: threading.Thread | None = None
        self.cached_models_by_item: dict[str, CachedModel] = {}

        self._build_widgets()
        self.root.after(100, self._poll_queue)
        self._refresh_cache_list()

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

        # モデルキャッシュ管理
        cache_frame = ttk.LabelFrame(self.root, text="モデルキャッシュ")
        cache_frame.pack(fill="x", padx=10, pady=(4, 4))

        tree_frame = ttk.Frame(cache_frame)
        tree_frame.pack(fill="x", padx=6, pady=(4, 2))
        self.cache_tree = ttk.Treeview(
            tree_frame, columns=("size",), show="tree headings", height=4, selectmode="extended"
        )
        self.cache_tree.heading("#0", text="モデル")
        self.cache_tree.heading("size", text="サイズ")
        self.cache_tree.column("#0", width=220, anchor="w")
        self.cache_tree.column("size", width=100, anchor="e")
        cache_scroll = ttk.Scrollbar(tree_frame, command=self.cache_tree.yview)
        self.cache_tree.configure(yscrollcommand=cache_scroll.set)
        self.cache_tree.pack(side="left", fill="x", expand=True)
        cache_scroll.pack(side="right", fill="y")

        cache_btn_frame = ttk.Frame(cache_frame)
        cache_btn_frame.pack(fill="x", padx=6, pady=(0, 6))
        self.cache_total_var = tk.StringVar(value="合計: -")
        ttk.Label(cache_btn_frame, textvariable=self.cache_total_var, foreground="#666666").pack(side="left")
        ttk.Button(cache_btn_frame, text="更新", command=self._refresh_cache_list).pack(side="right", padx=(4, 0))
        ttk.Button(
            cache_btn_frame, text="選択したモデルを削除", command=self._delete_selected_cache
        ).pack(side="right")

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
                    self._refresh_cache_list()
                    messagebox.showinfo("完了", f"保存しました:\n{payload}")
                elif kind == "error":
                    self.status_var.set(f"エラー: {payload}")
                    self.run_button.configure(state="normal")
                    messagebox.showerror("エラー", str(payload))
                elif kind == "cache_refresh":
                    self._refresh_cache_list()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ---------------------------------------------------------- model cache
    def _refresh_cache_list(self) -> None:
        for item in self.cache_tree.get_children():
            self.cache_tree.delete(item)
        self.cached_models_by_item.clear()

        try:
            cached = list_cached_models()
        except Exception as exc:  # noqa: BLE001 - 一覧表示できなくてもアプリは継続
            self._append_log(f"モデルキャッシュの取得に失敗しました: {exc}")
            cached = []

        total_bytes = 0
        for c in cached:
            item_id = self.cache_tree.insert("", "end", text=c.model_size, values=(c.size_str,))
            self.cached_models_by_item[item_id] = c
            total_bytes += c.size_bytes

        self.cache_total_var.set(f"合計: {format_size(total_bytes)} ({len(cached)} 件)")

    def _delete_selected_cache(self) -> None:
        if self.cache_worker and self.cache_worker.is_alive():
            return

        selected = [self.cached_models_by_item[i] for i in self.cache_tree.selection() if i in self.cached_models_by_item]
        if not selected:
            messagebox.showinfo("未選択", "削除するモデルを選択してください。")
            return

        names = "\n".join(f"- {c.model_size} ({c.size_str})" for c in selected)
        if not messagebox.askyesno("キャッシュ削除の確認", f"以下のモデルキャッシュを削除します。よろしいですか？\n\n{names}"):
            return

        self.cache_worker = threading.Thread(target=self._delete_cache_worker, args=(selected,), daemon=True)
        self.cache_worker.start()

    def _delete_cache_worker(self, cached_models: list[CachedModel]) -> None:
        for c in cached_models:
            try:
                delete_cached_model(c)
                self.msg_queue.put(("log", f"モデルキャッシュを削除しました: {c.model_size} ({c.size_str})"))
            except Exception as exc:  # noqa: BLE001 - GUIに表示するため全捕捉
                self.msg_queue.put(("log", f"削除に失敗しました: {c.model_size}: {exc}"))
        self.msg_queue.put(("cache_refresh", None))

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
