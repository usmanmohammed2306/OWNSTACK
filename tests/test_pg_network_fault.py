"""Protocol fixture parsing controls use byte streams, never live databases."""
import importlib.util
from pathlib import Path
import struct

import pytest

spec = importlib.util.spec_from_file_location('pg_network_fault', Path(__file__).parents[1] / 'scripts/pg_network_fault.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class Fragmented:
    def __init__(self, data):
        self.data = data

    def recv(self, size):
        part, self.data = self.data[:min(size, 1)], self.data[min(size, 1):]
        return part


def test_fragmented_frame_reassembles_without_changing_bytes():
    message = b'C' + struct.pack('!I', 11) + b'COMMIT\0'
    assert proxy.frame(Fragmented(message)) == (b'C', b'COMMIT\0', message)


@pytest.mark.parametrize('data', [b'', b'Q', b'Q\0\0', b'Q\0\0\0\x0aab'])
def test_truncated_stream_is_not_a_committed_response(data):
    with pytest.raises(EOFError):
        proxy.frame(Fragmented(data))


@pytest.mark.parametrize('length', [0, 3, 16 * 1024 * 1024 + 1, 2**32 - 1])
def test_oversized_or_invalid_frame_rejected(length):
    with pytest.raises(ValueError):
        proxy.frame(Fragmented(b'Q' + struct.pack('!I', length)))


def test_proxy_refuses_non_loopback_target(tmp_path):
    with pytest.raises(ValueError, match='loopback'):
        proxy.PostgresFaultProxy('example.com', 5432, tmp_path / 'unused.jsonl')
