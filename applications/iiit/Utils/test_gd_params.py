import unittest


class MyTestCase(unittest.TestCase):
    _gd_params = {
        "max_iterations": 1000,
        "deadband": 100,
        "gamma": {
            "ac": 0.0001,
            "light": 0.0001
        },
        "weight_factors": {
            "ac": 30,
            "light": 1
        }
    }

    def test_something(self):
        wt_factors = self._gd_params['weight_factors']
        sum_wt_factors = float(wt_factors['ac'] + wt_factors['light'])

        c_ac = (
            (float(wt_factors['ac']) / sum_wt_factors)
            if sum_wt_factors != 0 else 0
        )
        c_light = (
            (float(wt_factors['light']) / sum_wt_factors)
            if sum_wt_factors != 0 else 0
        )

        print(
            'sum_wt_factors: {:0.2}'.format(sum_wt_factors)
            + ', c_ac: {:0.2}'.format(c_ac)
            + ', c_light: {:0.2}'.format(c_light)
        )
        self.assertEqual(True, True)


if __name__ == '__main__':
    unittest.main()
