from threading import Condition, Lock
from time import perf_counter_ns


class GlobalLock:
    def __init__(self):
        self.lock = Lock()

    def acquire(self, role):
        self.lock.acquire()

    def release(self, role):
        self.lock.release()


class RWLock:
    def __init__(self):
        self.condition = Condition(Lock())
        self.readers = 0
        self.writer = False
        self.next_ticket = 0
        self.serving = 0

    def acquire(self, role):
        with self.condition:
            ticket = self.next_ticket
            self.next_ticket += 1
            while ticket != self.serving or self.writer or (role == 'write' and self.readers):
                self.condition.wait()
            if role == 'write':
                self.writer = True
            else:
                self.readers += 1
            self.serving += 1
            self.condition.notify_all()

    def release(self, role):
        with self.condition:
            if role == 'write':
                self.writer = False
            else:
                self.readers -= 1
            self.condition.notify_all()


class Node:
    __slots__ = ('key', 'next')

    def __init__(self, key, next_node=None):
        self.key = key
        self.next = next_node


class OrderedList:
    def __init__(self, mode):
        self.sync = GlobalLock() if mode == 'global' else RWLock()
        self.head = None
        self.count = 0
        for key in reversed(range(0, 1024, 2)):
            self.head = Node(key, self.head)
            self.count += 1

    def _add(self, key):
        previous, current = None, self.head
        while current is not None and current.key < key:
            previous, current = current, current.next
        if current is not None and current.key == key:
            return False
        node = Node(key, current)
        if previous is None:
            self.head = node
        else:
            previous.next = node
        self.count += 1
        return True

    def _remove(self, key):
        previous, current = None, self.head
        while current is not None and current.key < key:
            previous, current = current, current.next
        if current is None or current.key != key:
            return False
        if previous is None:
            self.head = current.next
        else:
            previous.next = current.next
        self.count -= 1
        return True

    def _contains(self, key):
        current = self.head
        while current is not None and current.key < key:
            current = current.next
        return current is not None and current.key == key

    def add(self, key):
        return self.execute('add', key)[3]

    def remove(self, key):
        return self.execute('remove', key)[3]

    def contains(self, key):
        return self.execute('contains', key)[3]

    def size(self):
        self.sync.acquire('read')
        try:
            return self.count
        finally:
            self.sync.release('read')

    def execute(self, operation, key):
        role = 'read' if operation == 'contains' else 'write'
        called = perf_counter_ns()
        self.sync.acquire(role)
        acquired = perf_counter_ns()
        try:
            value = getattr(self, '_' + operation)(key)
        finally:
            self.sync.release(role)
        returned = perf_counter_ns()
        return called, acquired, returned, value

    def validate(self):
        keys, visited = [], set()
        current = self.head
        while current is not None:
            if id(current) in visited:
                raise AssertionError('Cycle')
            visited.add(id(current))
            keys.append(current.key)
            current = current.next
        assert all(0 <= k < 1024 for k in keys)
        assert all(a < b for a, b in zip(keys, keys[1:]))
        assert len(keys) == self.size()
        return keys
