"""Process-local, byte-bounded caches. Keys must include access and data versions."""
from collections import OrderedDict
from threading import RLock
from time import monotonic
import pickle

class BoundedCache:
    def __init__(self, max_bytes=32*1024*1024, max_entries=128, ttl=300):
        self.max_bytes, self.max_entries, self.ttl = max_bytes, max_entries, ttl
        self.entries = OrderedDict()
        self.size = 0
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            item = self.entries.get(key)
            if item is None:
                return None
            expires, data = item
            if expires <= monotonic():
                self.size -= len(data)
                del self.entries[key]
                return None
            self.entries.move_to_end(key)
        # Only bytes serialized by this process are loaded; never disk/user input.
        return pickle.loads(data)

    def put(self, key, value):
        data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        if len(data) > self.max_bytes:
            return
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous:
                self.size -= len(previous[1])
            self.entries[key] = (monotonic()+self.ttl, data)
            self.size += len(data)
            while self.size > self.max_bytes or len(self.entries) > self.max_entries:
                _, (_, removed) = self.entries.popitem(last=False)
                self.size -= len(removed)

sheet_cache = BoundedCache(max_entries=16, ttl=120)
lexical_cache = BoundedCache(max_entries=16, ttl=300)
query_vector_cache = BoundedCache(max_bytes=8*1024*1024, max_entries=256, ttl=300)
verification_cache = BoundedCache(max_bytes=8*1024*1024, max_entries=2048, ttl=120)
plan_cache = BoundedCache(max_bytes=2*1024*1024, max_entries=256, ttl=120)
