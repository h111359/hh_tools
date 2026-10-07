"""Real file/CLI orchestration tests with recognition replaced by deterministic local data."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transcribe

class PipelineTests(unittest.TestCase):
    def test_resume_protection_and_invalidation(self):
        with tempfile.TemporaryDirectory(prefix='аудио space ') as directory:
            root = Path(directory)
            source = root/'sample.wav'
            with wave.open(str(source), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b'\0\0'*32000)
            cfg = json.loads((transcribe.ROOT/'config/default.json').read_text())
            cfg.update(output_dir=str(root/'out'), mode='draft', language='en')
            args = argparse.Namespace(audio=str(source), speaker_map=None, resume=False, overwrite=False)
            fake_hw = {'model': {'revision':'test'}, 'versions': {'test':'1'}}
            result = {'segments': [], 'speech_regions': []}
            with patch.object(transcribe, 'preflight', return_value=fake_hw), \
                 patch('faster_whisper.WhisperModel'), \
                 patch.object(transcribe, 'recognize', return_value=result) as recognize, \
                 contextlib.redirect_stdout(io.StringIO()):
                transcribe.pipeline(args, cfg)
                self.assertEqual(recognize.call_count, 1)
                with self.assertRaises(FileExistsError):
                    transcribe.pipeline(args, cfg)
                args.resume = True
                transcribe.pipeline(args, cfg)
                self.assertEqual(recognize.call_count, 1)
                cfg['language'] = 'bg'
                transcribe.pipeline(args, cfg)
                self.assertEqual(recognize.call_count, 2)
                jobs = list((root/'out').glob('sample-*'))
                self.assertEqual(len(jobs), 2)
                self.assertTrue(all(json.loads((j/'manifest.json').read_text())['status']=='complete' for j in jobs))
                args.resume = False; args.overwrite = True
                transcribe.pipeline(args, cfg)
                self.assertEqual(len(list((root/'out').glob('*.backup-*'))), 1)

    def test_interruption_resumes_only_missing_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'sample.wav'
            with wave.open(str(source), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b'\0\0'*16000*24)
            cfg = json.loads((transcribe.ROOT/'config/default.json').read_text())
            cfg.update(output_dir=str(root/'out'), mode='draft', chunk_seconds=20)
            args = argparse.Namespace(audio=str(source), speaker_map=None, resume=False, overwrite=False)
            empty = {'segments': [], 'speech_regions': []}
            with patch.object(transcribe, 'preflight', return_value={'model':{}, 'versions':{}}), \
                 patch('faster_whisper.WhisperModel'), \
                 patch.object(transcribe, 'silence_boundaries', return_value=[]), \
                 patch.object(transcribe, 'recognize', side_effect=[empty, KeyboardInterrupt(), empty]) as recognize, \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(KeyboardInterrupt):
                    transcribe.pipeline(args, cfg)
                job = next((root/'out').glob('sample-*'))
                self.assertEqual(json.loads((job/'manifest.json').read_text())['status'], 'interrupted')
                args.resume = True
                transcribe.pipeline(args, cfg)
                self.assertEqual(recognize.call_count, 3)
                self.assertEqual(json.loads((job/'manifest.json').read_text())['status'], 'complete')

if __name__ == '__main__':
    unittest.main()
