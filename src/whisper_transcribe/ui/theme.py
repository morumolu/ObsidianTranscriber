"""カラーパレット・フォント・ttkbootstrap スタイルの定義。"""
import tkinter as tk
from tkinter import font as tkfont

import ttkbootstrap as tb

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


def setup_style(root: tk.Tk) -> None:
    """minty テーマを適用し、アプリ固有のスタイルとフォントを設定する。"""
    style = tb.Style(theme="minty")

    # アプリ全体の既定フォントを Yu Gothic UI に統一
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family="Yu Gothic UI", size=10)

    style.configure("Muted.TLabel", foreground=TEXT_MUTED, font=FONT_UI)
    style.configure("AppTitle.TLabel", foreground=ACCENT, font=FONT_TITLE)
    style.configure("Treeview", rowheight=26)
    root.configure(bg=style.colors.bg)
