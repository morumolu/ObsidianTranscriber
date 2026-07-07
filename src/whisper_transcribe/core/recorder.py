import threading
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
import soundfile as sf

# Whisper の入力に最適な 16kHz モノラルで録音する
SAMPLE_RATE = 16000
CHANNELS = 1

# 保存形式: 拡張子 -> (libsndfile フォーマット, サブタイプ)
# OGG Vorbis は音声用途で WAV の約 1/7 のサイズになり、Whisper の精度への影響もほぼない
SAVE_FORMATS: dict[str, tuple[str, str | None]] = {
    ".ogg": ("OGG", "VORBIS"),
    ".flac": ("FLAC", None),
    ".mp3": ("MP3", None),
    ".wav": ("WAV", "PCM_16"),
}


class RecorderError(RuntimeError):
    """録音デバイスの初期化・操作に失敗したことを表す。"""


class Recorder:
    """マイク入力を録音するレコーダー。

    start() でストリームを開始し、コールバックでフレームを蓄積、
    stop() で音声データ (float32, モノラル) を返す。スレッドセーフ。
    """

    def __init__(self) -> None:
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._level: float = 0.0

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def level(self) -> float:
        """直近の入力レベル (RMS, 0.0-1.0) を返す。"""
        with self._lock:
            return self._level

    @property
    def elapsed_seconds(self) -> float:
        """録音済みの秒数を返す。"""
        with self._lock:
            total_frames = sum(len(f) for f in self._frames)

        return total_frames / SAMPLE_RATE

    def start(self) -> None:
        """録音を開始する。マイクが使えない場合は RecorderError を送出する。"""
        if self._stream is not None:
            return

        self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=self._on_audio,
            )

            assert self._stream is not None
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RecorderError(str(exc)) from exc

    def _on_audio(self, indata: np.ndarray, frames: int, time: Any, status: Any) -> None:
        rms = float(np.sqrt(np.mean(np.square(indata))))
        with self._lock:
            self._frames.append(indata.copy())
            self._level = rms

    def stop(self) -> np.ndarray:
        """録音を停止し、音声データを返す。"""
        if self._stream is None:
            return np.empty((0, CHANNELS), dtype=np.float32)

        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

        with self._lock:
            self._level = 0.0
            if not self._frames:
                return np.empty((0, CHANNELS), dtype=np.float32)

            data = np.concatenate(self._frames)
            self._frames = []

        return data

    @staticmethod
    def save(path: Path, data: np.ndarray) -> Path:
        """音声データを拡張子に応じた形式で保存する。"""
        fmt = SAVE_FORMATS.get(path.suffix.lower())
        if fmt is None:
            supported = ", ".join(sorted(SAVE_FORMATS))
            raise ValueError(
                f"Unsupported save format: '{path.suffix}' (supported: {supported})"
            )

        sf.write(str(path), data, SAMPLE_RATE, format=fmt[0], subtype=fmt[1])
        return path
