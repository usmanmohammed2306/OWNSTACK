import unittest
import re
from sample_app.report import export_pdf


class PDFContractTests(unittest.TestCase):
    def test_cross_reference_offsets_and_stream_length(self):
        pdf = export_pdf("Project Atlas", ["Atlas roadmap"])
        start = re.search(rb"startxref\s+(\d+)\s+%%EOF", pdf)
        self.assertIsNotNone(start)
        offset = int(start.group(1))
        self.assertEqual(pdf[offset:offset + 4], b"xref")
        table = re.match(rb"xref\s+0\s+(\d+)\s+([^t]+)trailer", pdf[offset:])
        self.assertIsNotNone(table)
        entries = table.group(2).splitlines()
        self.assertEqual(len(entries), int(table.group(1)))
        self.assertEqual(entries[0].strip(), b"0000000000 65535 f")
        for number, entry in enumerate(entries[1:], 1):
            address = int(entry.split()[0])
            self.assertTrue(pdf[address:].startswith(f"{number} 0 obj".encode()))
        stream = re.search(rb"/Length\s+(\d+)\s*>>\s*stream\r?\n(.*?)\r?\nendstream", pdf, re.S)
        self.assertIsNotNone(stream)
        self.assertEqual(int(stream.group(1)), len(stream.group(2)))

    def test_pdf_has_parseable_structure(self):
        pdf = export_pdf("Project Atlas", ["Atlas roadmap", "Atlas budget"])
        self.assertTrue(pdf.startswith(b"%PDF-1."))
        self.assertIn(b"xref", pdf)
        self.assertIn(b"trailer", pdf)
        self.assertIn(b"%%EOF", pdf)
        self.assertIn(b"Project Atlas", pdf)

    def test_no_unrelated_tenant_data_appears(self):
        pdf = export_pdf("Project Atlas", ["Atlas roadmap"])
        self.assertNotIn(b"Nova", pdf)

    def test_content_is_escaped(self):
        pdf = export_pdf("A (test) \\ project", [])
        self.assertIn(b"A \\(test\\) \\\\ project", pdf)


if __name__ == "__main__":
    unittest.main()
