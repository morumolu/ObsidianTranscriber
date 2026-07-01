import typer
from faster_whisper import WhisperModel
from pathlib import Path
app = typer.Typer()

DEFAULT_FILE = Path(__file__).parent.parent.parent / "assets" / "sample.wav"

@app.command()
def transcribe(
    input_file: str = typer.Option(DEFAULT_FILE, "--input", "-i", help="Path to the audio file to transcribe"),
    model_size: str = typer.Option("large-v3", "--model", "-m", help="Whisper model size"),
    language: str = typer.Option("ja", "--language", "-l", help="Audio language code"),
):
    """Transcribe an audio file using faster-whisper."""
    typer.echo(f"Loading model: {model_size}")
    model = WhisperModel(model_size, device="cuda", compute_type="float16")

    typer.echo(f"Transcribing: {input_file}")
    segments, info = model.transcribe(input_file, language=language)

    for segment in segments:
        typer.echo(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")


if __name__ == "__main__":
    app()