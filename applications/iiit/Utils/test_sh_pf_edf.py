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

SH_DEVICE_LED = 1
SH_DEVICE_FAN = 2

SH_FAN_POWER = 8
SH_LED_POWER = 10

SH_FAN_THRESHOLD_PCT = .30
SH_LED_THRESHOLD_PCT = .30


def mround(num, multiple_of):
    # _log.debug('mround()')
    value = math.floor((num + multiple_of / 2) / multiple_of) * multiple_of
    return value


# return energy in Wh for the given duration
def calc_energy_wh(pwr_wh, duration_sec):
    value = (pwr_wh * duration_sec) / 3600
    return value


class MyTestCase(unittest.TestCase):
    _pf_sh_fan = {
        "roundup": 10,
        "idx": 0,
        "coefficients": [
            {"a": 70, "b": 5, "c": 20},
            {"a": 60, "b": 10, "c": 30},
            {"a": 35, "b": 29.75, "c": 40}
        ]
    }

    _pf_rc = {
        "roundup": 0.5,
        "idx": 2,
        "coefficients": [
            {"a": 1, "b": -3.5, "c": 23},
            {"a": 1, "b": -3.5, "c": 24},
            {"a": 1, "b": -3.5, "c": 25}
        ]
    }

    _edf_rc = {
        "roundup": 0.5,
        "idx": 2,
        "coefficients": [
            {"a": 0, "b": -100, "c": 2350},
            {"a": 0, "b": -100, "c": 2400},
            {"a": 0, "b": -100, "c": 2450}
        ]
    }

    _sh_devices_th_pp = [1.95, .5, 1.95, 1.95, 0.95, 0.95, 0.95, 0.95, 0.95]
    _sh_devices_level = [0.3, 0.9, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]

    # compute new Fan Speed (0-100%) from price functions
    def _compute_new_fan_speed(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp

        idx = self._pf_sh_fan['idx']
        roundup = self._pf_sh_fan['roundup']
        coefficients = self._pf_sh_fan['coefficients']

        a = coefficients[idx]['a']
        b = coefficients[idx]['b']
        c = coefficients[idx]['c']

        speed = a * pp ** 2 + b * pp + c
        return mround(speed, roundup)

    def _sh_fan_ed(self, bid_pp, duration):
        ed = 0
        if bid_pp <= self._sh_devices_th_pp[SH_DEVICE_FAN]:
            fan_speed = self._compute_new_fan_speed(bid_pp) / 100
            fan_energy = calc_energy_wh(SH_FAN_POWER, duration)
            ed = ((fan_energy * SH_FAN_THRESHOLD_PCT)
                  if fan_speed <= SH_FAN_THRESHOLD_PCT
                  else (fan_energy * fan_speed))
        return ed

    # compute new TSP from price functions
    def _compute_rc_new_tsp(self, pp):
        pp = 0 if pp < 0 else 1 if pp > 1 else pp

        idx = self._pf_rc['idx']
        roundup = self._pf_rc['roundup']
        coefficients = self._pf_rc['coefficients']

        a = coefficients[idx]['a']
        b = coefficients[idx]['b']
        c = coefficients[idx]['c']

        tsp = a * pp ** 2 + b * pp + c
        return mround(tsp, roundup)

    # compute ed ac from ed functions given tsp
    def _compute_ed_rc(self, bid_tsp):
        idx = self._edf_rc['idx']
        roundup = self._edf_rc['roundup']
        coefficients = self._edf_rc['coefficients']

        a = coefficients[idx]['a']
        b = coefficients[idx]['b']
        c = coefficients[idx]['c']

        ed_ac = a * bid_tsp ** 2 + b * bid_tsp + c
        return mround(ed_ac, roundup)

    def _sh_led_ed(self, bid_pp, duration):
        ed = 0
        if bid_pp <= self._sh_devices_th_pp[SH_DEVICE_LED]:
            led_level = self._sh_devices_level[SH_DEVICE_LED]
            led_energy = calc_energy_wh(SH_LED_POWER, duration)
            ed = ((led_energy * SH_LED_THRESHOLD_PCT)
                  if led_level <= SH_LED_THRESHOLD_PCT
                  else (led_energy * led_level))
        return ed

    print('Test SH & RC PF & EDF')

    def test_sh_rc(self):
        print('\ntest_sh_rc')
        duration = 3600
        for bid_pp in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            bid_tsp = self._compute_rc_new_tsp(bid_pp)
            ed_rc = calc_energy_wh(
                self._compute_ed_rc(bid_tsp),
                duration
            )
            print(
                'bid_pp: {:0.2f}'.format(bid_pp)
                + ', bid_tsp: {:0.2f}'.format(bid_tsp)
                + ', ed_rc: {:0.4f}'.format(ed_rc)
            )
        self.assertEqual(True, True)

    def test_sh_fan(self):
        print('\ntest_sh_fan')
        duration = 3600
        for bid_pp in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            fan_speed = self._compute_new_fan_speed(bid_pp)
            ed_fan = self._sh_fan_ed(bid_pp, duration)
            print(
                'bid_pp: {:0.2f}'.format(bid_pp)
                + ', fan_speed: {:0.2f}'.format(fan_speed)
                + ', ed_fan: {:0.4f}'.format(ed_fan)
            )
        self.assertEqual(True, True)

    def test_sh_led(self):
        print('\ntest_sh_led')
        duration = 3600
        for bid_pp in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            for led_level in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
                self._sh_devices_level[SH_DEVICE_LED] = led_level
                # fan_speed = self._compute_new_fan_speed(bid_pp)
                ed_led = self._sh_led_ed(bid_pp, duration)
                print(
                    'bid_pp: {:0.2f}'.format(bid_pp)
                    + ', led_level: {:0.2f}'.format(led_level)
                    + ', ed_led: {:0.4f}'.format(ed_led)
                )
        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
