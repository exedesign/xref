import platform
import sys

if (sys.platform == 'win32' and sys.version_info >= (3, 10)
        and platform.machine().lower() in ('amd64', 'x86_64')
        and sys.maxsize > 2**32):
    import f3d
