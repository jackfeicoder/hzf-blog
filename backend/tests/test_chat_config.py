"""Public source must not embed a provider credential or replace a user's key."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from routers import chat


class ChatConfigTests(unittest.TestCase):
    def test_user_key_wins_over_site_default(self):
        with patch.object(chat, 'DEFAULT_FREE_KEY', 'fixture-site-key'):
            self.assertEqual(chat.resolve_api_key('sensenova', ' fixture-user-key '), 'fixture-user-key')

    def test_only_sensenova_can_use_configured_default(self):
        with patch.object(chat, 'DEFAULT_FREE_KEY', 'fixture-site-key'):
            self.assertEqual(chat.resolve_api_key('SENSENOVA', ''), 'fixture-site-key')
            with self.assertRaises(HTTPException):
                chat.resolve_api_key('custom', None)

    def test_missing_default_is_actionable_and_provider_listing_is_honest(self):
        with patch.object(chat, 'DEFAULT_FREE_KEY', ''):
            with self.assertRaises(HTTPException) as raised:
                chat.resolve_api_key('sensenova', None)
            self.assertEqual(raised.exception.status_code, 400)
            self.assertFalse(chat.list_providers()['providers'][0]['is_free'])
