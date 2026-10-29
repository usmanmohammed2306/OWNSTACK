"""Loopback-only PostgreSQL wire fault fixture, never a production proxy.

Unencrypted protocol is accepted solely for disposable local test databases.
Credentials and SQL are relayed, never recorded. No buffered traffic is replayed
after a partition. COMMIT faults distinguish a dropped request from PostgreSQL's
actual COMMIT completion/idle response. Independent DB reads remain the oracle.
"""
import json
import socket
import struct
import threading
import time


def receive(sock, size):
    data = bytearray()
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError
        data.extend(part)
    return bytes(data)


def frame(sock):
    kind = receive(sock, 1)
    header = receive(sock, 4)
    size = struct.unpack('!I', header)[0]
    if not 4 <= size <= 16 * 1024 * 1024:
        raise ValueError('Invalid fixture frame')
    body = receive(sock, size - 4)
    return kind, body, kind + header + body


class PostgresFaultProxy:
    def __init__(self, host, port, journal):
        if host != '127.0.0.1':
            raise ValueError('Network fault target must be loopback')
        self.target = host, port
        self.journal = journal
        self.lock = threading.Lock()
        self.connections = set()
        self.threads = []
        self.events = []
        self.armed = None
        self.partition = threading.Event()
        self.stop = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        self.listener.settimeout(.2)
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def log(self, **fields):
        row = {'at': time.time(), **fields}
        with self.lock:
            self.events.append(row)
            with self.journal.open('a') as file:
                file.write(json.dumps(row) + '\n')

    def arm(self, mode):
        if mode not in {'cut_before_commit', 'cut_after_commit', 'silence_after_commit'}:
            raise ValueError('Unknown fixed fault')
        with self.lock:
            if self.armed:
                raise ValueError('A fault is already armed')
            self.armed = mode

    def accept(self):
        while not self.stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            thread = threading.Thread(target=self.relay, args=(client,), daemon=True)
            self.threads.append(thread)
            thread.start()

    def relay(self, client):
        server = None
        ended = threading.Event()
        state = {'fault': None, 'commit_complete': False, 'silent': False}
        def close_pair():
            ended.set()
            for sock in (client, server):
                if sock:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    sock.close()
        try:
            server = socket.create_connection(self.target, timeout=5)
            server.settimeout(None)
            with self.lock:
                self.connections.add(client)
                self.connections.add(server)
            header = receive(client, 4)
            size = struct.unpack('!I', header)[0]
            if not 8 <= size <= 65536:
                raise ValueError('Invalid fixture startup')
            startup = receive(client, size - 4)
            if struct.unpack('!I', startup[:4])[0] != 196608:
                raise ValueError('Fixture requires sslmode=disable and gssencmode=disable')
            server.sendall(header + startup)

            def upstream():
                try:
                    while not ended.is_set():
                        kind, body, message = frame(client)
                        if self.partition.is_set() or state['silent']:
                            continue
                        if kind == b'Q' and body.rstrip(b'\0').strip().upper() == b'COMMIT':
                            with self.lock:
                                state['fault'] = self.armed
                                self.armed = None
                            if state['fault'] == 'cut_before_commit':
                                self.log(mode=state['fault'], commit_forwarded=False, server_commit_confirmed=False)
                                close_pair()
                                return
                        server.sendall(message)
                except (EOFError, OSError, ValueError):
                    pass
                finally:
                    close_pair()

            thread = threading.Thread(target=upstream, daemon=True)
            self.threads.append(thread)
            thread.start()
            while not ended.is_set():
                kind, body, message = frame(server)
                if self.partition.is_set() or state['silent']:
                    continue
                if state['fault'] in {'cut_after_commit', 'silence_after_commit'}:
                    if kind == b'C':
                        state['commit_complete'] = body == b'COMMIT\0'
                    if kind == b'Z':
                        confirmed = state['commit_complete'] and body == b'I'
                        self.log(mode=state['fault'], commit_forwarded=True,
                                 server_commit_confirmed=confirmed, commit_ack_delivered=False)
                        if not confirmed:
                            raise ValueError('Fault did not observe committed idle state')
                        if state['fault'] == 'cut_after_commit':
                            close_pair()
                            return
                        state['silent'] = True
                    continue
                client.sendall(message)
        except (EOFError, OSError, ValueError):
            pass
        finally:
            close_pair()
            with self.lock:
                self.connections.discard(client)
                self.connections.discard(server)

    def close(self):
        self.stop.set()
        self.listener.close()
        with self.lock:
            sockets = list(self.connections)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self.thread.join(timeout=2)
        for thread in self.threads:
            thread.join(timeout=2)
        if self.thread.is_alive() or any(thread.is_alive() for thread in self.threads):
            raise RuntimeError('Fixture proxy threads did not stop')
