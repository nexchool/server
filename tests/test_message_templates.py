"""A message is a purpose and its variables. The template is configuration."""

import pytest

from modules.integrations import templates
from modules.integrations.errors import IntegrationError, TEMPLATE_NOT_CONFIGURED
from modules.integrations.templates import MessageTemplate


def test_a_bare_string_template_still_resolves_with_no_named_variables():
    """Every existing row and test fixture holds a bare string — a school
    registered on a vendor that takes free text plus a DLT stamp, nothing
    more. Breaking that would be a migration nobody asked for."""
    configuration = {"templates": {"authentication_otp": "1707169900000000000"}}
    template = templates.template_for(configuration, "authentication_otp")
    assert template == MessageTemplate(id="1707169900000000000", variables=())


def test_an_object_template_yields_its_id_and_its_variable_names():
    """MSG91's Flow API matches a template's placeholders by name, not
    position — Task 8b. A school on that vendor registers both."""
    configuration = {
        "templates": {
            "authentication_otp": {"id": "flow_x", "variables": ["OTP", "MINUTES"]},
        }
    }
    template = templates.template_for(configuration, "authentication_otp")
    assert template.id == "flow_x"
    assert template.variables == ("OTP", "MINUTES")


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


def test_an_object_template_with_no_id_is_refused_the_same_way():
    """`{"variables": [...]}` with no `id` is not a template anybody
    registered — it is a config typo, and it should read like one."""
    with pytest.raises(IntegrationError) as raised:
        templates.template_for(
            {"templates": {"authentication_otp": {"variables": ["OTP"]}}},
            "authentication_otp",
        )
    assert raised.value.code == TEMPLATE_NOT_CONFIGURED


def test_the_otp_variables_are_positional_and_match_the_registered_wording():
    from modules.auth.otp_message import build_otp_message, otp_variables

    variables = otp_variables("418302")
    assert variables[0] == "418302"
    # Whatever wording is registered, the code and the minutes are what it
    # interpolates, and the rendered text has to contain both.
    rendered = build_otp_message("418302")
    assert "418302" in rendered and variables[1] in rendered
