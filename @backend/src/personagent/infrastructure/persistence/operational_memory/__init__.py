"""Operational memory persistence package.

Each module in this package exposes a single collaborator class
extracted from the original ``OperationalMemoryRepository`` god file
(``infrastructure/persistence/operational_memory_repository.py``).

These are NOT private helpers — tests and future use cases may import
directly from the modules in this package.
"""
