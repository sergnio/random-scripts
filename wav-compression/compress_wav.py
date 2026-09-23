#!/usr/bin/env python3
"""Convert a tree of WAV files to AAC/M4A or FLAC without touching the originals."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile


def parse_args() -> argparse.Namespace:
    """Parse command line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Directory containing WAV files')
    parser.add_argument('output', type=Path, help='Directory for converted files')
    parser.add_argument('--codec', choices=('aac', 'flac'), default='aac')
    parser.add_argument('--aac-bitrate', default='96k', help='AAC bitrate (default: 96k)')
    parser.add_argument('--zip', action='store_true', help='Create and verify a ZIP of the outputs')
    parser.add_argument(
        '--verify-decode',
        action='store_true',
        help='Fully decode each output to check for audio errors',
    )
    args = parser.parse_args()
    if not re.fullmatch(r'[1-9][0-9]*[kKmM]?', args.aac_bitrate):
        parser.error('--aac-bitrate must look like 96k or 128k')
    if not args.source.is_dir():
        parser.error(f'Source directory does not exist: {args.source}')
    source = args.source.resolve()
    output = args.output.resolve()
    try:
        output.relative_to(source)
    except ValueError:
        pass
    else:
        parser.error('Output must be outside the source directory')
    if shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None:
        parser.error('ffmpeg and ffprobe must be installed and on PATH')
    return args


def find_wavs(source: Path) -> list[Path]:
    """Find WAVs while avoiding hidden metadata directories and AppleDouble files."""
    wavs: list[Path] = []
    for directory, subdirectories, filenames in os.walk(source, onerror=_raise_walk_error):
        subdirectories[:] = [name for name in subdirectories if not name.startswith('.')]
        for filename in filenames:
            if filename.startswith('.') or Path(filename).suffix.lower() != '.wav':
                continue
            path = Path(directory) / filename
            if path.is_file() and not path.is_symlink():
                wavs.append(path)
    return sorted(wavs)


def _raise_walk_error(error: OSError) -> None:
    """Fail if any source directory cannot be scanned."""
    raise error


def probe_audio(path: Path) -> tuple[str, float]:
    """Return the first audio codec and container duration for a file."""
    result = subprocess.check_output(
        [
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name:format=duration',
            '-of', 'json', str(path),
        ],
        text=True,
    )
    data = json.loads(result)
    codec = data['streams'][0]['codec_name']
    duration = float(data['format']['duration'])
    if duration <= 0:
        raise ValueError(f'No positive audio duration: {path}')
    return codec, duration


def verify_output(source: Path, output: Path, codec: str, decode: bool) -> None:
    """Check codec, playback length, and optionally the full decoded output."""
    actual_codec, output_duration = probe_audio(output)
    _, source_duration = probe_audio(source)
    if actual_codec != codec:
        raise ValueError(f'Expected {codec}, found {actual_codec}: {output}')
    if abs(output_duration - source_duration) > 0.25:
        raise ValueError(
            f'Playback length differs by more than 0.25 seconds: {source} -> {output}'
        )
    if decode:
        subprocess.run(
            [
                'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
                '-i', str(output), '-map', '0:a:0', '-f', 'null', '-',
            ],
            check=True,
        )


def convert(source: Path, output: Path, codec: str, bitrate: str, decode: bool) -> bool:
    """Convert one WAV, returning True when a new output was created."""
    if output.exists():
        verify_output(source, output, codec, decode)
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f'.{output.stem}.{os.getpid()}.partial{output.suffix}')
    if temporary.exists():
        raise FileExistsError(f'Temporary output already exists: {temporary}')
    command = [
        'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
        '-i', str(source), '-map', '0:a:0', '-map_metadata', '0',
    ]
    if codec == 'aac':
        command.extend(['-c:a', 'aac', '-b:a', bitrate])
    else:
        command.extend(['-c:a', 'flac', '-compression_level', '5'])
    command.append(str(temporary))
    try:
        subprocess.run(command, check=True)
        verify_output(source, temporary, codec, decode)
        if output.exists():
            raise FileExistsError(f'Output appeared during conversion: {output}')
        os.replace(temporary, output)
        os.utime(output, (time.time(), source.stat().st_mtime))
    finally:
        temporary.unlink(missing_ok=True)
    return True


def create_zip(output_root: Path, outputs: list[Path]) -> Path:
    """Store the converted files in a checked ZIP next to the output folder."""
    archive = output_root.parent / f'{output_root.name}.zip'
    if archive.exists():
        raise FileExistsError(f'ZIP already exists; move it aside first: {archive}')
    temporary = archive.with_name(f'.{archive.name}.{os.getpid()}.partial')
    if temporary.exists():
        raise FileExistsError(f'Temporary ZIP already exists: {temporary}')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zip_file:
            for path in outputs:
                relative_name = path.relative_to(output_root).as_posix()
                zip_file.write(path, arcname=f'{output_root.name}/{relative_name}')
        with zipfile.ZipFile(temporary) as zip_file:
            bad_file = zip_file.testzip()
            if bad_file is not None:
                raise ValueError(f'ZIP failed CRC check: {bad_file}')
            if len(zip_file.namelist()) != len(outputs):
                raise ValueError('ZIP file count does not match converted file count')
        if archive.exists():
            raise FileExistsError(f'ZIP appeared during creation: {archive}')
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def main() -> int:
    """Convert all WAVs, report errors, and optionally create an upload ZIP."""
    args = parse_args()
    source_root = args.source.resolve()
    output_root = args.output.resolve()
    extension = '.m4a' if args.codec == 'aac' else '.flac'
    wavs = find_wavs(source_root)
    if not wavs:
        print('No WAV files found.', file=sys.stderr)
        return 1
    failures: list[str] = []
    outputs: list[Path] = []
    started = time.monotonic()
    print(f'Found {len(wavs)} WAV files.')
    for index, source in enumerate(wavs, 1):
        output = output_root / source.relative_to(source_root).with_suffix(extension)
        try:
            created = convert(source, output, args.codec, args.aac_bitrate, args.verify_decode)
            outputs.append(output)
            action = 'Converted' if created else 'Verified existing'
            print(f'[{index}/{len(wavs)}] {action}: {output.relative_to(output_root)}', flush=True)
        except Exception as error:
            failures.append(f'{source}: {error}')
            print(f'[{index}/{len(wavs)}] ERROR: {error}', file=sys.stderr, flush=True)
    if failures:
        print(f'{len(failures)} conversion(s) failed; no ZIP was made.', file=sys.stderr)
        return 1
    source_bytes = sum(path.stat().st_size for path in wavs)
    output_bytes = sum(path.stat().st_size for path in outputs)
    print(
        f'{len(outputs)} files: {source_bytes / 1024**2:.1f} MiB WAV -> '
        f'{output_bytes / 1024**2:.1f} MiB {args.codec.upper()} '
        f'in {(time.monotonic() - started) / 60:.1f} minutes.'
    )
    if args.zip:
        try:
            archive = create_zip(output_root, outputs)
            print(f'Checked ZIP: {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)')
        except Exception as error:
            print(f'ZIP failed: {error}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
