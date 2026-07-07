"""core 層のユニットテスト (GUI 非依存)。"""
from pathlib import Path

import numpy as np
import pytest

from whisper_transcribe.core.models import model_name, resolve_device
from whisper_transcribe.core.model_size import ModelSize
from whisper_transcribe.core.recorder import SAMPLE_RATE, Recorder
from whisper_transcribe.core.transcribe import validate_input_file, validate_output_path


class TestModelName:
    def test_enum(self) -> None:
        assert model_name(ModelSize.large_v3) == "large-v3"

    def test_str(self) -> None:
        assert model_name("tiny") == "tiny"


class TestResolveDevice:
    def test_explicit_device_passthrough(self) -> None:
        assert resolve_device("cpu") == "cpu"
        assert resolve_device("cuda") == "cuda"


class TestValidators:
    def test_input_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            validate_input_file(tmp_path / "missing.wav")

    def test_input_unsupported_extension(self, tmp_path: Path) -> None:
        bad = tmp_path / "note.txt"
        bad.write_text("x")
        with pytest.raises(ValueError, match="Unsupported"):
            validate_input_file(bad)

    def test_output_dir_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            validate_output_path(tmp_path / "no_dir" / "out.md")

    def test_output_ok(self, tmp_path: Path) -> None:
        validate_output_path(tmp_path / "out.md")  # 例外が出ないこと


class TestRecorderSave:
    @pytest.fixture()
    def silence(self) -> np.ndarray:
        return np.zeros((SAMPLE_RATE, 1), dtype=np.float32)  # 1秒の無音

    @pytest.mark.parametrize("ext", [".wav", ".flac", ".ogg", ".mp3"])
    def test_save_formats(self, tmp_path: Path, silence: np.ndarray, ext: str) -> None:
        out = Recorder.save(tmp_path / f"rec{ext}", silence)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_save_unsupported_extension(self, tmp_path: Path, silence: np.ndarray) -> None:
        with pytest.raises(ValueError, match="Unsupported save format"):
            Recorder.save(tmp_path / "rec.xyz", silence)
