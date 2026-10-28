import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import deploy_site


class DeploySiteTest(unittest.TestCase):
    def test_og_uploads_first_even_when_file_size_has_not_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            docs = Path(temp)
            (docs / 'og.png').write_bytes(b'new!')
            (docs / 'logo.png').write_bytes(b'same')
            (docs / 'index.html').write_text('<html></html>')
            ftp = Mock()
            ftp.size.return_value = 4
            with patch.object(deploy_site, 'DOCS_DIR', docs), \
                    patch.object(deploy_site, 'load_env', return_value={'TL_WEB_DIR': '/site'}), \
                    patch.object(deploy_site, 'ftp_connect', return_value=ftp), \
                    patch.object(deploy_site, 'mkdirs'), patch('sys.argv', ['deploy_site.py']):
                deploy_site.main()
            self.assertEqual([call.args[0] for call in ftp.storbinary.call_args_list],
                             ['STOR /site/polataj/og.png', 'STOR /site/polataj/index.html'])
            ftp.quit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
