"""Exercise the actual script entry point without opening a server socket."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from extract_sheet import excel_to_dataframe


ROOT = Path(__file__).resolve().parents[1]


class ServerCommandTests(unittest.TestCase):
    def launch(self, *args):
        with patch.object(sys, 'argv', ['main.py', *map(str, args)]):
            runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')

    def test_custom_workbook_loads_once_with_first_or_named_sheet(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'other workbook.xlsx'
            workbook = Workbook()
            workbook.active.title = 'First sheet'
            workbook.create_sheet('Other sheet')
            for sheet in workbook:
                sheet.append([None, 'LIMBA FRANCEZĂ'])
                sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', sheet.title])
            workbook.active = 1
            workbook.save(source)
            workbook.close()
            for options, expected in [((), 'First sheet'), (('--sheet', 'Other sheet'), 'Other sheet')]:
                with self.subTest(options=options):
                    with patch('extract_sheet.excel_to_dataframe', wraps=excel_to_dataframe) as loader:
                        with patch('waitress.serve', autospec=True) as run:
                            self.launch(source, *options)
                    loader.assert_called_once_with(str(source), options[1] if options else None)
                    run.assert_called_once()
                    app = run.call_args.args[0]
                    self.assertEqual(app.config['EXCEL_PATH'], str(source))
                    self.assertEqual(app.extensions['lexicon_df'].attrs['sheet_name'], expected)
                    self.assertIn(expected, app.test_client().get('/').get_data(as_text=True))
                    self.assertEqual(run.call_args.kwargs['host'], '127.0.0.1')
                    self.assertEqual(run.call_args.kwargs['port'], 5000)

    def test_no_arguments_keep_the_default_workbook(self):
        with patch('extract_sheet.excel_to_dataframe', wraps=excel_to_dataframe) as loader:
            with patch('waitress.serve', autospec=True) as run:
                self.launch()
        loader.assert_called_once_with(str(ROOT / 'db' / 'example.xlsx'), None)
        run.assert_called_once()

    def test_binding_port_and_proxy_options(self):
        for arguments, host, port in [
            ((), '127.0.0.1', 5000),
            (('--local', '--port', '8080'), '127.0.0.1', 8080),
            (('--public', '--port', '9000'), '0.0.0.0', 9000),
            (('--host', '192.0.2.10'), '192.0.2.10', 5000),
            (('--host', '::1'), '::1', 5000),
        ]:
            with self.subTest(arguments=arguments), patch('waitress.serve') as run:
                self.launch(*arguments)
                self.assertEqual(run.call_args.kwargs['host'], host)
                self.assertEqual(run.call_args.kwargs['port'], port)
                self.assertNotIn('trusted_proxy', run.call_args.kwargs)
                self.assertTrue(run.call_args.kwargs['clear_untrusted_proxy_headers'])
                self.assertFalse(run.call_args.kwargs['expose_tracebacks'])
                self.assertFalse(run.call_args.args[0].debug)

        with patch('waitress.serve') as run:
            self.launch('--trusted-host', 'words.example.org', '--trusted-host', 'localhost',
                        '--trusted-proxy', '127.0.0.1', '--secure-cookies')
        app = run.call_args.args[0]
        self.assertEqual(app.config['TRUSTED_HOSTS'], ['words.example.org', 'localhost'])
        self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
        self.assertEqual(app.test_client().get('/', base_url='http://untrusted.example').status_code, 400)
        options = run.call_args.kwargs
        self.assertEqual(options['trusted_proxy'], '127.0.0.1')
        self.assertEqual(options['trusted_proxy_count'], 1)
        self.assertEqual(options['trusted_proxy_headers'], {'x-forwarded-for', 'x-forwarded-proto'})

    def test_invalid_server_options_fail_before_loading_workbook(self):
        for arguments in [
            ('--port', '0'), ('--port', '65536'), ('--port', 'text'),
            ('--local', '--public'), ('--public', '--host', '127.0.0.1'),
            ('--host', 'not-an-ip'), ('--trusted-proxy', '*'),
        ]:
            with self.subTest(arguments=arguments):
                with patch('extract_sheet.excel_to_dataframe') as loader, patch('waitress.serve') as run:
                    with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as stopped:
                        self.launch(*arguments)
                self.assertEqual(stopped.exception.code, 2)
                loader.assert_not_called()
                run.assert_not_called()

    def test_listen_errors_are_readable(self):
        errors = StringIO()
        with patch('waitress.serve', side_effect=OSError('Address already in use')):
            with redirect_stderr(errors), self.assertRaises(SystemExit) as stopped:
                self.launch('--port', '8080')
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn('Could not listen on 127.0.0.1:8080', errors.getvalue())
        self.assertIn('Address already in use', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())

    def test_help_does_not_load_a_workbook(self):
        output = StringIO()
        with patch('extract_sheet.excel_to_dataframe') as loader:
            with patch('waitress.serve') as run:
                with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                    self.launch('--help')
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn('--sheet', output.getvalue())
        self.assertIn('excel_file', output.getvalue())
        loader.assert_not_called()
        run.assert_not_called()

    def test_bad_files_sheets_and_layouts_stop_before_starting_the_server(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            corrupt = directory / 'corrupt.xlsx'
            corrupt.write_text('This is not an Excel ZIP archive.')
            unsupported = directory / 'unsupported.txt'
            unsupported.write_text('Not an Excel file.')
            invalid = directory / 'invalid.xlsx'
            workbook = Workbook()
            workbook.active.append([None, 'Language'])
            workbook.active.append([None, 'Data before an etymon marker'])
            workbook.save(invalid)
            workbook.close()
            duplicate = directory / 'duplicate.xlsx'
            workbook = Workbook()
            workbook.active.append([None, 'Language', 'Language'])
            workbook.active.append(['ETIMON/', 'one', 'two'])
            workbook.save(duplicate)
            workbook.close()
            for arguments, expected in [
                ((directory / 'missing.xlsx',), 'No such file'),
                ((corrupt,), 'not a zip file'),
                ((unsupported,), 'does not support'),
                ((ROOT / 'db' / 'example.xlsx', '--sheet', 'Missing'), 'does not exist'),
                ((invalid,), 'before the first ETIMON/'),
                ((duplicate,), 'Duplicate column heading'),
            ]:
                with self.subTest(arguments=arguments):
                    errors = StringIO()
                    with patch('waitress.serve') as run:
                        with redirect_stderr(errors), self.assertRaises(SystemExit) as stopped:
                            self.launch(*arguments)
                    self.assertEqual(stopped.exception.code, 2)
                    self.assertIn('Could not load', errors.getvalue())
                    self.assertIn(expected, errors.getvalue())
                    self.assertNotIn('Traceback', errors.getvalue())
                    run.assert_not_called()
