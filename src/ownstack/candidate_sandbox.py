"""Standalone trusted bootstrap embedded in the candidate driver, before exec.

Linux x86-64/aarch64 only. Deny-all Landlock filesystem rules and an explicit
seccomp syscall allowlist stack with the container's policy. Never invoke in the
API/worker/host process. Missing kernel/library support fails closed.
"""
import ctypes
import errno
import os
import platform
import sys
import encodings.cp1252  # Warm the owned PDF encoder before all file opens stop.

POLICY_ID = 'landlock-seccomp-pdf-v1'
ALLOWED_SYSCALLS = (
    'read', 'write', 'readv', 'writev', 'close', 'fstat', 'lseek',
    'mmap', 'mprotect', 'munmap', 'mremap', 'brk', 'madvise',
    'rt_sigaction', 'rt_sigprocmask', 'rt_sigreturn', 'sigaltstack',
    'futex', 'futex_waitv', 'clock_gettime', 'gettimeofday', 'time',
    'getrandom', 'getpid', 'getppid', 'gettid', 'getuid', 'geteuid',
    'getgid', 'getegid', 'exit', 'exit_group', 'sched_yield', 'restart_syscall',
    'getrusage',
)


def lockdown():
    if sys.platform != 'linux' or platform.machine() not in {'x86_64', 'aarch64'}:
        raise RuntimeError('Required Linux candidate isolation unavailable')
    libc = ctypes.CDLL(None, use_errno=True)
    seccomp = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    class ArgCompare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                    ('mask', ctypes.c_uint64), ('value', ctypes.c_uint64)]
    # These three syscall numbers are shared by the two explicitly supported ABIs.
    abi = libc.syscall(444, 0, 0, 1)  # landlock_create_ruleset VERSION
    if abi < 3:
        raise RuntimeError('Landlock ABI >= 3 required, including truncation control')
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError('Cannot establish no_new_privs')
    fs = (1 << 15) - 1  # ABI 3: execute/read/write/remove/make/refer/truncate.
    if abi >= 5:
        fs |= 1 << 15  # device ioctl control
    attrs = (ctypes.c_uint64 * 3)(fs, 3 if abi >= 4 else 0, 3 if abi >= 6 else 0)
    size = 24 if abi >= 6 else 16 if abi >= 4 else 8
    ruleset = libc.syscall(444, ctypes.byref(attrs), size, 0)
    if ruleset < 0:
        raise RuntimeError('Cannot create deny-all Landlock ruleset')
    try:
        if libc.syscall(446, ruleset, 0) != 0:  # landlock_restrict_self
            raise RuntimeError('Cannot enforce Landlock')
    finally:
        os.close(ruleset)
    # Check real enforcement before stacking seccomp; open() must fail via Landlock.
    ctypes.set_errno(0)
    fd = libc.open(b'/etc/passwd', 0)
    if fd >= 0:
        os.close(fd)
        raise RuntimeError('Landlock filesystem denial self-check failed')
    if ctypes.get_errno() != errno.EACCES:
        raise RuntimeError('Unexpected Landlock denial')
    # Only 0/1/2 are retained. No queue, socket, directory or secret descriptor.
    os.closerange(3, 1024)
    context = seccomp.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError('Cannot create seccomp filter')
    try:
        for name in ALLOWED_SYSCALLS:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            # CPython needs data mappings, not new executable memory.
            comparison = ArgCompare(2, 7, 4, 0) if name in {'mmap', 'mprotect'} else None
            if number >= 0 and seccomp.seccomp_rule_add_array(context, 0x7fff0000, number,
                    1 if comparison else 0, ctypes.byref(comparison) if comparison else None) != 0:
                raise RuntimeError('Cannot define seccomp allowlist')
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError('Cannot enforce seccomp')
    finally:
        seccomp.seccomp_release(context)
    ctypes.set_errno(0)
    descriptor = libc.socket(2, 1, 0)
    if descriptor >= 0:
        os.close(descriptor)
        raise RuntimeError('Seccomp socket denial self-check failed')
    if ctypes.get_errno() != errno.EPERM:
        raise RuntimeError('Unexpected seccomp denial')
    return {'policy': POLICY_ID, 'landlock_abi': abi, 'filesystem': 'deny-all',
            'syscalls': 'allowlist', 'new_privileges': False}
