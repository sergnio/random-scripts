# WAV compression

`compress_wav.py` converts every WAV in a directory and its subdirectories. It keeps the relative folder structure, names, and file modification times. The script **never deletes or changes the original WAVs**.

## Requirements

- Python 3.9 or newer
- `ffmpeg` and `ffprobe` on your `PATH` (on a Mac with Homebrew: `brew install ffmpeg`)

No Python packages are required.

## Convert to AAC/M4A

For speech recordings, this uses the same 96 kb/s AAC setting used for the TX1 and TX2 archives:

```bash
python3 wav-compression/compress_wav.py \
  "/Volumes/RECORDER" \
  "$HOME/Downloads/Recorder-M4A" \
  --zip --verify-decode
```

The script writes one `.m4a` per WAV and creates `Recorder-M4A.zip` alongside the output folder. The ZIP keeps the folder structure and is checked for errors before the script reports success. Audio inside M4A is already compressed, so the ZIP is mainly for convenient upload.

AAC is **lossy**. A decoded WAV cannot recover audio detail discarded during encoding. Use `--aac-bitrate 128k` or higher if you want a larger, higher quality AAC file, especially for music or stereo recordings.

## Convert to lossless FLAC

```bash
python3 wav-compression/compress_wav.py \
  "/Volumes/RECORDER" \
  "$HOME/Downloads/Recorder-FLAC" \
  --codec flac --zip --verify-decode
```

FLAC preserves the audio samples. A WAV recreated from FLAC can have different headers or metadata; use a ZIP of the original WAVs if you need byte-for-byte identical files.

## Safety and recovery

- Choose an output directory **outside** the source directory. The script rejects an output inside the source.
- Existing valid outputs are skipped, so you can rerun the same command after an interruption. An invalid existing output causes an error; move it aside before retrying.
- New files are written to temporary names and renamed only after their codec and playback length are checked. `--verify-decode` also decodes each output to catch audio errors; it takes longer.
- The script does not overwrite an existing ZIP. Move or remove an old ZIP before rebuilding one.
- Keep the WAV originals until the converted files are in durable storage and you have checked the backup. Avoid `/tmp` for the only copy: macOS can clear it.

Run `python3 wav-compression/compress_wav.py --help` for all options.
