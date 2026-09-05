"""Bounded cleanup of a worker and detached browser descendant groups."""
from __future__ import annotations

import os
import signal
import subprocess
import time


def _snapshot():
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,pgid='], capture_output=True,
                            text=True, check=True, timeout=2)
    rows = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and all(field.isdigit() for field in fields):
            pid, parent, group = map(int, fields)
            rows[pid] = (parent, group)
    return rows


def owned_processes(rows, root_pid):
    """Find only the requested worker and descendants in one process snapshot."""
    owned = {root_pid}
    while True:
        children = {pid for pid, (parent, _) in rows.items() if parent in owned}
        if children <= owned:
            return {pid: rows[pid] for pid in owned if pid in rows}
        owned.update(children)


def terminate_tree(root_pid, *, grace_seconds=0.2):
    """Stop owned groups before the root dies and detached children are orphaned.

    The caller must have created root_pid as a new session. A process table is
    captured before any signal. Group signals are restricted to groups whose
    leader is in that captured worker tree; the caller's group is never signaled.
    """
    if type(root_pid) is not int or root_pid <= 1 or root_pid == os.getpid():
        raise ValueError('Cleanup requires a different positive worker PID')
    if not 0 <= grace_seconds <= 1:
        raise ValueError('Cleanup grace must be between zero and one second')
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(root_pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return
    caller_group = os.getpgrp()
    try:
        rows = _snapshot()
    except (OSError, subprocess.SubprocessError):
        # Still terminate the worker group, but do not claim detached cleanup
        # succeeded when the ownership snapshot was unavailable.
        if os.getpgid(root_pid) != caller_group:
            os.killpg(root_pid, signal.SIGKILL)
        raise RuntimeError('Worker stopped; descendant process snapshot failed')
    owned = owned_processes(rows, root_pid)
    groups = {group for _, group in owned.values()
              if group in owned and group > 1 and group != caller_group}
    # Detached browser groups are signaled before their parent worker group.
    ordered_groups = sorted(groups - {root_pid}) + ([root_pid] if root_pid in groups else [])

    def send(sig):
        fallback_groups = set()
        for group in ordered_groups:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                # macOS can return EPERM for a group containing only an
                # unreaped child. Revalidate and signal its known PIDs below.
                fallback_groups.add(group)
        for pid, (_, group) in owned.items():
            if (group in groups and group not in fallback_groups) or pid == os.getpid():
                continue
            try:
                # Revalidate group membership before signaling a single PID.
                if os.getpgid(pid) == group:
                    os.kill(pid, sig)
            except ProcessLookupError:
                pass

    send(signal.SIGTERM)
    time.sleep(grace_seconds)
    send(signal.SIGKILL)
