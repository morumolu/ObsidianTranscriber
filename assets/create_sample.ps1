param(
    [string]$FileName = "sample.wav"
)

if ($FileName -notmatch '\.wav$') {
    $FileName += ".wav"
}

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

$outputPath = Join-Path $PSScriptRoot $FileName
$synth.SetOutputToWaveFile($outputPath)
$synth.Speak("This is a test recording for Whisper.")
$synth.Dispose()

Write-Host "Saved to: $outputPath"