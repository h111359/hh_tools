"""Offline transcription primitives. Times are seconds from the original audio start."""
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

VERSION = '1.0.0'


def atomic(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    with tmp.open('w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-3000:])
    return r.stdout


def probe(path):
    d = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
    audio = next((s for s in d['streams'] if s['codec_type'] == 'audio'), None)
    if audio is None:
        raise ValueError('No audio stream')
    duration = float(audio.get('duration', d['format'].get('duration', 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Empty audio or unknown duration')
    return d, audio, duration


def prepare(source, target, channel=None):
    temp = target.with_suffix('.tmp.wav')
    cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source), '-map', '0:a:0']
    if channel is not None:
        cmd += ['-af', f'pan=mono|c0=c{channel}']
    cmd += ['-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(temp)]
    run(cmd)
    temp.replace(target)


def silence_boundaries(wav, cfg):
    cmd = ['ffmpeg', '-nostdin', '-i', str(wav), '-af',
           f"silencedetect=noise={cfg['silence_db']}dB:d={cfg['silence_seconds']}", '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    starts, mids = [], []
    for line in r.stderr.splitlines():
        m = re.search(r'silence_start: ([\d.]+)', line)
        if m:
            starts.append(float(m[1]))
        m = re.search(r'silence_end: ([\d.]+)', line)
        if m and starts:
            mids.append((starts.pop() + float(m[1])) / 2)
    return mids


def chunks(duration, boundaries, maximum, overlap, search):
    if duration <= 0 or not 0 <= overlap < maximum / 4 or maximum < 5:
        raise ValueError('Require positive audio, chunk >=5s and overlap < chunk/4')
    # Core ownership intervals partition the timeline. Padded intervals never exceed maximum.
    core_max = maximum - 2 * overlap
    start = 0.0
    result = []
    while start < duration - 1e-6:
        end = min(duration, start + core_max)
        options = [t for t in boundaries if max(start + core_max / 2, end - search) <= t <= end]
        if end < duration and options:
            end = max(options)
        result.append({'core_start': start, 'core_end': end,
                       'start': max(0, start - overlap), 'end': min(duration, end + overlap)})
        start = end
    return result


def owned_words(words, chunk):
    # Never deduplicate text by phrase: true repetition at different times survives.
    return [w for w in words if chunk['core_start'] <= (w['start'] + w['end']) / 2 < chunk['core_end']]


def timestamp(seconds, subtitle=False):
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02}:{m:02}:{s:02}{"," if subtitle else "."}{ms:03}'


def signals(segment, cfg):
    flags = []
    if segment['avg_logprob'] < cfg['review_logprob']:
        flags.append('low_logprob')
    if segment['no_speech_prob'] > 0.6:
        flags.append('possible_text_over_silence')
    if segment['compression_ratio'] > 2.4 or re.search(r'\b(\w+)(?:\W+\1){2,}\b', segment['text'], re.I):
        flags.append('repetition')
    if any(w['probability'] < cfg['review_word_probability'] for w in segment['words']):
        flags.append('low_word_score')
    if re.search(r'\d|\b[A-Z]{2,}\b', segment['text']):
        flags.append('verify_number_or_acronym')
    return flags


def export(job, segments, reviews, cfg, names):
    faithful = ['# Faithful transcript', '', 'Automatic recognition; wording and speaker labels require review.', '']
    readable = ['# Readable transcript', '', 'Conservative formatting only; recognized wording retained.', '']
    plain, srt = [], []
    for s in segments:
        label = names.get(s['speaker'], s['speaker'])
        marker = ' [uncertain wording]' if s['flags'] else ''
        attribution = ' [speaker uncertain]' if s['speaker'] == 'Speaker unknown' else ''
        heading = f"[{timestamp(s['start'])}–{timestamp(s['end'])}] {label}{attribution}"
        body = s['text'].strip()
        faithful += [f'**{heading}**{marker}', '', body, '']
        readable += [f'**{heading}**{marker}', '', ' '.join(body.split()), '']
        plain.append(f'{heading}{marker}: {body}')
        if body and s['end'] > s['start']:
            end = max(s['end'], s['start'] + 0.001)
            srt.append(f"{len(srt)+1}\n{timestamp(s['start'], True)} --> {timestamp(end, True)}\n{label}: {body}{marker}\n")
    if 'md' in cfg['formats']:
        atomic(job / 'faithful.md', '\n'.join(faithful))
        atomic(job / 'readable.md', '\n'.join(readable))
    if 'txt' in cfg['formats']:
        atomic(job / 'transcript.txt', '\n'.join(plain))
    if 'srt' in cfg['formats']:
        atomic(job / 'transcript.srt', '\n'.join(srt))
    if 'json' in cfg['formats']:
        atomic(job / 'transcript.json', {'schema_version': 1, 'time_origin': 'original recording start', 'segments': segments})
    report = ['# Review report', '', 'Scores are heuristic model signals, not calibrated correctness probabilities.',
              'The first pass is retained. Alternatives are evidence for human listening, never automatic corrections.', '']
    for r in reviews:
        report += [f"## {timestamp(r['start'])}–{timestamp(r['end'])}: {', '.join(r['flags'])}", '',
                   'First pass: ' + (r.get('text') or '[no recognized speech]'), '']
        if r.get('attempt'):
            report += ['Alternative: ' + r['attempt']['text'], '', 'Attempt artifact: ' + r['artifact'], '']
    if not reviews:
        report += ['No passages flagged. This does not establish correctness.']
    atomic(job / 'review.md', '\n'.join(report))
    atomic(job / 'review.json', reviews)
