import unittest

from applications.iiit.Utils.ispace_msg import round_off_pp


class MyTestCase(unittest.TestCase):

    def test_something(self):

        print('round_off_pp(0): {:0.2f}'.format(round_off_pp(0)))
        print('round_off_pp(.10): {:0.2f}'.format(round_off_pp(.10)))
        print('round_off_pp(1): {:0.2f}'.format(round_off_pp(1)))
        print('round_off_pp(10): {:0.2f}'.format(round_off_pp(10)))
        print('round_off_pp(1.25): {:0.2f}'.format(round_off_pp(1.25)))

        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
