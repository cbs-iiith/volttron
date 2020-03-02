import sys

from ispace_msg import (
    ISPACE_Msg, MessageType, ISPACE_Msg_ActivePower, ISPACE_Msg_Energy,
    EnergyCategory
    )
from ispace_msg_utils import get_default_ap_msg, get_default_ed_msg
from copy import copy

tmp1 = ISPACE_Msg_ActivePower(
    MessageType.active_power, False, True,
    0, 'float', 'W',
    None,
    '192.168.1.4', 'device-1',
    None, None,
    3600, 3600, 60, 'UTC',
    EnergyCategory.thermal
    )
tmp2 = ISPACE_Msg_ActivePower(
    MessageType.active_power, False, True,
    0, 'float', 'W',
    None,
    '192.168.1.4', 'device-2',
    None, None,
    3600, 3600, 60, 'UTC',
    EnergyCategory.lighting
    )

tmp3 = get_default_ap_msg('192.168.1.4', 'device-3')
tmp4 = get_default_ap_msg('192.168.1.4', 'device-4')
tmp5 = copy(tmp2)

print('Active Power Messages')
print('Message1: {}'.format(tmp1))
print('Message2: {}'.format(tmp2))
print('Message3: {}'.format(tmp3))
print('Message4: {}'.format(tmp4))
print('Message5: {}'.format(tmp5))


tmp1 = ISPACE_Msg_Energy(
    MessageType.energy_demand, False, True,
    0, 'float', 'Wh',
    None,
    '192.168.1.4', 'device-1',
    None, None,
    3600, 3600, 60, 'UTC',
    EnergyCategory.thermal
    )
tmp2 = ISPACE_Msg_Energy(
    MessageType.energy_demand, False, True,
    0, 'float', 'Wh',
    None,
    '192.168.1.4', 'device-2',
    None, None,
    3600, 3600, 60, 'UTC',
    EnergyCategory.lighting
    )

tmp3 = get_default_ed_msg('192.168.1.4', 'device-3')
tmp4 = get_default_ed_msg('192.168.1.4', 'device-4')
tmp5 = copy(tmp2)

print('Energy Demand Messages')
print('Message1: {}'.format(tmp1))
print('Message2: {}'.format(tmp2))
print('Message3: {}'.format(tmp3))
print('Message4: {}'.format(tmp4))
print('Message5: {}'.format(tmp5))
