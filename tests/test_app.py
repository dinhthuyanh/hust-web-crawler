import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.patch = patch.object(app, 'DATA', self.data)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app.LINK_CACHE.update(signature=None, rows=[])
        (self.data / 'links.csv').write_text(
            'url,title,type,status_code,decision,reason\n'
            'https://hust.edu.vn/a,Tuyển sinh,html,200,KEEP,OK\n'
            'https://hust.edu.vn/b,Lỗi,html,403,DROP,Forbidden\n', encoding='utf-8')

    def test_status_falls_back_to_links_and_preserves_counts(self):
        with patch.object(app, 'crawler_pid', return_value=None):
            status = app.snapshot()
        self.assertEqual((status['processed'], status['kept'], status['dropped']), (2, 1, 1))
        self.assertEqual(status['statuses'], {'200': 1, '403': 1})
        self.assertFalse(status['running'])

    def test_report_and_filters(self):
        (self.data / 'report.json').write_text(json.dumps({'processed_urls': 20, 'pending_urls': 10}))
        with patch.object(app, 'crawler_pid', return_value=100):
            status = app.snapshot()
        self.assertEqual(status['processed'], 20)
        self.assertTrue(status['running'])
        rows = app.filtered_links({'q': ['TUYỂN'], 'decision': ['KEEP'], 'type': ['html']})
        self.assertEqual(len(rows), 1)
        self.assertEqual(app.filtered_links({'decision': ['DROP'], 'q': ['tuyển']}), [])

    def test_broken_report_and_missing_csv(self):
        (self.data / 'report.json').write_text('{')
        (self.data / 'links.csv').unlink()
        with patch.object(app, 'crawler_pid', return_value=None):
            self.assertEqual(app.snapshot()['processed'], 0)

    def test_markdown_urls_are_normalized(self):
        self.assertEqual(app.clean_url('[HUST](https://hust.edu.vn/)'), 'https://hust.edu.vn/')

    def test_unrelated_pid_is_not_signalled(self):
        pidfile = self.data / 'pid'
        pidfile.write_text('123')
        with patch.object(app, 'PID', pidfile), patch('app.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'unrelated-process'
            self.assertIsNone(app.crawler_pid())

    def handler(self, path):
        handler = object.__new__(app.Handler)
        handler.path = path
        handler.headers = {'Host': '127.0.0.1:8000', 'Origin': 'http://127.0.0.1:8000'}
        handler.send_data = unittest.mock.Mock()
        return handler

    def test_start_rejects_duplicate_process(self):
        handler = self.handler('/api/crawler/start')
        with patch.object(app, 'crawler_pid', return_value=123), patch('app.subprocess.Popen') as spawn:
            handler.do_POST()
        self.assertEqual(handler.send_data.call_args.args[0], 409)
        spawn.assert_not_called()

    def test_stop_requests_checkpoint_without_killing_process_group(self):
        handler = self.handler('/api/crawler/stop')
        with patch.object(app, 'crawler_pid', return_value=123), patch('app.os.kill') as kill:
            handler.do_POST()
        kill.assert_called_once_with(123, app.signal.SIGINT)
        self.assertEqual(handler.send_data.call_args.args[0], 202)

    def test_cross_origin_control_is_rejected_before_process_lookup(self):
        handler = self.handler('/api/crawler/start')
        handler.headers['Origin'] = 'https://other.example'
        with patch.object(app, 'crawler_pid') as lookup:
            handler.do_POST()
        lookup.assert_not_called()
        self.assertEqual(handler.send_data.call_args.args[0], 403)


if __name__ == '__main__':
    unittest.main()
