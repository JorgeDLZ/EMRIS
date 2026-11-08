import pytest

from config.env import env_bool, env_list


@pytest.mark.parametrize("raw", ["1", "true", "True", "YES", "on"])
def test_env_bool_true_values(monkeypatch, raw):
    monkeypatch.setenv("FLAG", raw)
    assert env_bool("FLAG") is True


@pytest.mark.parametrize("raw", ["0", "false", "False", "", "no", "off", "nope"])
def test_env_bool_false_values(monkeypatch, raw):
    monkeypatch.setenv("FLAG", raw)
    assert env_bool("FLAG", default=True) is False


def test_env_bool_default_when_unset(monkeypatch):
    monkeypatch.delenv("FLAG", raising=False)
    assert env_bool("FLAG", default=True) is True


def test_env_list_trims_and_drops_empty(monkeypatch):
    monkeypatch.setenv("HOSTS", "a.com, b.com,")
    assert env_list("HOSTS") == ["a.com", "b.com"]


def test_env_list_default_when_unset(monkeypatch):
    monkeypatch.delenv("HOSTS", raising=False)
    assert env_list("HOSTS") == []
