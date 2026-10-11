"""Pytest plugin that prevents provider, credential, and network calls in offline CI."""

import socket
import subprocess

import pytest

_patch = pytest.MonkeyPatch()


def _blocked(*args, **kwargs):
    pytest.fail("Offline tests cannot use network connections or subprocesses.")


def pytest_sessionstart(session):
    # Apply before collection as well as test execution: imports must be offline too.
    for name in ("connect", "connect_ex"):
        _patch.setattr(socket.socket, name, _blocked)
    _patch.setattr(socket, "create_connection", _blocked)
    _patch.setattr(socket, "getaddrinfo", _blocked)
    _patch.setattr(subprocess, "Popen", _blocked)


def pytest_sessionfinish(session, exitstatus):
    _patch.undo()
