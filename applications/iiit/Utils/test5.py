import unittest
import sys

from enum import IntEnum


class PcaState(IntEnum):
    online = 0
    standalone = 1
    standby = 2
    pass


class MyTestCase(unittest.TestCase):

    def test_1(self):
        print('sys.platform: {}'.format(sys.platform))
        print('Test 1')
        pca_state = PcaState.online
        print('pca_state: {}'.format(pca_state))

        if pca_state not in PcaState:
            print('pca_state: {}, False'.format(pca_state))
        else:
            print('pca_state: {}, True'.format(pca_state))

        pca_state = 10
        print('pca_state: {}'.format(pca_state))

        if pca_state not in PcaState:
            print('pca_state: {}, False'.format(pca_state))
        else:
            print('pca_state: {}, True'.format(pca_state))
        return

    def test_2(self):
        print('\nTest 2')
        pca_state_s = 'online'
        if pca_state_s.lower() not in PcaState.__dict__.keys():
            print('pca_state_s: {}, False'.format(pca_state_s))
            pca_state = PcaState[pca_state_s.lower()]
            print('pca_state: {}, True'.format(pca_state))
        else:
            print('pca_state_s: {}, True'.format(pca_state_s))
            pca_state = PcaState[pca_state_s.lower()]
            print('pca_state: {}, True'.format(pca_state))

        pca_state_s = 'ONLINE'
        if pca_state_s.lower() not in PcaState.__dict__.keys():
            print('pca_state_s: {}, False'.format(pca_state_s))
            pca_state = PcaState[pca_state_s.lower()]
            print('pca_state: {}, True'.format(pca_state))
        else:
            print('pca_state_s: {}, True'.format(pca_state_s))
            pca_state = PcaState[pca_state_s.lower()]
            print('pca_state: {}, True'.format(pca_state))

        pca_state_s = 'SOME_THING_ELSE'
        if pca_state_s.lower() not in PcaState.__dict__.keys():
            print('pca_state_s: {}, False'.format(pca_state_s))
            pca_state = PcaState.online
            print('pca_state: {}, True'.format(pca_state))
        else:
            print('pca_state_s: {}, True'.format(pca_state_s))
            pca_state = PcaState[pca_state_s.lower()]
            print('pca_state: {}, True'.format(pca_state))
        return


if __name__ == '__main__':
    unittest.main()
