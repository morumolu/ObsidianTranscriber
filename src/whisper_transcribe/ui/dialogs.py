"""モーダルダイアログ (結果プレビュー / モデルキャッシュ管理)。"""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, cast

import ttkbootstrap as tb

from ..core.model_cache import (
    CachedModel,
    delete_cached_model,
    format_size,
    list_cached_models,
)
from .i18n import tr
from .theme import BG, FONT_UI, SURFACE, TEXT
from .win32 import bind_ime_font_fix

# ワーカースレッドから GUI スレッドへ渡すメッセージ (種別, ペイロード)
Message = tuple[str, object]


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
        # DPI スケーリングに応じた初期サイズ (文字が大きくなっても中身が収まるように)
        scale = self.winfo_fpixels("1i") / 96.0
        self.geometry(f"{int(640 * scale)}x{int(520 * scale)}")
        self.minsize(int(480 * scale), int(360 * scale))

        self._output_path = output_path
        self._log = log
        self._on_saved = on_saved
        self._on_discard = on_discard
        self._saved = False

        # ボタン行を先に bottom へ確保し、ウィンドウが狭くても隠れないようにする
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side="bottom", fill="x", padx=12, pady=(6, 12))
        tb.Button(
            btn_frame, text=tr("btn_copy"), bootstyle="info-outline", command=self._copy
        ).pack(side="left")
        tb.Button(
            btn_frame, text=tr("btn_save"), bootstyle="success", command=self._save
        ).pack(side="right")
        tb.Button(
            btn_frame, text=tr("btn_discard"), bootstyle="secondary-outline", command=self._discard
        ).pack(side="right", padx=(0, 8))

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
        self.after(100, self._poll)  # noqa

    def _build_widgets(self) -> None:
        # ボタン行と合計表示を先に bottom へ確保し、隠れないようにする
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side="bottom", fill="x", padx=12, pady=(6, 12))
        tb.Button(
            btn_frame, text=tr("btn_close"), bootstyle="secondary", command=self.destroy
        ).pack(side="right", padx=(6, 0))
        tb.Button(
            btn_frame, text=tr("btn_refresh"), bootstyle="info-outline", command=self._refresh
        ).pack(side="right", padx=(6, 0))
        tb.Button(
            btn_frame, text=tr("btn_delete_selected"), bootstyle="danger-outline", command=self._delete_selected
        ).pack(side="right")

        self.total_var = tk.StringVar(value=tr("cache_total_empty"))
        ttk.Label(self, textvariable=self.total_var, style="Muted.TLabel").pack(
            side="bottom", anchor="w", padx=12
        )

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
        self.after(100, self._poll)  # noqa
