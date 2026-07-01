from faster_whisper import WhisperModel


def main():
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")

    segments, info = model.transcribe("recording.mp3", language="ja")
    for segment in segments:
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")


if __name__ == "__main__":
    main()