import unittest

from applications.iiit.Utils.ispace_msg import ISPACE_Msg_ActivePower
from applications.iiit.Utils.ispace_msg_utils import get_default_ap_msg


class MyTestCase(unittest.TestCase):

    tmp1 = None  # type: ISPACE_Msg_ActivePower
    tmp2 = None  # type: ISPACE_Msg_ActivePower

    def test_int(self):
        print('\ntest_int')
        self.tmp1 = get_default_ap_msg('192.168.1.4', 'device-1')
        self.tmp2 = get_default_ap_msg('192.168.1.4', 'device-2')

        self.tmp1.set_value(10)
        self.tmp2.set_value(30)
        print(
            'tmp1: {}'.format(self.tmp1.get_value())
            + ', tmp2: {}'.format(self.tmp2.get_value())
        )

        self.tmp1 += 40
        print('tmp1 += 40: {}'.format(self.tmp1.get_value()))

        self.assertEqual(self.tmp1.get_value(), 50.0)
        return

    def test_float(self):
        print('\ntest_float')
        self.tmp1 = get_default_ap_msg('192.168.1.4', 'device-1')
        self.tmp2 = get_default_ap_msg('192.168.1.4', 'device-2')

        self.tmp1.set_value(10)
        self.tmp2.set_value(30)
        print(
            'tmp1: {}'.format(self.tmp1.get_value())
            + ', tmp2: {}'.format(self.tmp2.get_value())
        )

        self.tmp1 += 60.0
        print('tmp1 += 60.0: {}'.format(self.tmp1.get_value()))

        self.assertEqual(self.tmp1.get_value(), 70.0)
        return

    def test_ispace_msg(self):
        print('\ntest_ispace_msg')
        self.tmp1 = get_default_ap_msg('192.168.1.4', 'device-1')
        self.tmp2 = get_default_ap_msg('192.168.1.4', 'device-2')

        self.tmp1.set_value(10)
        self.tmp2.set_value(30)
        print(
            'tmp1: {}'.format(self.tmp1.get_value())
            + ', tmp2: {}'.format(self.tmp2.get_value())
        )

        self.tmp1 += self.tmp2
        print('tmp1 += self.tmp2: {}'.format(self.tmp1.get_value()))

        self.assertEqual(self.tmp1.get_value(), 40.0)
        return


if __name__ == '__main__':
    unittest.main()
