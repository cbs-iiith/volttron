import unittest

# from applications.iiit.Utils.ispace_utils import isclose
EPSILON = 1e-04


def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    # _log.debug('isclose()')
    value = abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
    return value


class MyTestCase(unittest.TestCase):

    def test_something(self):
        budget = 1785.71
        new_ed = 4060.50
        deadband = 100

        if isclose(budget, new_ed, EPSILON, deadband):
            print(
                'is close'
                + ' |budget({:0.2f})'.format(budget)
                + ' - new_ed({:0.2f})|'.format(new_ed)
                + ' < deadband({:0.4f})'.format(deadband)
            )
        else:
            print(
                'not close'
                + ' |budget({:0.2f})'.format(budget)
                + ' - new_ed({:0.2f})|'.format(new_ed)
                + ' < deadband({:0.4f})'.format(deadband)
            )

        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
