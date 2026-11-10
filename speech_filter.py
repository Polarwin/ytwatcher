"""Subtitle-first removal of long non-speech sections from audio subscriptions."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

MODEL_URL = ('https://raw.githubusercontent.com/snakers4/silero-vad/'
             '066409f3d9db45a30d21dfcbf9147826ffdd7052/src/silero_vad/data/silero_vad.onnx')
MODEL_SHA = '1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3'
MODEL_PATH = Path(__file__).parent / '.cache/silero-vad/silero_vad.onnx'
TIMING = re.compile(r'(?m)^(\d{2}(?::\d{2})?:\d{2}[.,]\d{3})\s+-->\s+'
                    r'(\d{2}(?::\d{2})?:\d{2}[.,]\d{3})[^\n]*\n')


def timestamp(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(part) * 60 ** n for n, part in enumerate(reversed(parts)))


def cues(path):
    text = path.read_text(encoding='utf-8-sig', errors='replace').replace('\r\n', '\n')
    result = []
    for block in re.split(r'\n\n+', text):
        match = TIMING.search(block)
        if match:
            result.append((timestamp(match[1]), timestamp(match[2]), block[match.end():].strip()))
    return result


def merge(spans, duration):
    result = []
    for start, end in sorted(spans):
        start, end = max(0., start), min(duration, end)
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def subtitle_speech(paths, duration):
    """Pick one complete track rather than combining overlapping translations."""
    for path in sorted(paths, key=lambda p: (not p.name.endswith('.en-orig.vtt'), p.name)):
        spans, words = [], 0
        track_cues = cues(path)
        music_spans = [(a, b) for a, b, text in track_cues
                       if re.search(r'\[\s*music\s*\]', text, re.I)]
        for start, end, raw in track_cues:
            text = html.unescape(re.sub(r'<[^>]*>', '', raw))
            music_label = bool(re.search(r'\[\s*music\s*\]', text, re.I))
            text = re.sub(r'\[[^\]]*\]|\([^)]*(?:music|applause|laughter)[^)]*\)', '', text, flags=re.I)
            text = text.replace('♪', '').replace('♫', '').strip()
            tokens = re.findall(r"[A-Za-z]+", text.casefold())
            # YouTube often captions instrumental breaks as "Heat. Heat."
            # alongside [music]. Ignore those fillers only near music labels;
            # substantive speech over background music remains speech.
            if (tokens and set(tokens) <= {'heat', 'hey', 'oh', 'ah', 'ooh', 'hmm'} and
                    any(start < b + 2 and end > a - 2 for a, b in music_spans)):
                continue
            if music_label and not tokens:
                continue
            if not re.search(r'[A-Za-z\u00c0-\uffff]', text):
                continue
            if text.casefold() in ('music', 'applause', 'laughter'):
                continue
            # A subtitle cue claiming minutes of speech is not a usable guide.
            if end - start > 45:
                continue
            words += len(text.split())
            spans.append((start, end))
        cue_count = len(spans)
        spans = merge(spans, duration)
        covered = sum(end - start for start, end in spans)
        # Reject empty, tiny or obviously truncated tracks; fall back to VAD.
        if cue_count >= 10 and words >= 100 and covered >= duration * .03 and spans[-1][1] >= duration * .7:
            return spans, path.name
    return None, None


def vad_speech(media, duration, threshold=.5):
    """Silero's pinned ONNX model on CPU, fed 16kHz mono audio by FFmpeg."""
    import numpy as np
    import onnxruntime as ort
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not MODEL_PATH.exists():
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != MODEL_SHA:
            raise ValueError('Silero model checksum mismatch')
        temporary = MODEL_PATH.with_suffix('.download')
        temporary.write_bytes(data)
        temporary.replace(MODEL_PATH)
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA:
        raise ValueError('Silero model checksum mismatch')
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(MODEL_PATH), sess_options=options, providers=['CPUExecutionProvider'])
    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros((1, 64), dtype=np.float32)
    spans, start, last_voice = [], None, None
    # A temporary PCM file bounds memory and avoids leaving decoder subprocesses.
    with tempfile.TemporaryDirectory(prefix='ytwatcher-vad-') as folder:
        pcm = Path(folder) / 'audio.pcm'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(media), '-vn',
                        '-ac', '1', '-ar', '16000', '-f', 's16le', str(pcm)],
                       check=True, capture_output=True, timeout=1800)
        with pcm.open('rb') as source:
            index = 0
            while raw := source.read(1024):
                audio = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768
                audio = np.pad(audio, (0, 512 - len(audio)))[None, :]
                output, state = session.run(None, {'input': np.concatenate((context, audio), axis=1),
                                                   'state': state, 'sr': np.array(16000, dtype=np.int64)})
                context = audio[:, -64:]
                t = index * .032
                if float(output.flat[0]) >= threshold:
                    if start is None:
                        start = t
                    last_voice = min(duration, t + .032)
                elif start is not None and t - last_voice >= .5:
                    if last_voice - start >= .25:
                        spans.append((start, last_voice))
                    start = last_voice = None
                index += 1
            if start is not None and last_voice - start >= .25:
                spans.append((start, last_voice))
    return merge(spans, duration)


