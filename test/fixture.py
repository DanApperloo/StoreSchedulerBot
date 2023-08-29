import os
import pytest

from test.path import *

from util.date import DateTranslator, DEFAULT_DATE_FORMAT
from util.exception import SingletonNotExist
from model.schedule_config import ScheduleConfig


@pytest.fixture(scope="function")
def destroy_scheduleconfig(request):
    def remove_scheduleconfig_storage():
        ScheduleConfig.instance = None
        del ScheduleConfig.instance

    request.addfinalizer(remove_scheduleconfig_storage)


@pytest.fixture(scope="function")
def default_scheduleconfig():
    default_config = get_resource_path('valid.schedule')

    try:
        _ = ScheduleConfig.singleton()
        del ScheduleConfig.instance  # noqa
    except SingletonNotExist:
        pass
    finally:
        return ScheduleConfig(config_file=default_config)


@pytest.fixture(scope="function")
def destroy_datetranslator(request):
    def remove_datetranslator_storage():
        DateTranslator.instance = None
        del DateTranslator.instance

    request.addfinalizer(remove_datetranslator_storage)


@pytest.fixture(scope="function")
def default_datetranslator():
    try:
        _ = DateTranslator.singleton()
        del DateTranslator.instance  # noqa
    except SingletonNotExist:
        pass
    finally:
        return DateTranslator(date_format=DEFAULT_DATE_FORMAT)


@pytest.fixture(scope="module")
def destroy_singletons(request):
    def remove_datetranslator_storage():
        DateTranslator.instance = None
        del DateTranslator.instance

    def remove_scheduleconfig_storage():
        ScheduleConfig.instance = None
        del ScheduleConfig.instance

    request.addfinalizer(remove_datetranslator_storage)
    request.addfinalizer(remove_scheduleconfig_storage)
