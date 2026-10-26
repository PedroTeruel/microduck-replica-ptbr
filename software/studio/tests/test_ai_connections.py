"""Private AI drafts survive restart without exposing credentials."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from studio.ai_connections import Connections, AiError


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ai-connections.json'
        self.store = Connections(self.tmp.name)

    def save(self, **values):
        return self.store.save({'name': '豆包草稿', 'provider': 'doubao_ark',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3', 'model': '',
            'auth_mode': 'bearer', **values})

    def test_read_does_not_create_personal_configuration(self):
        self.assertEqual(self.store.view()['connections'], [])
        self.assertFalse(self.path.exists())

    def test_draft_secret_restart_selection_and_delete(self):
        item = self.save(api_key='private-key-123')
        self.assertEqual(item['missing'], ['model'])
        self.assertNotIn('private-key-123', json.dumps(self.store.view()))
        with self.assertRaises(AiError):
            self.store.select(item['id'])
        item = self.save(id=item['id'], model='manual')
        self.store.select(item['id'])
        restart = Connections(self.tmp.name)
        self.assertEqual(restart.view()['current_id'], item['id'])
        self.assertEqual(restart.private(item['id'], item['revision'])[0]['api_key'], 'private-key-123')
        if os.name != 'nt':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        restart.delete(item['id'])
        self.assertIsNone(restart.view()['current_id'])

    def test_blank_key_keeps_only_same_destination_and_explicit_clear_works(self):
        item = self.save(model='my-model', api_key='private-key-123')
        same = self.save(id=item['id'], model='my-model', api_key='')
        self.assertTrue(same['key_configured'])
        changed = self.save(id=item['id'], model='my-model', base_url='https://other.example/v1')
        self.assertFalse(changed['key_configured'])
        self.assertIn('api_key', changed['missing'])
        cleared = self.save(id=item['id'], clear_key=True)
        self.assertFalse(cleared['key_configured'])

    def test_short_key_does_not_rewrite_schema_or_identifiers(self):
        item = self.save(model='model', api_key='model')
        self.assertEqual(item['model'], '[已隐藏]')
        self.assertEqual(item['provider'], 'doubao_ark')
        self.assertEqual(len(item['id']),24)
        self.store.select(item['id'])
        state = self.store.view()
        self.assertIn('connections',state)
        self.assertEqual(state['current_id'],item['id'])
        self.assertIn('model',state['connections'][0])

    def test_url_delimiters_types_and_private_state_schema_are_strict(self):
        for url in (None,False,123,'https://example.com?','https://example.com#'):
            with self.subTest(url=url), self.assertRaises(AiError):
                self.save(base_url=url)
        self.path.write_text(json.dumps({'version':1,'generation':0,'current_id':None,
            'connections':[{'id':'x'*24}]}))
        original = self.path.read_bytes()
        with self.assertRaises(AiError):
            self.save()
        self.assertEqual(self.path.read_bytes(), original)

    def test_corrupt_state_is_preserved_on_read_and_save(self):
        self.path.write_bytes(b'{broken private bytes')
        for action in (self.store.view, self.save):
            with self.assertRaises(AiError) as caught:
                action()
            self.assertEqual(caught.exception.code, 'state')
            self.assertEqual(self.path.read_bytes(), b'{broken private bytes')

    def test_validation_and_limit(self):
        for values in ({'provider':'fake'}, {'base_url':'https://user:pw@example.com'},
                       {'base_url':'http://public.example/v1'}, {'base_url':'https://example.com?key=x'},
                       {'base_url':'https://example.com/#x'}, {'auth_mode':'none'}, {'extra':'ignored'}):
            with self.subTest(values=values), self.assertRaises(AiError):
                self.save(**values)
        local = self.save(base_url='http://127.0.0.1:8000/v1', auth_mode='none', model='local')
        self.assertTrue(local['ready'])
        for i in range(9):
            self.save(name=str(i))
        with self.assertRaises(AiError):
            self.save()

    def test_keys_cannot_contain_header_whitespace_or_non_ascii(self):
        for key in ('hello world','bad\tkey','bad\nkey','密钥'):
            with self.subTest(key=key), self.assertRaises(AiError):
                self.save(api_key=key)

    def test_delete_current_does_not_select_another_saved_connection(self):
        first = self.save(model='one', api_key='secret-one')
        other = self.save(model='two', api_key='secret-two')
        self.store.select(first['id'])
        self.store.delete(first['id'])
        view = self.store.view()
        self.assertIsNone(view['current_id'])
        self.assertEqual(view['connections'][0]['id'],other['id'])

    def test_public_fields_are_redacted_and_revisions_reject_stale_calls(self):
        item = self.save(name='my-secret-key', api_key='my-secret-key', model='model')
        self.assertNotIn('my-secret-key', json.dumps(self.store.view()))
        self.save(id=item['id'], model='changed')
        with self.assertRaises(AiError):
            self.store.private(item['id'], item['revision'])

    def test_finishing_reply_checks_revision_and_redacts_under_the_same_lock(self):
        item = self.save(model='manual',api_key='private-key-123')
        _,generation = self.store.private(item['id'],item['revision'])
        self.assertEqual(self.store.finish(generation,'echo private-key-123'),'echo [已隐藏]')
        self.store.select(item['id'])
        with self.assertRaises(AiError) as caught:
            self.store.finish(generation,'stale reply')
        self.assertEqual(caught.exception.code,'stale')


if __name__ == '__main__':
    unittest.main()
