#!/usr/bin/env python3
"""Local-only entry point. Run with speech2text/.venv/bin/python."""
import argparse
import dataclasses
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import wave

ROOT = Path(__file__).resolve().parent
os.environ['HF_HOME'] = str(ROOT / 'cache/huggingface')
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
from transcription.core import (VERSION, atomic, chunks, export, key, owned_words,
                                prepare, probe, sha256, signals, silence_boundaries)


def log(message):
    print(time.strftime('%H:%M:%S') + ' ' + message, flush=True)


def model_receipt(path):
    r = json.loads((path / 'receipt.json').read_text())
    required = {'config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt'}
    if not required <= r['sha256'].keys():
        raise ValueError('Incomplete model receipt')
    for name, digest in r['sha256'].items():
        if sha256(path / name) != digest:
            raise ValueError('Model checksum mismatch: ' + name)
    return r


def preflight(cfg):
    import ctranslate2
    import faster_whisper
    import numpy
    from faster_whisper.vad import get_vad_model
    for tool in ['ffmpeg', 'ffprobe']:
        if not shutil.which(tool):
            raise RuntimeError(f'Missing system dependency: {tool}')
    supported = ctranslate2.get_supported_compute_types(cfg['device'])
    if cfg['compute_type'] not in supported:
        raise ValueError(f"Unsupported precision; choose from {sorted(supported)}")
    receipt = model_receipt(Path(cfg['model_path']))
    get_vad_model()  # ONNX VAD comes with faster-whisper, no model download.
    versions = {n: importlib.metadata.version(n) for n in ['faster-whisper', 'ctranslate2', 'av', 'onnxruntime', 'numpy']}
    return {'python': sys.version, 'platform': platform.platform(), 'cpu': platform.processor(),
            'logical_cpus': os.cpu_count(), 'compute_types': sorted(supported), 'versions': versions,
            'disk_free_bytes': shutil.disk_usage(ROOT).free,
            'memory': Path('/proc/meminfo').read_text() if Path('/proc/meminfo').exists() else 'unavailable',
            'ffmpeg': __import__('subprocess').check_output(['ffmpeg', '-version'], text=True).splitlines()[0],
            'model': receipt}


def read_audio(path, start, end):
    import numpy as np
    with wave.open(str(path), 'rb') as w:
        w.setpos(min(w.getnframes(), round(start * 16000)))
        return np.frombuffer(w.readframes(round((end-start)*16000)), dtype='<i2').astype(np.float32) / 32768


def recognize(model, wav, interval, cfg, prompt, language, review=False):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    audio = read_audio(wav, interval['start'], interval['end'])
    vad = get_speech_timestamps(audio, VadOptions(threshold=cfg['vad_threshold'], min_silence_duration_ms=400))
    settings = {'beam_size': 5 if review or cfg['mode'] == 'careful' else 1,
                'temperature': 0.0, 'condition_on_previous_text': False,
                'word_timestamps': True, 'vad_filter': True,
                'vad_parameters': {'threshold': cfg['vad_threshold'], 'min_silence_duration_ms': 400},
                'initial_prompt': prompt or None, 'language': language}
    result = {'interval': interval, 'settings': settings, 'segments': [],
              'speech_regions': [{'start': interval['start']+v['start']/16000,
                                  'end': interval['start']+v['end']/16000} for v in vad]}
    if not vad:
        return result
    iterator, info = model.transcribe(audio, **settings)
    result['detected_language'] = info.language
    result['language_score'] = info.language_probability
    for seg in iterator:
        d = dataclasses.asdict(seg)
        offset = interval['start']
        words = [{'start': max(offset, offset+w['start']), 'end': min(interval['end'], offset+w['end']),
                  'word': w['word'], 'probability': w['probability']} for w in (d['words'] or [])]
        result['segments'].append({'start': offset+d['start'], 'end': min(interval['end'], offset+d['end']),
                                  'text': d['text'], 'words': words, 'avg_logprob': d['avg_logprob'],
                                  'no_speech_prob': d['no_speech_prob'], 'compression_ratio': d['compression_ratio']})
    return result


