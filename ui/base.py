"""UI backend interface.

Each platform backend implements run() and renders core.UsageMonitor
state (title + menu model) with its native toolkit:

- ui/macos.py   -> rumps (menu bar app)
- ui/linux.py   -> AyatanaAppIndicator + PyGObject
- ui/windows.py -> pystray + tkinter flyout
"""


class TrayBackend:
    """Minimal contract for a platform tray backend."""

    def run(self):
        """Start the event loop; blocks until quit."""
        raise NotImplementedError
