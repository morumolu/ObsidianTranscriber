"""GUI 文字列の多言語対応 (日本語 / 英語) と言語設定の永続化。

言語は `~/.whisper_transcribe.json` に保存され、次回起動時に反映される。
未設定の場合は OS のロケールから自動判定する。
"""
import locale
from typing import Any

from .config import get_value, set_value

# (言語コード, メニュー表示名)。表示名は翻訳しない
LANGUAGES: list[tuple[str, str]] = [("ja", "日本語"), ("en", "English")]

_current_language = "en"

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "ja": {
        # メニュー
        "menu_file": "ファイル",
        "menu_open_audio": "音声ファイルを開く...",
        "menu_set_output": "出力先を指定...",
        "menu_quit": "終了",
        "menu_tools": "ツール",
        "menu_start": "文字起こし開始",
        "menu_test": "テスト書き起こし (先頭{sec}秒)",
        "menu_cancel": "文字起こしを中断",
        "menu_record_toggle": "録音開始/停止",
        "menu_cache": "モデルキャッシュ管理...",
        "menu_clear_log": "ログをクリア",
        "menu_settings": "設定",
        "menu_record_format": "録音フォーマット",
        "menu_language": "言語 (Language)",
        "menu_help": "ヘルプ",
        "menu_about": "バージョン情報",
        "about_title": "バージョン情報",
        "about_text": "Whisper {version}\n\nfaster-whisper によるローカル音声文字起こしツール。\n結果は Obsidian 向け Markdown として保存されます。",
        # メイン画面
        "app_subtitle": "Obsidian向けローカル音声文字起こし",
        "drop_zone": "🎵 ここに音声ファイルをドラッグ&ドロップ\n{exts}",
        "label_input": "入力:",
        "label_output": "出力:",
        "not_selected": "(未選択)",
        "label_model": "モデル:",
        "label_language": "言語:",
        "check_timestamps": "タイムスタンプ",
        "btn_record_start": "● 録音開始",
        "btn_record_stop": "■ 録音停止",
        "btn_start": "文字起こし開始",
        "btn_test": "テスト ({sec}秒)",
        "btn_cancel": "中断",
        "label_log": "処理ログ:",
        # ステータス
        "status_idle": "待機中",
        "status_processing": "処理中...",
        "status_test_processing": "テスト処理中...",
        "status_progress": "処理中... {cur}s / {total}s ({pct}%)",
        "status_downloading": "モデルをダウンロード中... {done}MB / {total}MB ({pct}%)",
        "status_recording": "録音中... {sec}s",
        "status_done": "完了: {path}",
        "status_test_done": "テスト完了 (結果は処理ログを確認、ファイルは未保存)",
        "status_cancelling": "中断中...",
        "status_cancelled": "中断しました",
        "status_error": "エラー: {msg}",
        # ダイアログ
        "dlg_done_title": "完了",
        "dlg_done_msg": "保存しました:\n{path}",
        "dlg_error_title": "エラー",
        "dlg_busy_title": "処理中",
        "dlg_busy_msg": "文字起こし中は録音できません。",
        "dlg_recording_title": "録音中",
        "dlg_recording_msg": "録音を停止してから文字起こしを開始してください。",
        "dlg_no_input_title": "入力なし",
        "dlg_no_input_msg": "音声ファイルを選択してください。",
        "dlg_no_output_title": "出力なし",
        "dlg_no_output_msg": "出力ファイル名を入力してください。",
        "dlg_unsupported_title": "非対応の形式",
        "dlg_unsupported_msg": "'{ext}' は非対応です。\n対応形式: {supported}",
        "dlg_select_audio": "音声ファイルを選択",
        "dlg_select_output": "保存先を選択",
        "dlg_record_save": "録音の保存先",
        "dlg_save_error_title": "保存エラー",
        "dlg_save_error_msg": "録音の保存に失敗しました:\n{msg}",
        "dlg_record_error_title": "録音エラー",
        # ファイル種別
        "ft_audio": "音声ファイル",
        "ft_all": "すべてのファイル",
        "ft_markdown": "Markdown",
        "fmt_flac": "FLAC (可逆圧縮)",
        "fmt_wav": "WAV (無圧縮)",
        # ログ
        "log_multi_drop": "複数ファイルがドロップされました。先頭のみ対象にします。",
        "log_record_start": "録音を開始しました。",
        "log_record_none": "録音データがありません。",
        "log_record_discard": "録音を破棄しました。",
        "log_record_saved": "録音を保存しました: {path} ({sec}s)",
        "log_cancelled": "文字起こしを中断しました。",
        # キャッシュダイアログ
        "cache_title": "モデルキャッシュ管理",
        "cache_col_model": "モデル",
        "cache_col_size": "サイズ",
        "cache_total": "合計: {size} ({count} 件)",
        "cache_total_empty": "合計: -",
        "btn_close": "閉じる",
        "btn_refresh": "更新",
        "btn_delete_selected": "選択したモデルを削除",
        "dlg_no_selection_title": "未選択",
        "dlg_no_selection_msg": "削除するモデルを選択してください。",
        "dlg_confirm_delete_title": "キャッシュ削除の確認",
        "dlg_confirm_delete_msg": "以下のモデルキャッシュを削除します。よろしいですか？\n\n{names}",
        "log_cache_deleted": "モデルキャッシュを削除しました: {name} ({size})",
        "log_cache_delete_failed": "削除に失敗しました: {name}: {msg}",
        "log_cache_list_failed": "モデルキャッシュの取得に失敗しました: {msg}",
        # 言語設定
        "lang_restart_title": "言語設定",
        "lang_restart_msg": "言語は再起動後に反映されます。",
        # 録音ファイル名・Vault設定
        "menu_record_filename": "録音ファイル名の形式...",
        "dlg_filename_format_title": "録音ファイル名の形式",
        "dlg_filename_format_prompt": "strftime形式で入力してください。\n例: %Y%m%d_%H%M → {example}",
        "dlg_filename_format_invalid_title": "無効な形式",
        "dlg_filename_format_invalid_msg": "この形式は使用できません: {msg}",
        "log_filename_format_set": "録音ファイル名の形式を設定しました: {fmt} (例: {example})",
        "menu_vault": "Obsidian Vault フォルダ...",
        "dlg_vault_title": "Obsidian Vault (録音の保存先) フォルダを選択",
        "log_vault_set": "Vault フォルダを設定しました: {path}",
        # 自動文字起こし
        "menu_auto_transcribe": "録音停止後に自動で文字起こし",
        # 録音キャッシュ
        "menu_open_recording_cache": "録音キャッシュフォルダを開く",
        "menu_recording_cache_limit": "録音キャッシュの上限数...",
        "dlg_recording_cache_limit_title": "録音キャッシュの上限数",
        "dlg_recording_cache_limit_prompt": "キャッシュに残す録音ファイルの最大数を入力してください。\nキャッシュ場所: {dir}",
        "log_recording_cache_limit_set": "録音キャッシュの上限を {limit} 件に設定しました。",
        "log_recording_pruned": "古い録音をキャッシュから削除しました: {name}",
        "log_recording_prune_failed": "録音キャッシュの削除に失敗しました: {name}: {msg}",
        # プレビュー
        "preview_title": "文字起こし結果のプレビュー",
        "status_preview": "結果を確認してください (プレビューを表示中)",
        "btn_save": "保存",
        "btn_copy": "コピー",
        "btn_discard": "破棄",
        "log_saved": "保存しました: {path}",
        "log_copied": "クリップボードにコピーしました。",
        "log_preview_discarded": "保存せずに閉じました。",
        # 録音
        "rec_start_failed": "録音を開始できませんでした: {msg}",
        "rec_unsupported_format": "未対応の保存形式です: '{ext}' (対応: {supported})",
    },
    "en": {
        # Menus
        "menu_file": "File",
        "menu_open_audio": "Open Audio File...",
        "menu_set_output": "Set Output File...",
        "menu_quit": "Quit",
        "menu_tools": "Tools",
        "menu_start": "Start Transcription",
        "menu_test": "Test Transcription (first {sec}s)",
        "menu_cancel": "Cancel Transcription",
        "menu_record_toggle": "Start/Stop Recording",
        "menu_cache": "Manage Model Cache...",
        "menu_clear_log": "Clear Log",
        "menu_settings": "Settings",
        "menu_record_format": "Recording Format",
        "menu_language": "Language",
        "menu_help": "Help",
        "menu_about": "About",
        "about_title": "About",
        "about_text": "Whisper {version}\n\nLocal audio transcription tool powered by faster-whisper.\nResults are saved as Obsidian-friendly Markdown.",
        # Main window
        "app_subtitle": "Local audio transcription for Obsidian",
        "drop_zone": "🎵 Drag & drop an audio file here\n{exts}",
        "label_input": "Input:",
        "label_output": "Output:",
        "not_selected": "(not selected)",
        "label_model": "Model:",
        "label_language": "Lang:",
        "check_timestamps": "Timestamps",
        "btn_record_start": "● Record",
        "btn_record_stop": "■ Stop",
        "btn_start": "Start Transcription",
        "btn_test": "Test ({sec}s)",
        "btn_cancel": "Cancel",
        "label_log": "Log:",
        # Status
        "status_idle": "Idle",
        "status_processing": "Processing...",
        "status_test_processing": "Test processing...",
        "status_progress": "Processing... {cur}s / {total}s ({pct}%)",
        "status_downloading": "Downloading model... {done}MB / {total}MB ({pct}%)",
        "status_recording": "Recording... {sec}s",
        "status_done": "Done: {path}",
        "status_test_done": "Test finished (see log; no file saved)",
        "status_cancelling": "Cancelling...",
        "status_cancelled": "Cancelled",
        "status_error": "Error: {msg}",
        # Dialogs
        "dlg_done_title": "Done",
        "dlg_done_msg": "Saved to:\n{path}",
        "dlg_error_title": "Error",
        "dlg_busy_title": "Busy",
        "dlg_busy_msg": "Cannot record while transcribing.",
        "dlg_recording_title": "Recording",
        "dlg_recording_msg": "Stop recording before starting transcription.",
        "dlg_no_input_title": "No Input",
        "dlg_no_input_msg": "Please select an audio file.",
        "dlg_no_output_title": "No Output",
        "dlg_no_output_msg": "Please enter an output file name.",
        "dlg_unsupported_title": "Unsupported Format",
        "dlg_unsupported_msg": "'{ext}' is not supported.\nSupported: {supported}",
        "dlg_select_audio": "Select Audio File",
        "dlg_select_output": "Select Output File",
        "dlg_record_save": "Save Recording As",
        "dlg_save_error_title": "Save Error",
        "dlg_save_error_msg": "Failed to save the recording:\n{msg}",
        "dlg_record_error_title": "Recording Error",
        # File types
        "ft_audio": "Audio files",
        "ft_all": "All files",
        "ft_markdown": "Markdown",
        "fmt_flac": "FLAC (lossless)",
        "fmt_wav": "WAV (uncompressed)",
        # Log
        "log_multi_drop": "Multiple files dropped; using only the first one.",
        "log_record_start": "Recording started.",
        "log_record_none": "No audio was recorded.",
        "log_record_discard": "Recording discarded.",
        "log_record_saved": "Recording saved: {path} ({sec}s)",
        "log_cancelled": "Transcription cancelled.",
        # Cache dialog
        "cache_title": "Manage Model Cache",
        "cache_col_model": "Model",
        "cache_col_size": "Size",
        "cache_total": "Total: {size} ({count} items)",
        "cache_total_empty": "Total: -",
        "btn_close": "Close",
        "btn_refresh": "Refresh",
        "btn_delete_selected": "Delete Selected Models",
        "dlg_no_selection_title": "No Selection",
        "dlg_no_selection_msg": "Select models to delete.",
        "dlg_confirm_delete_title": "Confirm Deletion",
        "dlg_confirm_delete_msg": "Delete the following model caches?\n\n{names}",
        "log_cache_deleted": "Deleted model cache: {name} ({size})",
        "log_cache_delete_failed": "Failed to delete: {name}: {msg}",
        "log_cache_list_failed": "Failed to list model cache: {msg}",
        # Language setting
        "lang_restart_title": "Language",
        "lang_restart_msg": "The language change will take effect after restarting the app.",
        # Recording filename / vault settings
        "menu_record_filename": "Recording File Name Format...",
        "dlg_filename_format_title": "Recording File Name Format",
        "dlg_filename_format_prompt": "Enter a strftime pattern.\ne.g. %Y%m%d_%H%M -> {example}",
        "dlg_filename_format_invalid_title": "Invalid Format",
        "dlg_filename_format_invalid_msg": "This pattern cannot be used: {msg}",
        "log_filename_format_set": "Recording file name format set: {fmt} (e.g. {example})",
        "menu_vault": "Obsidian Vault Folder...",
        "dlg_vault_title": "Select Obsidian Vault (Recording Destination) Folder",
        "log_vault_set": "Vault folder set: {path}",
        # Auto transcription
        "menu_auto_transcribe": "Auto-transcribe after recording stops",
        # Recording cache
        "menu_open_recording_cache": "Open Recording Cache Folder",
        "menu_recording_cache_limit": "Recording Cache Limit...",
        "dlg_recording_cache_limit_title": "Recording Cache Limit",
        "dlg_recording_cache_limit_prompt": "Enter the maximum number of recordings to keep in the cache.\nCache location: {dir}",
        "log_recording_cache_limit_set": "Recording cache limit set to {limit}.",
        "log_recording_pruned": "Removed old recording from cache: {name}",
        "log_recording_prune_failed": "Failed to remove cached recording: {name}: {msg}",
        # Preview
        "preview_title": "Transcription Preview",
        "status_preview": "Review the result (preview open)",
        "btn_save": "Save",
        "btn_copy": "Copy",
        "btn_discard": "Discard",
        "log_saved": "Saved: {path}",
        "log_copied": "Copied to clipboard.",
        "log_preview_discarded": "Closed without saving.",
        # Recording
        "rec_start_failed": "Failed to start recording: {msg}",
        "rec_unsupported_format": "Unsupported save format: '{ext}' (supported: {supported})",
    },
}


def detect_language() -> str:
    """OS のロケールから言語を自動判定する。"""
    loc = ""
    try:
        loc = locale.getlocale()[0] or ""
        if not loc:
            locale.setlocale(locale.LC_CTYPE, "")
            loc = locale.getlocale()[0] or ""
    except Exception:  # noqa: BLE001 - 判定に失敗したら英語にフォールバック
        pass
    low = loc.lower()
    return "ja" if ("ja" in low or "japan" in low) else "en"


def save_language(lang: str) -> None:
    """言語設定を保存する (次回起動時に反映)。"""
    set_value("language", lang)


def init_language() -> str:
    """設定ファイル (無ければロケール) から言語を初期化する。"""
    global _current_language
    lang = get_value("language")
    if lang not in _TRANSLATIONS:
        lang = detect_language()
    _current_language = lang
    return lang


def get_language() -> str:
    return _current_language


def tr(key: str, **kwargs: Any) -> str:
    """現在の言語で文字列を取得する。埋め込みは kwargs で渡す。"""
    table = _TRANSLATIONS.get(_current_language, _TRANSLATIONS["en"])
    text = table.get(key) or _TRANSLATIONS["en"].get(key) or key
    return text.format(**kwargs) if kwargs else text