def pipeline(args, cfg):
    start_time = time.monotonic()
    source = Path(args.audio).resolve()
    if not source.is_file():
        raise ValueError('Audio file not found')
    metadata, stream, duration = probe(source)
    if cfg['speakers'] == 'channels' and stream['channels'] < 2:
        raise ValueError('Channel speaker separation requires at least two channels')
    if stream['channels'] > 1 and cfg['speakers'] == 'none':
        raise ValueError('Multichannel input: explicitly choose --speakers channels or --mix-channels')
    prompt_parts = []
    for field in ['context', 'glossary']:
        if cfg[field]:
            prompt_parts.append(Path(cfg[field]).read_text(encoding='utf-8'))
    prompt = '\n'.join(prompt_parts)
    if len(prompt) > 1800:
        raise ValueError('Context/glossary too long; keep combined hints under 1800 characters (Whisper has a limited prompt token window).')
    names = json.loads(Path(args.speaker_map).read_text()) if args.speaker_map else {}
    if not isinstance(names, dict) or not all(isinstance(v, str) for v in names.values()):
        raise ValueError('Speaker map must be a JSON object with string names')
    log('Preflight: verifying local model and dependencies')
    hardware = preflight(cfg)
    identity = {'sha256': sha256(source), 'bytes': source.stat().st_size}
    effective = dict(cfg, prompt_content=prompt, speaker_names=names)
    code_hash = key({p.name: sha256(p) for p in [Path(__file__), ROOT/'transcription/core.py']})
    job_key = key({'input': identity, 'config': effective, 'model': hardware['model'],
                   'versions': hardware['versions'], 'code': code_hash})
    output = Path(cfg['output_dir']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    job = output / f'{source.stem}-{job_key[:16]}'
    # OS advisory lock survives crashes without stale locks; per-job mutations serialized.
    lock = (output / f'.{job_key}.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('This job is already running')
    if job.exists() and not args.resume:
        if not args.overwrite:
            lock.close()
            raise FileExistsError(f'Results exist: {job}; use --resume or --overwrite')
        backup = job.with_name(job.name + f'.backup-{time.time_ns()}')
        job.rename(backup)
        log(f'Previous job preserved at {backup}')
    job.mkdir(exist_ok=True)
    artifacts = job / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    manifest_path = job / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'schema_version': 1, 'tool_version': VERSION, 'job_key': job_key, 'input': dict(identity, path=str(source)),
        'config': effective, 'hardware': hardware, 'metadata': metadata, 'runs': [], 'stages': {}, 'fallbacks': []}
    manifest['runs'].append({'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'resume': args.resume})
    manifest['status'] = 'running'
    atomic(manifest_path, manifest)
    try:
        count = stream['channels'] if cfg['speakers'] == 'channels' else 1
        plans = []
        log('Audio preparation: 16 kHz PCM, originals preserved')
        for channel in range(count):
            wav = artifacts / f'channel-{channel}.wav'
            plan_file = artifacts / f'plan-{channel}.json'
            if not wav.exists():
                prepare(source, wav, channel if cfg['speakers'] == 'channels' else None)
            if plan_file.exists():
                plan = json.loads(plan_file.read_text())
            else:
                plan = chunks(duration, silence_boundaries(wav, cfg), cfg['chunk_seconds'], cfg['overlap_seconds'], cfg['boundary_search_seconds'])
                atomic(plan_file, plan)
            plans.extend((channel, wav, i, c) for i, c in enumerate(plan))
        manifest['stages']['preparation_seconds'] = time.monotonic()-start_time
        atomic(manifest_path, manifest)
        model = None
        def get_model():
            nonlocal model
            if model is None:
                from faster_whisper import WhisperModel
                log(f"Model loading: {cfg['model_path']} ({cfg['device']}/{cfg['compute_type']})")
                model = WhisperModel(cfg['model_path'], device=cfg['device'], compute_type=cfg['compute_type'],
                                     cpu_threads=cfg['threads'], num_workers=1, local_files_only=True)
            return model
        first_start = time.monotonic()
        segments, reviews = [], []
        for done, (channel, wav, idx, c) in enumerate(plans):
            checkpoint = artifacts / f'first-{channel}-{idx}.json'
            if checkpoint.exists():
                result = json.loads(checkpoint.read_text())
                log(f'Resume: using chunk {done+1}/{len(plans)}')
            else:
                result = recognize(get_model(), wav, c, cfg, prompt, cfg['language'])
                atomic(checkpoint, result)
                elapsed = time.monotonic()-first_start
                eta = elapsed / (done+1) * (len(plans)-done-1)
                log(f'Transcription {done+1}/{len(plans)}; elapsed {elapsed:.1f}s; rough remaining {eta:.1f}s')
            label = f'Speaker {channel+1}' if cfg['speakers'] == 'channels' else 'Speaker unknown'
            for s in result['segments']:
                words = owned_words(s['words'], c)
                if not words:
                    continue
                s = dict(s, words=words, start=words[0]['start'], end=words[-1]['end'],
                         text=''.join(w['word'] for w in words).strip(), speaker=label, channel=channel)
                s['flags'] = signals(s, cfg)
                if (c['core_start'] > 0 and s['start'] < c['core_start']+1) or (c['core_end'] < duration and s['end'] > c['core_end']-1):
                    s['flags'].append('chunk_boundary')
                segments.append(s)
                if s['flags']:
                    reviews.append(dict(s, wav=str(wav)))
            for region in result['speech_regions']:
                middle = (region['start']+region['end'])/2
                if c['core_start'] <= middle < c['core_end'] and region['end']-region['start'] > 0.5:
                    if not any(s['start'] < region['end'] and s['end'] > region['start'] for s in result['segments']):
                        gap = dict(region, text='[unrecognized audio; speech detector flagged this region]',
                                   flags=['speech_without_text'], speaker=label, channel=channel, words=[])
                        segments.append(gap)
                        reviews.append(dict(gap, wav=str(wav)))
        manifest['stages']['first_pass_seconds'] = time.monotonic()-first_start
        atomic(artifacts / 'first-pass.json', segments)
        review_start = time.monotonic()
        if cfg['mode'] == 'careful':
            for index, r in enumerate(reviews[:cfg['review_max_attempts']]):
                left = max(0, r['start']-cfg['review_padding_seconds'])
                right = min(duration, r['end']+cfg['review_padding_seconds'], left+cfg['review_max_seconds'])
                path = artifacts / f'review-{index}.json'
                if path.exists():
                    attempt = json.loads(path.read_text())
                else:
                    log(f'Review {index+1}/{min(len(reviews), cfg["review_max_attempts"])}: {left:.1f}–{right:.1f}s')
                    attempt = recognize(get_model(), Path(r['wav']), {'start': left, 'end': right}, cfg, prompt, cfg['language'], review=True)
                    atomic(path, attempt)
                # Compare only the target interval; surrounding context is retained in artifact.
                target_words = [w for s in attempt['segments'] for w in s['words'] if r['start'] <= (w['start']+w['end'])/2 <= r['end']]
                alt = ''.join(w['word'] for w in target_words).strip()
                r['attempt'] = {'text': alt, 'interval': attempt['interval']}
                r['artifact'] = str(path.relative_to(job))
                if ' '.join(alt.casefold().split()) != ' '.join(r['text'].casefold().split()):
                    r['flags'] = list(r['flags']) + ['pass_disagreement']
        manifest['stages']['review_seconds'] = time.monotonic()-review_start
        segments.sort(key=lambda s: (s['start'], s['channel']))
        for i, s in enumerate(segments):
            if any(t['channel'] != s['channel'] and t['start'] < s['end'] and t['end'] > s['start'] for t in segments[:i]):
                s['flags'].append('cross_channel_overlap_or_bleed')
                reviews.append(dict(s))
        for r in reviews:
            r.pop('wav', None)
        export(job, segments, reviews, cfg, names)
        manifest['status'] = 'complete'
        manifest['review_count'] = len(reviews)
        manifest['runs'][-1]['elapsed_seconds'] = time.monotonic()-start_time
        atomic(manifest_path, manifest)
        log(f'Complete in {time.monotonic()-start_time:.1f}s: {job}')
    except BaseException as exc:
        manifest['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'
        manifest['error'] = str(exc)
        manifest['runs'][-1]['elapsed_seconds'] = time.monotonic()-start_time
        atomic(manifest_path, manifest)
        raise
    finally:
        lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('audio', nargs='?')
    p.add_argument('--config', type=Path, default=ROOT/'config/default.json')
    p.add_argument('--mode', choices=['draft', 'careful'], default='careful')
    p.add_argument('--preflight', action='store_true')
    p.add_argument('--offline', action='store_true', help='Always enforced, including without this flag')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--resume', action='store_true')
    group.add_argument('--overwrite', action='store_true', help='Back up existing job then restart')
    p.add_argument('--output-dir')
    p.add_argument('--model-path')
    p.add_argument('--device', choices=['cpu', 'cuda'])
    p.add_argument('--compute-type')
    p.add_argument('--language', help='Language code or auto')
    p.add_argument('--glossary')
    p.add_argument('--context')
    p.add_argument('--speakers', choices=['none', 'channels'])
    p.add_argument('--mix-channels', action='store_true')
    p.add_argument('--speaker-map')
    p.add_argument('--chunk-seconds', type=float)
    a = p.parse_args()
    cfg = json.loads(a.config.read_text())
    for field in ['output_dir', 'model_path']:
        cfg[field] = str((ROOT / cfg[field]).resolve())
    for field in ['output_dir', 'model_path', 'device', 'compute_type', 'language', 'glossary', 'context', 'speakers', 'chunk_seconds']:
        if getattr(a, field) is not None:
            cfg[field] = getattr(a, field)
    if a.mix_channels:
        if cfg['speakers'] == 'channels':
            p.error('--mix-channels conflicts with --speakers channels')
        cfg['speakers'] = 'mix'
    if cfg['language'] == 'auto':
        cfg['language'] = None
    cfg['mode'] = a.mode
    if cfg['threads'] < 1 or cfg['review_max_attempts'] < 0 or not 0 < cfg['vad_threshold'] < 1:
        p.error('Invalid resource/VAD settings')
    chunks(1, [], cfg['chunk_seconds'], cfg['overlap_seconds'], cfg['boundary_search_seconds'])
    if not set(cfg['formats']) <= {'md', 'txt', 'json', 'srt'}:
        p.error('Unknown output format')
    if a.preflight:
        print(json.dumps(preflight(cfg), indent=2))
    elif not a.audio:
        p.error('Provide an audio file or --preflight')
    else:
        pipeline(a, cfg)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted. Rerun the same command with --resume.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'Error: {exc}\nNo automatic GPU fallback. For CUDA failures rerun with --device cpu --compute-type int8 (a separate job).', file=sys.stderr)
        sys.exit(1)
