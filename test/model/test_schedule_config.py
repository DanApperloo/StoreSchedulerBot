import pytest

from model.schedule_config import ScheduleConfig
from util.exception import SingletonNotExist, SingletonExist, ConfigError
from test.path import get_resource_path
from test.fixture import destroy_scheduleconfig


def test_scheduleconfig_singleton(destroy_scheduleconfig):
    test_config = get_resource_path('valid.schedule')

    # Detect uninitialized Singleton
    with pytest.raises(SingletonNotExist):
        ScheduleConfig.singleton()

    # Set an invalid existing Singleton
    ScheduleConfig.instance = 'deadbeef'
    with pytest.raises(SingletonNotExist):
        ScheduleConfig.singleton()
    del ScheduleConfig.instance

    # Ensure init fails if Singleton already exists
    _ = ScheduleConfig(config_file=test_config)
    with pytest.raises(SingletonExist):
        _ = ScheduleConfig(config_file=test_config)
    del ScheduleConfig.instance

    # Ensure we can get the Singleton instance
    a = ScheduleConfig(config_file=test_config)
    assert a.initialized
    assert ScheduleConfig.singleton() is a

    # Ensure we can't create a new one
    with pytest.raises(SingletonExist):
        _ = ScheduleConfig(config_file=test_config)
    del ScheduleConfig.instance

    # Test Invalid Config - No Days
    test_config = get_resource_path('no_days.schedule')
    with pytest.raises(ConfigError):
        a = ScheduleConfig(config_file=test_config)
    del ScheduleConfig.instance

    # Test Valid Config
    test_config = get_resource_path('valid.schedule')
    a = ScheduleConfig(config_file=test_config)
    assert len(a.day_configs) == 7
    assert a.nightly_config.enabled
    assert a.weekly_config.enabled
    del ScheduleConfig.instance

    # Test Valid Config - No Nightly
    test_config = get_resource_path('no_nightly.schedule')
    a = ScheduleConfig(config_file=test_config)
    assert len(a.day_configs) == 7
    assert not a.nightly_config.enabled
    assert a.weekly_config.enabled
    del ScheduleConfig.instance

    # Test Valid Config - No Weekly
    test_config = get_resource_path('no_weekly.schedule')
    a = ScheduleConfig(config_file=test_config)
    assert len(a.day_configs) == 7
    assert a.nightly_config.enabled
    assert not a.weekly_config.enabled
    del ScheduleConfig.instance
