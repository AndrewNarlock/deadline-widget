"""Tests for turning course pages into plain text."""

import unittest

from deadline_widget.sources.pages import page_text

HTML = """
<html><head><title>Week 4</title><script>steal()</script></head>
<body>
  <nav>Home | Syllabus</nav>
  <main>
    <h2>Week 4: Oct 19-23</h2>
    <p>Read <em>Chapter 3</em> before Friday.<br>Bring questions.</p>
    <table><tr><td>Mon</td><td>Quiz 2</td></tr></table>
  </main>
</body></html>
"""


class PageTextTest(unittest.TestCase):
    def setUp(self):
        self.title, self.text = page_text(HTML)

    def test_title(self):
        self.assertEqual(self.title, "Week 4")

    def test_keeps_inline_words_together_and_blocks_on_their_own_lines(self):
        self.assertEqual(
            self.text.splitlines(),
            ["Week 4: Oct 19-23", "Read Chapter 3 before Friday.", "Bring questions.", "Mon | Quiz 2"],
        )

    def test_drops_scripts_and_navigation(self):
        self.assertNotIn("steal", self.text)
        self.assertNotIn("Syllabus", self.text)


if __name__ == "__main__":
    unittest.main()
