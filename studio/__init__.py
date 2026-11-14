"""Autology Studio (interim shell): a separate application that talks to the Autology platform over HTTP only.

It never imports the ``autology`` package (the engine): it sees the platform exactly as any other client does.
The technology of the final Studio is an open owner decision (D9); this shell is deliberately small, written with
the standard library and plain JavaScript, so it can be replaced without touching the engine.
"""

__version__ = "0.1.0"
