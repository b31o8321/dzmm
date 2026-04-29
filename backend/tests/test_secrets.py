from unittest.mock import patch

from dzmm.secrets import store_api_key, get_api_key, delete_api_key, mask_key


def test_store_and_retrieve_api_key():
    fake_store = {}

    def fake_set(service, name, value):
        fake_store[(service, name)] = value

    def fake_get(service, name):
        return fake_store.get((service, name))

    def fake_del(service, name):
        fake_store.pop((service, name), None)

    with patch("keyring.set_password", side_effect=fake_set), \
         patch("keyring.get_password", side_effect=fake_get), \
         patch("keyring.delete_password", side_effect=fake_del):
        store_api_key("doubao_main", "sk-abcdef123456")
        assert get_api_key("doubao_main") == "sk-abcdef123456"
        delete_api_key("doubao_main")
        assert get_api_key("doubao_main") is None


def test_mask_key():
    assert mask_key("sk-abcdef123456") == "sk-abc***3456"
    assert mask_key("short") == "***"
    assert mask_key("") == "***"
    assert mask_key(None) == "***"
