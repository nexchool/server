"""A misspelled FLASK_ENV must not quietly hand you the development config.

`get_config` ended in `config_map.get(env, DevelopmentConfig)`, so anything the
map did not recognise — `prod`, `Production`, a stray space, a variable that
failed to load — selected development. That is not one setting going wrong; on
a production box it is five at once, because `ProductionConfig.init_app` never
runs to object:

  * `SECRET_KEY` stays `dev-secret-key-change-in-production`, and
    `JWT_SECRET_KEY` inherits it — every token signed with a public literal
  * CORS becomes `['*']` **with credentials**, which flask-cors serves by
    echoing the caller's origin back
  * `DEBUG` is on
  * GraphQL introspection and the IDE are on
  * the session cookie loses `Secure`

None of that raises, logs, or looks different until someone goes looking.

So: a value that is recognised is honoured, a value that is merely differently
spelled is normalised, and a value nobody recognises stops the app instead of
guessing at it.
"""

from __future__ import annotations

import pytest

from config import (
    DevelopmentConfig,
    ProductionConfig,
    StagingConfig,
    get_config,
)


@pytest.mark.parametrize(
    "env, expected",
    [
        ("development", DevelopmentConfig),
        ("production", ProductionConfig),
        ("staging", StagingConfig),
        ("testing", DevelopmentConfig),
    ],
)
def test_a_known_environment_selects_its_config(env, expected):
    assert get_config(env) is expected


@pytest.mark.parametrize("env", ["Production", "PRODUCTION", "  production  "])
def test_capitalisation_and_whitespace_are_not_typos(env):
    """Someone writing `Production` meant production, and would have got dev."""
    assert get_config(env) is ProductionConfig


@pytest.mark.parametrize("env", ["prod", "prd", "producton", "live", "dev "])
def test_an_unrecognised_environment_refuses_to_guess(env):
    """The failure this exists to prevent: `FLASK_ENV=prod` running dev config."""
    with pytest.raises(ValueError) as raised:
        get_config(env)

    message = str(raised.value)
    assert env.strip() in message, "the message should name what was given"
    assert "production" in message, "and list what is valid"


def test_it_never_silently_returns_development_for_an_unknown_value():
    """Stated as its own property, because it is the whole point."""
    for env in ("prod", "PROD", "producton", "staging-2", "?"):
        with pytest.raises(ValueError):
            get_config(env)


def test_a_bad_value_from_the_environment_is_named_in_the_error(monkeypatch):
    """Read from FLASK_ENV, the refusal used to report `None` — useless at 2am."""
    monkeypatch.setenv("FLASK_ENV", "prod")

    with pytest.raises(ValueError) as raised:
        get_config()

    assert "'prod'" in str(raised.value)


def test_an_unset_environment_still_defaults_to_development(monkeypatch):
    """Locally this is normal, so it must keep working."""
    monkeypatch.delenv("FLASK_ENV", raising=False)

    assert get_config() is DevelopmentConfig


def test_an_empty_environment_variable_is_treated_as_unset(monkeypatch):
    """`FLASK_ENV=` in a compose file is absence, not a typo."""
    monkeypatch.setenv("FLASK_ENV", "")

    assert get_config() is DevelopmentConfig


@pytest.mark.parametrize("env", ["production", "Production", "  PRODUCTION "])
def test_every_reader_of_flask_env_agrees(monkeypatch, env):
    """Three places read FLASK_ENV, and they must not disagree about it.

    `get_config` selects the config class, `is_production()` decides whether to
    use production-style URLs, and `S3_ENV_PREFIX` decides whether uploads land
    under `prod/` or `local/`. Each normalised differently — one lowercased,
    one did not, one neither — so a differently-spelled value could select the
    production config while writing files to the local prefix and generating
    development URLs. Normalising in one place is what stops that.
    """
    from config.settings import current_environment, is_production

    monkeypatch.setenv("FLASK_ENV", env)

    assert current_environment() == "production"
    assert is_production() is True
    assert get_config() is ProductionConfig


def test_a_development_environment_is_not_mistaken_for_production(monkeypatch):
    from config.settings import is_production

    monkeypatch.setenv("FLASK_ENV", "development")

    assert is_production() is False
    assert get_config() is DevelopmentConfig


def test_production_still_refuses_to_boot_on_the_development_secret():
    """The guard that only ever runs once production is actually selected.

    This is why the silent fallback mattered: a misspelled FLASK_ENV meant
    `init_app` never ran, so nothing checked the key at all.
    """
    class _Unchanged(ProductionConfig):
        SECRET_KEY = "dev-secret-key-change-in-production"
        BACKEND_URL = "https://api.example.test"

    with pytest.raises(ValueError, match="SECRET_KEY"):
        _Unchanged.init_app(app=None)
