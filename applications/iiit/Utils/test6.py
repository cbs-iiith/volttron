import unittest
from random import randint

from applications.iiit.Utils.ispace_msg import MessageType, ISPACE_Msg


def get_default_pp_msg(discovery_address, device_id):
    return ISPACE_Msg(
        MessageType.price_point, False, True,
        0, 'float', '%',
        None,
        discovery_address, device_id,
        None, None,
        3600, 3600, 60, 'UTC'
    )
    pass


class MyTestCase(unittest.TestCase):
    tmp1 = get_default_pp_msg('192.168.1.4', 'device-1')
    tmp2 = get_default_pp_msg('192.168.1.4', 'device-2')
    tmp3 = get_default_pp_msg('192.168.1.4', 'device-3')
    tmp4 = get_default_pp_msg('192.168.1.4', 'device-4')

    tmp1.set_price_id(randint(0, 99999999))
    tmp2.set_price_id(randint(0, 99999999))
    tmp3.set_price_id(randint(0, 99999999))
    tmp4.set_price_id(randint(0, 99999999))

    def test_1(self):
        check = (
            True
            if self.tmp1 in [self.tmp1, self.tmp2, self.tmp3]
            else False
        )
        print(
            'pp msg id: {}, list: {}'.format(
                self.tmp1.get_price_id(),
                [self.tmp1.get_price_id(),
                 self.tmp2.get_price_id(),
                 self.tmp3.get_price_id()
                 ]
            )
        )
        self.assertEqual(check, True)
        return

    def test_2(self):
        check = (
            True
            if self.tmp4 in [self.tmp1, self.tmp2, self.tmp3]
            else False
        )
        print(
            '\npp msg id: {}, list: {}'.format(
                self.tmp4.get_price_id(),
                [self.tmp1.get_price_id(),
                 self.tmp2.get_price_id(),
                 self.tmp3.get_price_id()
                 ]
            )
        )
        self.assertEqual(check, False)
        return


if __name__ == '__main__':
    unittest.main()
