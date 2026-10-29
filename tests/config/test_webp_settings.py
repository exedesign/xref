import pytest

from xref.config import XRefSettings
from xref.widgets.settings import ImageStorageFormatWidget


def test_webp_in_options():
    options = {value[0]: value for value in ImageStorageFormatWidget.OPTIONS}
    assert 'webp' in options
    assert 'png' in options
    assert 'jpg' in options
    assert 'best' in options


def test_webp_valid_setting(settings):
    settings.setValue('Items/image_storage_format', 'webp')
    assert settings.value('Items/image_storage_format') == 'webp'
    assert settings.valueOrDefault('Items/image_storage_format') == 'webp'


def test_invalid_setting_rejected(settings):
    settings.setValue('Items/image_storage_format', 'gif')
    assert settings.valueOrDefault('Items/image_storage_format') == 'best'
