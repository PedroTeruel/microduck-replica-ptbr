import unittest
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from training_studio.pretrained import pretrained_models


class PretrainedCatalogTests(unittest.TestCase):
    def test_state_includes_inventory_without_creating_or_installing_models(self):
        from training_studio.service import StudioService
        with tempfile.TemporaryDirectory() as folder:
            with patch('training_studio.service.inspect_environment', return_value={'ready': True}):
                service = StudioService(Path(folder) / 'state', Path(folder) / 'engine', demo=True)
            try:
                state = service.state()
                self.assertEqual(len(state['pretrained_models']), 20)
                self.assertEqual(state['runs'], [])
                self.assertIsNone(state['active_run_id'])
                self.assertFalse((Path(folder) / 'engine').exists())
            finally:
                service.shutdown()

    def test_public_catalog_keeps_sources_hardware_and_capabilities_distinct(self):
        models = pretrained_models()
        self.assertEqual(len(models), 20)
        self.assertEqual(len({m['id'] for m in models}), 20)
        for model in models:
            with self.subTest(model=model['id']):
                self.assertEqual(model['format'], 'ONNX')
                self.assertEqual(model['capabilities'], dict(installed=False, local_evaluation=False, resume_training=False))
                self.assertRegex(model['revision'], r'^[0-9a-f]{40}$')
                self.assertRegex(model['sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(model['verification'])
                self.assertTrue(model['compatibility'])
                for key in ('source_url', 'download_url', 'license_url', 'hash_source_url'):
                    url = urlsplit(model[key])
                    self.assertEqual(url.scheme, 'https')
                    self.assertIn(url.hostname, ('huggingface.co', 'github.com', 'raw.githubusercontent.com'))
                    self.assertFalse(url.username or url.password)
                if model['source_kind'] == 'official':
                    self.assertEqual(model['version'], 'V8')
                    self.assertEqual(model['servos'], 'XL330')
                    self.assertIn(model['revision'], model['download_url'])
                else:
                    self.assertEqual(model['servos'], 'HD1910')
                    self.assertIn('非商业', model['license_label'])

    def test_community_bundle_link_never_masquerades_as_one_model(self):
        models = pretrained_models()
        bundled = [m for m in models if m['download_label'] == '查看发布包']
        self.assertEqual(len(bundled), 5)
        self.assertTrue(all(m['source_kind'] == 'community' and m['model_file'].endswith('.onnx') for m in bundled))
        self.assertTrue(all(any('发布包' in text for text in m['details']) for m in bundled))
        self.assertEqual(sum(m['requires_rollers'] for m in models), 6)

    def test_callers_cannot_mutate_future_catalog(self):
        models = pretrained_models()
        first = models[0]['id']
        models[0]['capabilities']['resume_training'] = True
        models[0]['tags'].append('changed')
        fresh = pretrained_models()
        self.assertEqual(fresh[0]['id'], first)
        self.assertFalse(fresh[0]['capabilities']['resume_training'])
        self.assertNotIn('changed', fresh[0]['tags'])


if __name__ == '__main__':
    unittest.main()
