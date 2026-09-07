"""A message is a purpose and its variables. The template is configuration."""

import pytest

from modules.integrations import templates
from modules.integrations.errors import IntegrationError, TEMPLATE_NOT_CONFIGURED


def test_a_configured_template_is_found_by_purpose():
    configuration = {"templates": {"authentication_otp": "1707169900000000000"}}
    assert (
        templates.template_for(configuration, "authentication_otp")
        == "1707169900000000000"
    )


def test_a_missing_template_is_refused_before_any_provider_is_called():
    """Discovering a missing template from a vendor's rejection code is a
    worse day than discovering it from our own refusal."""
    with pytest.raises(IntegrationError) as raised:
        templates.template_for({"templates": {}}, "authentication_otp")
    assert raised.value.code == TEMPLATE_NOT_CONFIGURED


def test_a_configuration_with_no_templates_key_at_all_is_refused_the_same_way():
    with pytest.raises(IntegrationError) as raised:
        templates.template_for({}, "authentication_otp")
    assert raised.value.code == TEMPLATE_NOT_CONFIGURED


def test_a_missing_template_is_not_retryable():
    """Nobody should retry a configuration problem; somebody should fix it."""
    with pytest.raises(IntegrationError) as raised:
        templates.template_for({}, "authentication_otp")
    assert raised.value.retryable is False


def test_the_otp_variables_are_positional_and_match_the_registered_wording():
    from modules.auth.otp_message import build_otp_message, otp_variables

    variables = otp_variables("418302")
    assert variables[0] == "418302"
    # Whatever wording is registered, the code and the minutes are what it
    # interpolates, and the rendered text has to contain both.
    rendered = build_otp_message("418302")
    assert "418302" in rendered and variables[1] in rendered
