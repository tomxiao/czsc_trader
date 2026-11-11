"""Physical-core selection and worker affinity for V4 research replay."""

import os
from pathlib import Path
import sys

from strategy_runtime.resources import ExecutionResources


def _select_slots(allowed, sibling_groups):
    remaining = set(allowed)
    slots = []
    for group in sibling_groups:
        eligible = allowed.intersection(group)
        if eligible:
            if not eligible <= remaining:
                raise RuntimeError("physical CPU topology contains overlapping cores")
            slots.append(min(eligible))
            remaining.difference_update(eligible)
    if not slots or remaining:
        raise RuntimeError("physical CPU topology does not cover the process affinity mask")
    return tuple(sorted(slots))


def _cpu_ids(mask):
    return frozenset(cpu for cpu in range(mask.bit_length()) if mask & (1 << cpu))


def _windows_api():
    import ctypes as ct
    from ctypes import wintypes as wt

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.GetActiveProcessorGroupCount.argtypes = []
    kernel.GetActiveProcessorGroupCount.restype = wt.WORD
    if ct.sizeof(ct.c_size_t) != 8 or kernel.GetActiveProcessorGroupCount() != 1:
        raise RuntimeError("replay affinity requires 64-bit Windows with one processor group")
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.GetProcessAffinityMask.argtypes = [wt.HANDLE, ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_size_t)]
    kernel.GetProcessAffinityMask.restype = wt.BOOL
    kernel.SetProcessAffinityMask.argtypes = [wt.HANDLE, ct.c_size_t]
    kernel.SetProcessAffinityMask.restype = wt.BOOL
    return kernel


def _windows_allowed(kernel):
    import ctypes as ct

    process_mask = ct.c_size_t()
    system_mask = ct.c_size_t()
    if not kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), ct.byref(process_mask), ct.byref(system_mask)):
        raise ct.WinError(ct.get_last_error())
    return _cpu_ids(process_mask.value)


def _windows_cores(kernel):
    import ctypes as ct
    from ctypes import wintypes as wt
    from struct import unpack_from

    query = kernel.GetLogicalProcessorInformationEx
    query.argtypes = [ct.c_int, ct.c_void_p, ct.POINTER(wt.DWORD)]
    query.restype = wt.BOOL
    processor_core = 0
    size = wt.DWORD()
    if query(processor_core, None, ct.byref(size)) or ct.get_last_error() != 122 or not size.value:
        raise RuntimeError("cannot size the Windows processor topology buffer")
    buffer = ct.create_string_buffer(size.value)
    if not query(processor_core, buffer, ct.byref(size)):
        raise ct.WinError(ct.get_last_error())

    offset = 0
    while offset < size.value:
        # SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX and PROCESSOR_RELATIONSHIP on Win64.
        if size.value - offset < 48:
            raise RuntimeError("truncated Windows processor topology record")
        relationship, length = unpack_from("<II", buffer, offset)
        if relationship != processor_core or not 48 <= length <= size.value - offset:
            raise RuntimeError("invalid Windows processor topology record")
        group_count, = unpack_from("<H", buffer, offset + 30)
        mask, group = unpack_from("<QH", buffer, offset + 32)
        if group_count != 1 or group != 0 or not mask:
            raise RuntimeError("invalid Windows physical-core mask")
        yield _cpu_ids(mask)
        offset += length


def _linux_cores(allowed):
    topology = Path("/sys/devices/system/cpu")
    seen = set()
    for cpu in sorted(allowed):
        if cpu in seen:
            continue
        value = (topology / f"cpu{cpu}" / "topology/thread_siblings_list").read_text().strip()
        siblings = set()
        for entry in value.split(","):
            start, _, end = entry.partition("-")
            siblings.update(range(int(start), int(end or start) + 1))
        if cpu not in siblings:
            raise RuntimeError(f"Linux physical-core topology is missing CPU {cpu}")
        seen.update(siblings)
        yield siblings


def replay_resources(requested: ExecutionResources | None) -> tuple[ExecutionResources, tuple[int, ...]]:
    if requested is not None:
        if type(requested) is not ExecutionResources:
            raise TypeError("evaluation requires ExecutionResources")
        if requested.native_threads_per_worker != 1:
            raise ValueError("V4 replay requires one native thread per worker")
        if requested.max_workers == 1:
            return requested, ()

    try:
        if sys.platform == "win32":
            kernel = _windows_api()
            slots = _select_slots(_windows_allowed(kernel), _windows_cores(kernel))
        elif sys.platform == "linux":
            allowed = os.sched_getaffinity(0)
            slots = _select_slots(allowed, _linux_cores(allowed))
        else:
            raise RuntimeError(f"unsupported platform {sys.platform}")
    except (OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"cannot resolve V4 replay physical cores: {exc}") from exc

    if requested is not None:
        slots = slots[:requested.max_workers]
    if sys.platform == "win32" and len(slots) > 61:
        raise RuntimeError("V4 replay exceeds the Windows process pool limit of 61 workers")
    return ExecutionResources(len(slots), 1, requested.random_seed if requested is not None else 0), slots


def bind_worker(cpu: int):
    if sys.platform == "win32":
        import ctypes as ct

        kernel = _windows_api()
        if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1 << cpu):
            raise ct.WinError(ct.get_last_error())
        if _windows_allowed(kernel) != {cpu}:
            raise RuntimeError("Windows did not apply the requested process affinity")
    elif sys.platform == "linux":
        # Linux affinity is per thread. Pin the leader before its children and
        # cover any native threads already created during spawn imports.
        os.sched_setaffinity(0, {cpu})
        if os.sched_getaffinity(0) != {cpu}:
            raise RuntimeError("Linux did not apply the requested worker affinity")
        for entry in Path("/proc/self/task").iterdir():
            tid = int(entry.name)
            if tid == os.getpid():
                continue
            try:
                os.sched_setaffinity(tid, {cpu})
                if os.sched_getaffinity(tid) != {cpu}:
                    raise RuntimeError(f"Linux did not apply affinity for thread {tid}")
            except ProcessLookupError:
                # The thread exited while the task directory was being read.
                continue
    else:
        raise RuntimeError(f"unsupported platform {sys.platform}")
