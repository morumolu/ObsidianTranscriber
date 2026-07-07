"""PyInstallerのエントリポイント。whisper_transcribeパッケージを正規のパッケージとして import させるための薄いランチャー。"""
from whisper_transcribe.ui.app import main

if __name__ == "__main__":
    main()
