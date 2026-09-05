import unittest

from scripts.check_public_boundary import PATTERNS


class PublicBoundaryTests(unittest.TestCase):
    def test_original_repository_site_and_relative_app_paths_remain_blocked(self):
        pattern = PATTERNS['original app reference']
        for value in ('https://github.com/BD4L/Breaches', 'https://bd4l.github.io/Breaches/',
                      '"/Breaches/data.json"', "'/Breaches/'"):
            self.assertIsNotNone(pattern.search(value))

    def test_official_source_directory_named_breaches_is_not_original_app_coupling(self):
        self.assertIsNone(PATTERNS['original app reference'].search(
            'https://consumer.sc.gov/sites/consumer/files/Documents/Related%20Laws/Breaches/2020/notice.pdf'))


if __name__ == '__main__':
    unittest.main()
