# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

# }}}

# Sam
import math
import unittest


def mround(num, multiple_of):
    # _log.debug('mround()')
    value = math.floor((num + multiple_of / 2) / multiple_of) * multiple_of
    return value


# return energy in Wh for the given duration
def calc_energy_wh(pwr_wh, duration_sec):
    value = (pwr_wh * duration_sec) / 3600
    return value


class MyTestCase(unittest.TestCase):
    _pf_zn_ac = {
        "roundup": 0.5,
        "idx": 0,
        "coefficients": [
            {"a": 7.5, "b": -1.5, "c": 24}
        ]
    }

    _pf_zn_light = {
        "roundup": 5,
        "idx": 0,
        "coefficients": [
            {"a": -35, "b": -35, "c": 100}
        ]
    }

    _edf_zn_ac = {
        "roundup": 100,
        "idx": 0,
        "coefficients": [
            {"a": 102.94, "b": -6128.3, "c": 91699}
        ]
    }

    _edf_zn_light = {
        "roundup": 5,
        "idx": 0,
        "coefficients": [
            {"a": 50, "b": 20, "c": 68}
        ]
    }

    # compute new zone temperature set point from price functions
    def _compute_new_tsp(self, pp):
        # type: (float) -> float
        pp = 0 if pp < 0 else 1 if pp > 1 else pp

        idx = self._pf_zn_ac['idx']
        roundup = self._pf_zn_ac['roundup']
        coefficients = self._pf_zn_ac['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        tsp = a * pp ** 2 + b * pp + c
        return mround(tsp, roundup)

    def _compute_new_lsp(self, pp):
        # type: (float) -> float
        pp = 0 if pp < 0 else 1 if pp > 1 else pp

        idx = self._pf_zn_light['idx']
        roundup = self._pf_zn_light['roundup']
        coefficients = self._pf_zn_light['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        lsp = a * pp ** 2 + b * pp + c
        return mround(lsp, roundup)

    # compute ed ac from ed functions given tsp
    def _compute_ed_ac(self, bid_tsp):
        # type: (float) -> float
        idx = self._edf_zn_ac['idx']
        roundup = self._edf_zn_ac['roundup']
        coefficients = self._edf_zn_ac['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        ed_ac = a * bid_tsp ** 2 + b * bid_tsp + c
        return mround(ed_ac, roundup)

    # compute ed lighting from ed functions given lsp
    def _compute_ed_light(self, bid_lsp):
        # type: (float) -> float
        idx = self._edf_zn_light['idx']
        roundup = self._edf_zn_light['roundup']
        coefficients = self._edf_zn_light['coefficients']

        a = float(coefficients[idx]['a'])
        b = float(coefficients[idx]['b'])
        c = float(coefficients[idx]['c'])

        ed_light = a * bid_lsp ** 2 + b * bid_lsp + c
        return mround(ed_light, roundup)

    print('Test Zone PF & EDF')

    def test_zn_ac(self):
        print('test_zn_ac')
        duration = 3600
        for bid_pp in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            bid_tsp = self._compute_new_tsp(bid_pp)
            ed_ac = calc_energy_wh(
                self._compute_ed_ac(bid_tsp),
                duration
            )
            print(
                'bid_pp: {:0.2f}'.format(bid_pp)
                + ', bid_tsp: {:0.1f}'.format(bid_tsp)
                + ', ed_ac: {:0.2f}'.format(ed_ac)
            )

        self.assertEqual(True, True)

    def test_zn_light(self):
        print('\ntest_zn_light')
        duration = 3600
        for bid_pp in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            bid_lsp = self._compute_new_lsp(bid_pp)
            ed_light = calc_energy_wh(
                self._compute_ed_light(bid_lsp/100),
                duration
            )
            print(
                'bid_pp: {:0.2f}'.format(bid_pp)
                + ', bid_lsp: {:0.1f}'.format(bid_lsp)
                + ', ed_light: {:0.2f}'.format(ed_light)
            )

        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
