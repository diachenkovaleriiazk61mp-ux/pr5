import random
from threading import Event, Thread
from structure import OrderedList, RWLock


def main():
    for mode in ('global','rw'):
        obj=OrderedList(mode)
        reference=set(range(0,1024,2))
        rng=random.Random(7)
        for i in range(20000):
            key=rng.randrange(1024)
            op=('add','remove','contains')[i%3]
            expected=key not in reference if op=='add' else key in reference
            assert obj.execute(op,key)[3]==expected
            if op=='add':
                reference.add(key)
            elif op=='remove':
                reference.discard(key)
            if i%500==0:
                assert obj.validate()==sorted(reference)
        assert obj.validate()==sorted(reference)
    lock=RWLock()
    held,release,done=Event(),Event(),Event()
    lock.acquire('read')

    def reader():
        lock.acquire('read')
        held.set()
        assert release.wait(5)
        lock.release('read')

    def writer():
        lock.acquire('write')
        done.set()
        lock.release('write')

    a=Thread(target=reader)
    a.start()
    assert held.wait(5)
    b=Thread(target=writer)
    b.start()
    assert not done.is_set()
    lock.release('read')
    assert not done.is_set()
    release.set()
    a.join(5)
    b.join(5)
    assert done.is_set() and not a.is_alive() and not b.is_alive()
    print('Structure and RWLock checks: OK')


if __name__=='__main__':
    main()
