import unittest

d_add_1 = 'd_add_1'
d_id_1 = 'd_id_1'

d_add_2 = 'd_add_2'
d_id_2 = 'd_id_2'

d_add_3 = 'd_add_3'
d_id_3 = 'd_id_3'

d_add_4 = 'd_add_4'
d_id_4 = 'd_id_4'


class MyTestCase(unittest.TestCase):
    ds_register = []  # ds discovery_addresses
    ds_device_ids = []  # ds device_ids
    bridge_host = ''

    def register_ds_bridge(self, d_add, d_id):
        print(
                '\nregister_ds_bridge('
                '{}'.format(d_add)
                + ', {})'.format(d_id)
        )

        if d_add in self.ds_register:
            print('already registered!!!')
            return

        self.ds_register.append(d_add)
        index = self.ds_register.index(d_add)
        print('index: {}'.format(index))

        self.ds_device_ids.insert(index, d_id)

        return

    def unregister_ds_bridge(self, d_add, d_id):
        print(
                '\nunregister_ds_bridge('
                + '{}'.format(d_add)
                + ', {})'.format(d_id)
        )

        if d_add not in self.ds_register:
            print('already unregistered!!!')
            return

        index = self.ds_register.index(d_add)
        del self.ds_register[index]
        del self.ds_device_ids[index]
        return

    def print_ds_register(self):
        print(
            'ds_register: {}'.format(self.ds_register)
            + ', ds_device_ids: {}'.format(self.ds_device_ids)
        )
        return

    def get_ds_device_ids(self):
        return (self.ds_device_ids
                if self.bridge_host != 'LEVEL_TAILEND'
                else [])

    def test_1(self):
        print('test_1()')
        self.print_ds_register()
        self.register_ds_bridge(d_add_1, d_id_1)
        self.print_ds_register()
        self.register_ds_bridge(d_add_2, d_id_2)
        self.print_ds_register()
        self.register_ds_bridge(d_add_3, d_id_3)
        self.print_ds_register()
        self.register_ds_bridge(d_add_1, d_id_1)
        self.print_ds_register()
        self.unregister_ds_bridge(d_add_1, d_id_1)
        self.print_ds_register()

        self.assertEqual(True, True)
        print('\n...done')
        return

    def test_2(self):
        print('\ntest_2()')
        result = ['sam_1', 'sam_2']
        print(
            'result: {}'.format(result)
        )

        result = self.get_ds_device_ids()
        print(
            'result: {}'.format(result)
        )

        self.register_ds_bridge(d_add_4, d_id_4)
        result = self.get_ds_device_ids()
        print(
            'result: {}'.format(result)
        )

        print('\n...done')
        return


if __name__ == '__main__':
    unittest.main()
