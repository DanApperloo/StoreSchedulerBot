import datetime
import pytest

from freezegun import freeze_time

from util.date import DateTranslator, CommonDate
from util.exception import SingletonNotExist, SingletonExist
from test.fixture import destroy_datetranslator, default_datetranslator


def test_datetranslator_singleton(destroy_datetranslator):
    # Detect uninitialized Singleton
    with pytest.raises(SingletonNotExist):
        DateTranslator.singleton()

    # Set an invalid existing Singleton
    DateTranslator.instance = 'deadbeef'
    with pytest.raises(SingletonNotExist):
        DateTranslator.singleton()
    del DateTranslator.instance

    # Ensure init fails if Singleton already exists
    _ = DateTranslator()
    with pytest.raises(SingletonExist):
        _ = DateTranslator()
    del DateTranslator.instance

    # Ensure we can get the Singleton instance
    a = DateTranslator()
    assert a.initialized
    assert DateTranslator.singleton() is a

    # Ensure we can't create a new one
    with pytest.raises(SingletonExist):
        _ = DateTranslator()


def test_datetranslator_get_date_format(default_datetranslator, destroy_datetranslator):
    assert default_datetranslator._date_format == DateTranslator.get_date_format()


@freeze_time("2023-09-24 03:21:34")
def test_datetranslator_today(default_datetranslator, destroy_datetranslator):
    # PDT is 7 hours behind at the sample time
    today = DateTranslator.today()
    assert today.year == 2023
    assert today.month == 9
    assert today.day == 23


def test_datetranslator_is_valid_date(default_datetranslator, destroy_datetranslator):
    # Using Default Format
    assert DateTranslator.is_valid_date("9/12/2001")
    assert not DateTranslator.is_valid_date("30/0/2001")
    assert DateTranslator.is_valid_date("09/02/2001")


def test_datetranslator_is_valid_day(default_datetranslator, destroy_datetranslator):
    assert DateTranslator.is_valid_day("Monday")
    assert DateTranslator.is_valid_day("monday")
    assert DateTranslator.is_valid_day("Tuesday")
    assert DateTranslator.is_valid_day("tuesday")
    assert DateTranslator.is_valid_day("Wednesday")
    assert DateTranslator.is_valid_day("wednesday")
    assert DateTranslator.is_valid_day("Thursday")
    assert DateTranslator.is_valid_day("thursday")
    assert DateTranslator.is_valid_day("Friday")
    assert DateTranslator.is_valid_day("friday")
    assert DateTranslator.is_valid_day("Saturday")
    assert DateTranslator.is_valid_day("saturday")
    assert DateTranslator.is_valid_day("Sunday")
    assert DateTranslator.is_valid_day("sunday")
    assert not DateTranslator.is_valid_day("Today")


def test_datetranslator_is_valid_shortcut(default_datetranslator, destroy_datetranslator):
    assert DateTranslator.is_valid_shortcut("Today")
    assert DateTranslator.is_valid_shortcut("today")
    assert DateTranslator.is_valid_shortcut("Tomorrow")
    assert DateTranslator.is_valid_shortcut("tomorrow")
    assert not DateTranslator.is_valid_shortcut("Monday")


@freeze_time("2023-09-24 12:21:34")
def test_datetranslator_date_from_day(default_datetranslator, destroy_datetranslator):
    assert DateTranslator.date_from_day("Sunday") == datetime.date.today()

    expected = (datetime.date.today() + datetime.timedelta(days=1))
    assert DateTranslator.date_from_day("Monday") == expected

    expected = (datetime.date.today() + datetime.timedelta(days=2))
    assert DateTranslator.date_from_day("Tuesday") == expected

    expected = (datetime.date.today() + datetime.timedelta(days=3))
    assert DateTranslator.date_from_day("Wednesday") == expected

    expected = (datetime.date.today() + datetime.timedelta(days=4))
    assert DateTranslator.date_from_day("Thursday") == expected

    expected = (datetime.date.today() + datetime.timedelta(days=5))
    assert DateTranslator.date_from_day("Friday") == expected

    expected = (datetime.date.today() + datetime.timedelta(days=6))
    assert str(DateTranslator.date_from_day("Saturday")) == expected.strftime(
        DateTranslator.get_date_format())

    with pytest.raises(ValueError):
        DateTranslator.date_from_day("31/0/2000")


@freeze_time("2023-09-24 12:21:34")
def test_datetranslator_day_from_shortcut(default_datetranslator, destroy_datetranslator):
    assert DateTranslator.day_from_shortcut("Today") == datetime.datetime.today().strftime("%A")

    expected = (datetime.datetime.today() + datetime.timedelta(days=1)).strftime("%A")
    assert DateTranslator.day_from_shortcut("Tomorrow") == expected

    with pytest.raises(ValueError):
        DateTranslator.day_from_shortcut("Yesterday")


@freeze_time("2023-09-24 12:21:34")
def test_datetranslator_day_from_date(default_datetranslator, destroy_datetranslator):
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/24/2023")) == "Sunday"
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/23/2023")) == "Saturday"
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/22/2023")) == "Friday"
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/21/2023")) == "Thursday"
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/20/2023")) == "Wednesday"
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/19/2023")) == "Tuesday"
    assert DateTranslator.day_from_date(CommonDate.deserialize("09/25/2023")) == "Monday"

    with pytest.raises(ValueError):
        DateTranslator.date_from_day("31/0/2000")

    with pytest.raises(ValueError):
        DateTranslator.date_from_day("2023-09-24")
