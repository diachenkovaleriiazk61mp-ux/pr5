from array import array
import gzip
import json
import math
from pathlib import Path
import sys


def audit(directory):
    directory = Path(directory)
    total = 0
    runs = list(directory.glob('serial-*.json')) + list(directory.glob('parallel-*.json'))
    assert runs, 'No runs'
    for path in runs:
        info = json.loads(path.read_text(encoding='utf-8'))
        assert info['invariants']
        durations = {'write': [], 'read': []}
        for thread in info['threads']:
            for role in ('write', 'read'):
                count = thread['counts'][role]
                if not count:
                    continue
                file = directory / f'{info["kind"]}-{info["mode"]}-{info["repeat"]}-thread{thread["id"]}-{role}.bin.gz'
                with gzip.open(file, 'rb') as stream:
                    values = array('Q')
                    values.frombytes(stream.read())
                if sys.byteorder != 'little':
                    values.byteswap()
                assert len(values) == count * 4
                for i in range(0, len(values), 4):
                    called, elapsed, waited, held = values[i:i+4]
                    assert elapsed == waited + held
                    assert called + elapsed <= round(info['D'] * 1e9)
                durations[role].extend(values[1::4])
                assert max(values[2::4]) / 1e6 <= info['roles'][role]['wait_max_ms'] + 1e-8
                total += count
        for role, values in durations.items():
            values.sort()
            result = info['roles'][role]
            assert len(values) == result['N']
            for q, field in ((.5, 'p50_us'), (.99, 'p99_us')):
                expected = values[math.ceil(q*len(values))-1] / 1000
                assert expected == result[field]
            assert 0 <= result['w'] <= 1
            assert result['X'] == result['N'] / info['D']
    print(f'Audit OK: {len(runs)} runs, {total} individual measurements')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
    else:
        choices = sorted(p.parent for p in Path('results').glob('*/status.json')
                         if json.loads(p.read_text(encoding='utf-8'))['complete'])
        if not choices:
            raise SystemExit('No completed full run')
        directory = choices[-1]
    audit(directory)
