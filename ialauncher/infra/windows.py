"""Windows host (WSL interop): keep the machine awake while a model is loaded."""
import os
import shutil
import subprocess

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED until stdin closes (the screen may still turn off)
_NO_SLEEP = r'''Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[void][W.P]::SetThreadExecutionState([uint32]"0x80000001")
[void][Console]::In.ReadLine()'''


class KeepAwake:
    """No-op outside WSL or with interop disabled."""

    def __init__(self):
        # systemd services have no Windows PATH
        path = os.environ.get("PATH", "") + ":/mnt/c/Windows/System32/WindowsPowerShell/v1.0"
        self.powershell = shutil.which("powershell.exe", path=path)
        self.proc = None

    def set(self, on):
        if not self.powershell or on == (self.proc is not None and self.proc.poll() is None):
            return
        if on:  # released when the process ends, including when the launcher dies (stdin closes)
            self.proc = subprocess.Popen([self.powershell, "-NoProfile", "-NonInteractive", "-Command", _NO_SLEEP],
                                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.proc.stdin.close()  # EOF -> PowerShell exits and Windows may sleep again
            self.proc = None
