"""Notification templates come out of the database, so they are not trusted.

`notification_templates` rows are written and previewed by platform admins
(`POST /api/platform/notification-templates/preview`). They were rendered by a
plain `jinja2.Environment`, which reaches Python attributes from inside a
template — so a template body was an arbitrary-code-execution oracle on the
box that holds every school's data. One compromised staff session became RCE.

The function's own docstring claimed "no arbitrary code execution" while the
class it returned allowed exactly that, which is why this asserts the
behaviour rather than the class name.
"""

from __future__ import annotations

import pytest

# The classic Jinja sandbox escape: walk from a literal up to `subprocess` via
# class internals. A sandbox refuses the attribute access; a plain Environment
# happily walks it.
ESCAPE = "{{ ''.__class__.__mro__[1].__subclasses__() }}"


def _render(body: str, **context) -> str:
    from modules.notifications.template_service import _safe_jinja_env

    return _safe_jinja_env().from_string(body).render(**context)


def test_a_template_cannot_reach_python_internals():
    from jinja2.exceptions import SecurityError

    with pytest.raises(SecurityError):
        _render(ESCAPE)


def test_an_objects_internals_do_not_leak_into_the_output():
    """A bare unsafe attribute yields Jinja's unsafe-undefined, not the value.

    The sandbox does not raise until that undefined is *used* (the chained
    escape above), so what matters here is that nothing about the object
    reaches the rendered text.
    """
    class Person:
        full_name = "Riya Patel"

    rendered = _render("[{{ person.__class__ }}]", person=Person())

    assert rendered == "[]"
    assert "Person" not in rendered


def test_ordinary_substitution_still_works():
    """The sandbox must not break what templates are actually for."""
    rendered = _render(
        "Dear {{ guardian }}, {{ child }} was absent on {{ day }}.",
        guardian="Mr Patel", child="Riya", day="12 August",
    )

    assert rendered == "Dear Mr Patel, Riya was absent on 12 August."


def test_a_callables_globals_cannot_be_walked():
    """`__globals__` is the usual route from any function to the interpreter."""
    from jinja2.exceptions import SecurityError

    with pytest.raises(SecurityError):
        _render("{{ render.__globals__['__builtins__'] }}", render=_render)
