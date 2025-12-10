# backend/__init__.py
"""
Backend-Package: enthält Konfiguration, Datenmodell, Worker, Devices und Orchestrator.
"""

from .backend import Backend  # Backend-Klasse aus backend/backend.py re-exportieren

__all__ = ["Backend"]
