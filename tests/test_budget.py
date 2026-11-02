import unittest
from unittest.mock import Mock, patch

from game import server


class BudgetTests(unittest.TestCase):
    def test_local_budget_remains_bounded_without_shared_store(self):
        with patch.object(server, "BACKEND", "ollama"):
            budget = server.Budget(1)
            budget.take()
            with self.assertRaises(server.OutOfBudget):
                budget.take()

    def test_paid_backend_requires_shared_store(self):
        with patch.object(server, "BACKEND", "tinker"):
            with self.assertRaises(server.OutOfBudget):
                server.Budget(10).take()

    def test_store_outage_never_spends_a_fallback_allowance(self):
        budget = server.Budget(10)
        budget.store = Mock()
        budget.store.pipeline.side_effect = ConnectionError("offline")
        with self.assertRaises(server.OutOfBudget):
            budget.take()
        self.assertEqual(budget.used, 0)

    def test_store_recovery_resumes_using_the_shared_count(self):
        budget = server.Budget(1)
        budget.store = Mock()
        pipeline = budget.store.pipeline.return_value
        pipeline.incr.return_value = pipeline
        pipeline.expire.return_value = pipeline
        pipeline.execute.side_effect = [ConnectionError("offline"), [1, True], [2, True]]
        with self.assertRaises(server.OutOfBudget):
            budget.take()
        budget.take()
        self.assertFalse(budget.store_down)
        with self.assertRaises(server.OutOfBudget):
            budget.take()


if __name__ == "__main__":
    unittest.main()
