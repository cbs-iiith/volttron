import unittest

d_add_1 = 'd_add_1'
d_id_1 = 'd_id_1'

d_add_2 = 'd_add_2'
d_id_2 = 'd_id_2'

d_add_3 = 'd_add_3'
d_id_3 = 'd_id_3'


class MyTestCase(unittest.TestCase):
    ds_register = []  # ds discovery_addresses
    ds_device_ids = []  # ds device_ids

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
                '\nregister_ds_bridge('
                + '{}'.format(d_add)
                + ', {})'.format(d_id)
        )

        if d_add not in self.ds_register:
            print('already unregistered!!!')
            return

        index = self.ds_register.index(d_add)
        self.ds_register.remove(d_add)
        del self.ds_register[index]
        del self.ds_device_ids[index]
        return

    def print_ds_register(self):
        print(
            'ds_register: {}'.format(self.ds_register)
            + ', ds_device_ids: {}'.format(self.ds_device_ids)
        )
        return

    def test_something(self):
        print('test_something()')
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


if __name__ == '__main__':
    unittest.main()
