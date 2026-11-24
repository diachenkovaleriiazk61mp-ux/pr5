import argparse
from array import array
from datetime import datetime, timezone
import gzip
import json
import math
import os
from pathlib import Path
import platform
import random
from statistics import mean, pstdev
import struct
import sys
from threading import Barrier, Thread
from time import perf_counter_ns
import traceback
from structure import OrderedList

PATTERN = ('write', 'read', 'write', 'read', 'write', 'read', 'write', 'read', 'write')


def quantile(values, q):
    return values[max(0, math.ceil(q * len(values)) - 1)] if values else None


def run(mode, kind, repeat, duration, warmup, directory):
    data = OrderedList(mode)
    slots = [None] * (9 if kind == 'parallel' else 1)
    errors = [None] * len(slots)
    window = {}
    nanos = int(duration * 1e9)

    def begin():
        window['warm_start'] = perf_counter_ns()
        window['start'] = window['warm_start'] + int(warmup * 1e9)
        window['end'] = window['start'] + nanos

    barrier = Barrier(len(slots), action=begin)

    def worker(index):
        rng = random.Random(700000 + repeat * 100 + index)
        records = {'write': array('Q'), 'read': array('Q')}
        waits = {'write': 0, 'read': 0}
        boundary = {'write': 0, 'read': 0}
        max_wait = {'write': 0, 'read': 0}
        delta = 0
        writes = 0
        calls = 0
        operations = {'add': 0, 'remove': 0, 'contains': 0}
        try:
            barrier.wait(timeout=30)
            start, end = window['start'], window['end']
            while perf_counter_ns() < end:
                role = PATTERN[calls % 9] if kind != 'parallel' else ('write' if index % 2 == 0 else 'read')
                key = rng.randrange(1024)
                if role == 'write':
                    operation = 'add' if writes % 2 == 0 else 'remove'
                    writes += 1
                else:
                    operation = 'contains'
                called, acquired, returned, value = data.execute(operation, key)
                if operation == 'add' and value:
                    delta += 1
                elif operation == 'remove' and value:
                    delta -= 1
                overlap = max(0, min(acquired, end) - max(called, start))
                waits[role] += overlap
                max_wait[role] = max(max_wait[role], overlap)
                if called >= start and returned <= end:
                    records[role].extend((called - start, returned - called,
                                          acquired - called, returned - acquired))
                    operations[operation] += 1
                elif called < end and returned > start:
                    boundary[role] += 1
                calls += 1
            slots[index] = dict(records=records, wait_ns=waits, delta=delta,
                                boundary=boundary, operations=operations, max_wait=max_wait)
        except BaseException:
            errors[index] = traceback.format_exc()
            barrier.abort()

    threads = [Thread(target=worker, args=(i,)) for i in range(len(slots))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if any(errors):
        raise RuntimeError('\n'.join(e for e in errors if e))
    keys = data.validate()
    assert len(keys) == 512 + sum(s['delta'] for s in slots)
    before = tuple(keys)
    assert all(data.contains(k) == (k in set(before)) for k in range(1024))
    assert tuple(data.validate()) == before
    result = dict(mode=mode, kind=kind, repeat=repeat, D=duration, warmup=warmup,
                  start_utc=datetime.now(timezone.utc).isoformat(),
                  invariants=True, final_size=len(keys), threads=[], roles={},
                  raw_format='gzip; little-endian uint64 rows: call_offset_ns,duration_ns,wait_ns,hold_ns')
    for i, slot in enumerate(slots):
        counts = {r: len(slot['records'][r]) // 4 for r in ('write', 'read')}
        result['threads'].append(dict(id=i + 1, role='mixed' if kind != 'parallel' else ('write' if i % 2 == 0 else 'read'),
                                      counts=counts, operations=slot['operations'], boundary=slot['boundary']))
        for role, values in slot['records'].items():
            if not values:
                continue
            filename = f'{kind}-{mode}-{repeat}-thread{i + 1}-{role}.bin.gz'
            with gzip.open(directory / filename, 'wb', compresslevel=1) as stream:
                if sys.byteorder != 'little':
                    values.byteswap()
                    values.tofile(stream)
                    values.byteswap()
                else:
                    values.tofile(stream)
    for role in ('write', 'read'):
        durations, lock_waits, holds = [], [], []
        for s in slots:
            values = s['records'][role]
            durations.extend(values[1::4])
            lock_waits.extend(values[2::4])
            holds.extend(values[3::4])
        durations.sort()
        counts = [t['counts'][role] for t in result['threads'] if t['role'] in (role, 'mixed')]
        total = len(durations)
        if not total:
            raise RuntimeError(f'No completed operations: {role}')
        p50, p99 = quantile(durations, .5) / 1000, quantile(durations, .99) / 1000
        concurrency = (5 if role == 'write' else 4) if kind == 'parallel' else 1
        result['roles'][role] = dict(N=total, X=total / duration,
            x=total / duration / concurrency, p50_us=p50, p99_us=p99,
            h=p99 / p50, wait_max_ms=max(s['max_wait'][role] for s in slots) / 1e6,
            w=sum(s['wait_ns'][role] for s in slots) / (concurrency * nanos),
            cv=pstdev(counts) / mean(counts), t_cs_us=mean(holds) / 1000)
    total = sum(r['N'] for r in result['roles'].values())
    result['X'] = total / duration
    for role in result['roles'].values():
        role['phi'] = role['N'] / total
    path = directory / f'{kind}-{mode}-{repeat}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{kind} {mode} #{repeat}: X={result["X"]:.2f}; invariants=OK', flush=True)
    print('Thread counts:', [(t['id'], t['counts']) for t in result['threads']], flush=True)
    print(json.dumps(result['roles'], indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('all', 'global', 'rw'), default='all')
    parser.add_argument('--kind', choices=('all', 'parallel', 'serial'), default='all')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    tag = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory = Path('smoke-results' if args.smoke else 'results') / tag
    directory.mkdir(parents=True)
    duration, warmup = (.3, .1) if args.smoke else (10, 1)
    metadata = dict(variant=7, structure='C7', n=9, n_w=5, n_r=4, keyspace=1024,
                    initial_size=512, logical_cpus=os.cpu_count(), python=sys.version,
                    implementation=platform.python_implementation(), platform=platform.platform(),
                    processor=platform.processor(), switch_interval=sys.getswitchinterval(),
                    gil_enabled=getattr(sys, '_is_gil_enabled', lambda: True)(),
                    D=duration, warmup=warmup, repeats=1 if args.smoke else 3, smoke=args.smoke)
    (directory / 'machine.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    modes = ('global', 'rw') if args.mode == 'all' else (args.mode,)
    kinds = ('serial', 'parallel') if args.kind == 'all' else (args.kind,)
    for repeat in range(1, metadata['repeats'] + 1):
        for kind in kinds:
            for mode in (modes if repeat % 2 else modes[::-1]):
                run(mode, kind, repeat, duration, warmup, directory)
    complete = args.mode == 'all' and args.kind == 'all'
    (directory / 'status.json').write_text(json.dumps(dict(complete=complete, smoke=args.smoke)), encoding='utf-8')
    if complete:
        from report import build
        build(directory)
    print(f'Saved: {directory.resolve()}', flush=True)


if __name__ == '__main__':
    main()
