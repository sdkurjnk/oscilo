import copy
import sys
import unittest

from oscilo import oscilo_engine
from oscilo.Domain import BUILTIN, ENCLOSING, GLOBAL, LOCAL, NOT_FOUND


DOMAIN_TEST_VALUE = ["global"]

def check_local_variable(frame, previous_reference, previous_snapshot, variable_name):
    # Ask the native engine to compare a local variable in the provided frame.
    return oscilo_engine.check_variable(
        frame,
        previous_reference,
        previous_snapshot,
        LOCAL,
        variable_name,
    )

class TestVMlogEngine(unittest.TestCase):
    def test_returns_none_when_variable_does_not_exist(self):
        frame = sys._getframe()

        result = check_local_variable(frame, None, None, "undefined_var")

        self.assertIsNone(result)

    def test_returns_false_when_value_does_not_change(self):
        sample_list = [1, 2, 3]
        previous_reference = sample_list
        previous_snapshot = copy.deepcopy(sample_list)

        frame = sys._getframe()
        result = check_local_variable(
            frame,
            previous_reference,
            previous_snapshot,
            "sample_list",
        )

        self.assertIs(result, False)

    def test_returns_true_when_reference_changes(self):
        sample_list = [1, 2, 3]
        previous_reference = sample_list
        previous_snapshot = copy.deepcopy(sample_list)

        sample_list = [1, 2, 3]

        frame = sys._getframe()
        result = check_local_variable(
            frame,
            previous_reference,
            previous_snapshot,
            "sample_list",
        )

        self.assertIs(result, True)

    def test_returns_true_when_mutable_data_changes(self):
        mutable_obj = [10, 20]
        previous_reference = mutable_obj
        previous_snapshot = copy.deepcopy(mutable_obj)

        mutable_obj.append(30)

        frame = sys._getframe()
        result = check_local_variable(
            frame,
            previous_reference,
            previous_snapshot,
            "mutable_obj",
        )

        self.assertIs(result, True)

    def test_local_and_global_select_the_requested_scope(self):
        # Give the local and global variables with the same name different objects.
        DOMAIN_TEST_VALUE = ["local"]
        frame = sys._getframe()
        global_value = globals()["DOMAIN_TEST_VALUE"]

        local_result = oscilo_engine.check_variable(
            frame,
            DOMAIN_TEST_VALUE,
            DOMAIN_TEST_VALUE.copy(),
            LOCAL,
            "DOMAIN_TEST_VALUE",
        )
        global_result = oscilo_engine.check_variable(
            frame,
            global_value,
            global_value.copy(),
            GLOBAL,
            "DOMAIN_TEST_VALUE",
        )

        # Each scope contains the same object as its previous reference,
        # so the result should be False.
        self.assertIs(local_result, False)
        self.assertIs(global_result, False)

        # Passing the reference from the other scope should return True
        # because the selected scope contains a different object.
        self.assertIs(
            oscilo_engine.check_variable(
                frame,
                global_value,
                global_value.copy(),
                LOCAL,
                "DOMAIN_TEST_VALUE",
            ),
            True,
        )
        self.assertIs(
            oscilo_engine.check_variable(
                frame,
                DOMAIN_TEST_VALUE,
                DOMAIN_TEST_VALUE.copy(),
                GLOBAL,
                "DOMAIN_TEST_VALUE",
            ),
            True,
        )

    def test_enclosing_selects_free_variable_from_frame_locals(self):
        captured = ["enclosing"]

        def inner():
            frame = sys._getframe()
            return oscilo_engine.check_variable(
                frame,
                captured,
                captured.copy(),
                ENCLOSING,
                "captured",
            )

        self.assertIs(inner(), False)

    def test_untrackable_and_unknown_domains_return_none(self):
        target = ["value"]
        frame = sys._getframe()

        for domain in (BUILTIN, NOT_FOUND, 999):
            with self.subTest(domain=domain):
                result = oscilo_engine.check_variable(
                    frame,
                    target,
                    target.copy(),
                    domain,
                    "target",
                )
                self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main(verbosity=2)