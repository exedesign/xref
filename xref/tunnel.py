#!/usr/bin/env python3

# This file is part of XRef.
#
# XRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# XRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with XRef.  If not, see <https://www.gnu.org/licenses/>.

"""Public tunnel for web sharing via localhost.run (plain SSH, no tools).

The tunnel only carries the tiny HTML/JS page; the live board data keeps
flowing over the WebSocket through the same tunnel. Uses the system's
``ssh`` client with a remote port forward, so nothing has to be installed.
"""

import logging
import re
import subprocess
import threading

logger = logging.getLogger(__name__)

#: Matches the https URL localhost.run prints when the tunnel is up
TUNNEL_URL_RE = re.compile(r'(https://[a-z0-9.-]+\.lhr\.life)')
TUNNEL_HOST = 'nokey@localhost.run'
SETUP_TIMEOUT = 20.0


class SshTunnel:
    """A temporary https tunnel to a local port via localhost.run."""

    def __init__(self, local_port):
        self.local_port = local_port
        self.url = None
        self.process = None
        self._output = []

    def start(self, timeout=SETUP_TIMEOUT):
        """Opens the tunnel. Returns the public https URL or None."""

        try:
            self.process = subprocess.Popen(
                ['ssh', '-R', '80:127.0.0.1:%d' % self.local_port,
                 '-o', 'StrictHostKeyChecking=no',
                 '-o', 'ExitOnForwardFailure=yes',
                 '-o', 'ServerAliveInterval=30',
                 TUNNEL_HOST],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(
                    subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as e:
            logger.info(f'Tunnel: ssh could not be started: {e}')
            return None

        event = threading.Event()

        def read_output():
            for line in self.process.stdout:
                text = line.decode('utf-8', 'replace').strip()
                if text:
                    self._output.append(text)
                    match = TUNNEL_URL_RE.search(text)
                    if match and self.url is None:
                        self.url = match.group(1)
                        event.set()
            event.set()

        threading.Thread(target=read_output, daemon=True).start()
        if not event.wait(timeout):
            logger.info('Tunnel: no URL within timeout')
            self.stop()
            return None
        if not self.url:
            logger.info('Tunnel: ' + ' | '.join(self._output[-3:]))
            self.stop()
            return None
        logger.info(f'Tunnel: {self.url}')
        return self.url

    def stop(self):
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.process.kill()
                except OSError:
                    pass
            self.process = None
        self.url = None
