import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcription.core import atomic, chunks, export, key, owned_words, timestamp

class CoreTests(unittest.TestCase):
    def test_partition_and_maximum(self):
        plan = chunks(301, [108, 219], 120, 2, 15)
        self.assertEqual(plan[0]['core_end'], 108)
        self.assertEqual(plan[-1]['core_end'], 301)
        for left, right in zip(plan, plan[1:]):
            self.assertEqual(left['core_end'], right['core_start'])
        self.assertTrue(all(c['end']-c['start'] <= 120 for c in plan))

    def test_overlap_and_genuine_repetition(self):
        words = [{'start': x, 'end': x+.3, 'word': ' yes'} for x in [8, 9, 10, 11]]
        a = {'core_start': 0, 'core_end': 10}
        b = {'core_start': 10, 'core_end': 20}
        merged = owned_words(words, a) + owned_words(words, b)
        self.assertEqual(merged, words)
        self.assertEqual(len(merged), 4)

    def test_timestamp_carry(self):
        self.assertEqual(timestamp(59.9996, True), '00:01:00,000')
        self.assertEqual(timestamp(3600), '01:00:00.000')

    def test_invalidation(self):
        baseline = {'input': 'abc', 'revision': 'v1', 'mode': 'draft'}
        for field in baseline:
            self.assertNotEqual(key(baseline), key(dict(baseline, **{field: 'changed'})))
        self.assertEqual(key(baseline), key(dict(reversed(list(baseline.items())))))

    def test_atomic_unicode_and_outputs(self):
        with tempfile.TemporaryDirectory(prefix='тест space ') as directory:
            p = Path(directory)
            atomic(p/'chunk.json', {'done': True})
            self.assertEqual(json.loads((p/'chunk.json').read_text()), {'done': True})
            (p/'chunk.json.tmp').write_text('partial')
            self.assertTrue(json.loads((p/'chunk.json').read_text())['done'])
            segment = dict(start=0, end=1.5, text='No, no, 12.', speaker='Speaker unknown', flags=['verify_number'])
            export(p, [segment], [segment], {'formats': ['md','txt','json','srt']}, {})
            self.assertIn('No, no, 12.', (p/'faithful.md').read_text())
            self.assertIn('00:00:00,000 --> 00:00:01,500', (p/'transcript.srt').read_text())
            self.assertEqual(json.loads((p/'transcript.json').read_text())['segments'], [segment])

    def test_empty_and_invalid(self):
        for duration in [0, -1]:
            with self.assertRaises(ValueError):
                chunks(duration, [], 120, 2, 15)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            export(p, [], [], {'formats':['md','txt','json','srt']}, {})
            self.assertEqual((p/'transcript.srt').read_text(), '')
            self.assertEqual(json.loads((p/'transcript.json').read_text())['segments'], [])

if __name__ == '__main__':
    unittest.main()
