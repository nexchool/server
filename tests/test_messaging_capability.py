"""The capability layer, once there is more than one channel in it."""

from modules.integrations import capabilities
from modules.integrations.base import SmsProvider, WhatsAppProvider
from modules.integrations.registry import registry


def test_whatsapp_is_a_capability_this_build_has():
    assert capabilities.CAPABILITY_WHATSAPP in capabilities.CAPABILITIES
    assert capabilities.CAPABILITY_LABELS[capabilities.CAPABILITY_WHATSAPP]


def test_the_two_channels_are_grouped_as_messaging():
    assert set(capabilities.MESSAGING_CAPABILITIES) == {
        capabilities.CAPABILITY_SMS,
        capabilities.CAPABILITY_WHATSAPP,
    }


def test_a_whatsapp_provider_declares_its_capability_without_being_told():
    assert WhatsAppProvider.capability == capabilities.CAPABILITY_WHATSAPP
    assert SmsProvider.capability == capabilities.CAPABILITY_SMS


def test_the_two_send_signatures_differ_because_the_channels_do():
    """WhatsApp never receives a body. Collapsing these into one `message`
    parameter would hide that, and the hiding is where the bug would live."""
    import inspect

    sms = set(inspect.signature(SmsProvider.send).parameters)
    whatsapp = set(inspect.signature(WhatsAppProvider.send).parameters)
    assert "body" in sms and "body" not in whatsapp
    assert "variables" in whatsapp and "variables" not in sms


def test_the_registry_still_validates_with_a_second_capability():
    registry.validate()
