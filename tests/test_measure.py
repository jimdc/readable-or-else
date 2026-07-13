import unittest

from reading_gate.measure import measure


class TestMeasureEnglish(unittest.TestCase):
    def test_simple_sentence_is_low_grade(self):
        text = "The cat sat on the mat. It was happy."
        m = measure(text, language="en")
        self.assertEqual(m.language, "en")
        self.assertIsNotNone(m.grade)
        self.assertEqual(m.grade_formula, "flesch_kincaid_grade")
        self.assertLess(m.grade, 5)
        self.assertGreater(m.word_count, 0)
        self.assertIn("flesch_reading_ease", m.details)

    def test_complex_sentence_is_high_grade(self):
        text = (
            "Notwithstanding the aforementioned considerations, the jurisdictional "
            "ramifications of the promulgated regulatory framework necessitate a "
            "comprehensive reassessment of interdepartmental accountability mechanisms."
        )
        m = measure(text, language="en")
        self.assertGreater(m.grade, 12)

    def test_complex_text_scores_higher_than_simple_text(self):
        simple = measure("The dog ran. It was fast. We saw it go.", language="en")
        complex_ = measure(
            "The quadrupedal mammal exhibited an accelerated locomotive gait that "
            "was readily observable to bystanders in the vicinity.",
            language="en",
        )
        self.assertGreater(complex_.grade, simple.grade)


class TestMeasureSpanish(unittest.TestCase):
    def test_spanish_is_measure_only(self):
        text = "Este es un texto de prueba con palabras sencillas y claras."
        m = measure(text, language="es")
        self.assertEqual(m.language, "es")
        self.assertIsNone(m.grade)
        self.assertEqual(m.grade_formula, "measure_only")
        self.assertIn("fernandez_huerta", m.details)
        self.assertIn("szigriszt_pazos", m.details)


class TestMeasureErrors(unittest.TestCase):
    def test_unsupported_language_raises(self):
        with self.assertRaises(ValueError):
            measure("some text", language="fr")


if __name__ == "__main__":
    unittest.main()
