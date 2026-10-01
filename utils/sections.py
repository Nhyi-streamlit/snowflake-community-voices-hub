"""Scoped early exit for a tab or section. st.stop() halts the whole page, hiding later tabs."""
from contextlib import contextmanager


class SectionDone(Exception):
    pass


@contextmanager
def section(container):
    with container:
        try:
            yield
        except SectionDone:
            pass