def analyse(media, subtitles, options):
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format',
                                               '-show_streams', '-of', 'json', str(media)], timeout=120))
    duration = float(info['format']['duration'])
    if duration <= options.get('min_duration', 1200):
        return {'duration': duration, 'keep': [[0, duration]], 'remove': [], 'method': 'below-duration-threshold'}
    if any(s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic') for s in info['streams']):
        raise ValueError('Speech filtering is limited to audio-only downloads')
    spans, track = subtitle_speech(subtitles, duration)
    method = 'subtitles'
    if spans is None:
        method = 'silero-vad-cpu'
        spans = vad_speech(media, duration, options.get('vad_threshold', .5))
    if not spans or sum(b - a for a, b in spans) < 10:
        raise ValueError('Too little detected speech; keeping original for safety')
    gap, padding = options.get('min_gap', 30), options.get('padding', 2)
    remove, end = [], 0.
    for start, stop in [*spans, [duration, duration]]:
        if start - end >= gap:
            a, b = end + (padding if end else 0), start - (padding if start < duration else 0)
            if b > a:
                remove.append([a, b])
        end = max(end, stop)
    keep, end = [], 0.
    for a, b in remove:
        if a > end:
            keep.append([end, a])
        end = b
    if end < duration:
        keep.append([end, duration])
    return {'duration': duration, 'method': method, 'subtitle': track, 'keep': keep,
            'remove': remove, 'output_duration': sum(b - a for a, b in keep),
            'min_gap': gap, 'padding': padding}


def vtt_time(seconds):
    ms = round(seconds * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


def retime(source, target, keep):
    blocks, offset = [], 0.
    original = cues(source)
    for begin, end in keep:
        for a, b, text in original:
            if b <= begin or a >= end:
                continue
            # YouTube's rolling captions embed original timestamps in cue text.
            text = re.sub(r'<\d{2}(?::\d{2})?:\d{2}[.,]\d{3}>', '', text)
            blocks.append(f'{vtt_time(offset + max(a, begin) - begin)} --> '
                          f'{vtt_time(offset + min(b, end) - begin)}\n{text}')
        offset += end - begin
    target.write_text('WEBVTT\n\n' + '\n\n'.join(blocks) + '\n')


def render(media, output, report):
    filters = [f'[0:a]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS[a{i}]'
               for i, (a, b) in enumerate(report['keep'])]
    filters.append(''.join(f'[a{i}]' for i in range(len(report['keep']))) +
                   f'concat=n={len(report["keep"])}:v=0:a=1[out]')
    # atrim cuts at audio samples so the rewritten subtitle clock stays aligned.
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(media), '-vn',
                    '-filter_complex', ';'.join(filters), '-map', '[out]', '-c:a', 'aac',
                    '-b:a', '128k', '-movflags', '+faststart', str(output)],
                   check=True, capture_output=True, timeout=3600)
    actual = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                   'format=duration', '-of', 'default=nw=1:nk=1', str(output)], timeout=120))
    if abs(actual - report['output_duration']) > max(2, len(report['keep']) * .1):
        raise ValueError('Filtered duration failed validation')
    return actual


def process(media, subtitles, options):
    """Stage all outputs, then replace; leave originals intact on any error."""
    report_file = media.with_name(media.stem + '.speech-filter.json')
    if report_file.exists():
        previous = json.loads(report_file.read_text())
        if previous.get('processed_file') == media.name and previous.get('processed_size') == media.stat().st_size:
            return media, float(previous['output_duration'])
    report = analyse(media, subtitles, options)
    if not report['remove']:
        return media, report['duration']
    target = media.with_suffix('.m4a')
    if target != media and target.exists():
        raise ValueError('Filtered target already exists; keeping original files')
    with tempfile.TemporaryDirectory(prefix='.speech-filter-', dir=media.parent) as folder:
        folder = Path(folder)
        audio = folder / 'filtered.m4a'
        duration = render(media, audio, report)
        updated = []
        for index, subtitle in enumerate(subtitles):
            staged = folder / f'{index}.vtt'
            retime(subtitle, staged, report['keep'])
            updated.append((subtitle, staged))
        # Roll back even a partial installation if a filesystem operation fails.
        backups = [(p, folder / f'original-{i}') for i, p in enumerate([media, *subtitles])]
        for source, backup in backups:
            shutil.copy2(source, backup)
        try:
            for subtitle, staged in updated:
                staged.replace(subtitle)
            audio.replace(target)
            if target != media:
                media.unlink()
            report['output_duration'] = duration
            report['original_file'] = media.name
            report['processed_file'] = target.name
            report['processed_size'] = target.stat().st_size
            report_file.write_text(json.dumps(report, indent=2))
        except Exception:
            for original, backup in backups:
                shutil.copy2(backup, original)
            if target != media:
                target.unlink(missing_ok=True)
            report_file.unlink(missing_ok=True)
            raise
    for dictionary in media.parent.iterdir():
        if not dictionary.name.startswith(media.stem + '.') or not dictionary.name.endswith('.dict.json'):
            continue
        try:
            dictionary.unlink(missing_ok=True)
        except OSError:
            pass
    return target, duration


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('media', type=Path)
    parser.add_argument('--subtitle', action='append', type=Path, default=[])
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--preview', type=Path)
    args = parser.parse_args()
    result = analyse(args.media, args.subtitle, {})
    args.report.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    if args.preview and result['remove']:
        render(args.media, args.preview, result)
