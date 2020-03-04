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

from applications.iiit.Utils.ispace_utils import Runningstats

rs = Runningstats(120)
# D:\Sam NotExtreme\FDD_LAB_VOLT_LOGS\Analysis\Book2.xlsx Sheet3
rs.push(1086.84)
rs.push(1084.39)
rs.push(1101.76)
rs.push(1118.71)
rs.push(1175.62)
rs.push(1193.5)
rs.push(1867.3)
rs.push(4643.15)
rs.push(9567.53)
rs.push(10749.04)
rs.push(13744.6)
rs.push(13988.82)
rs.push(18398.27)
rs.push(15668.12)
rs.push(16422.07)
rs.push(14924.56)
rs.push(13230.41)
rs.push(13364.36)
rs.push(13061.1)
rs.push(12591.44)
rs.push(12354.83)
rs.push(12338.71)
rs.push(12240.55)
rs.push(11936.28)
rs.push(11736.06)
rs.push(11701.95)
rs.push(11570.09)
rs.push(11496.75)
rs.push(11342.42)
rs.push(11529.91)
rs.push(11298.79)
rs.push(11327.1)
rs.push(11027.94)
rs.push(11139.8)
rs.push(10954.59)
rs.push(11427.72)
rs.push(10975.83)
rs.push(10927.54)
rs.push(10942.3)
rs.push(10924.17)
rs.push(10788.68)
rs.push(10836.77)
rs.push(10784.29)
rs.push(10837.6)
rs.push(10827.91)
rs.push(10930.52)
rs.push(10973.06)
rs.push(10749.2)
rs.push(10852.98)
rs.push(10879.52)
rs.push(10733.53)
rs.push(10792.81)
rs.push(10795.36)
rs.push(10764.67)
rs.push(10546.55)
rs.push(10734.5)
rs.push(10456.08)
rs.push(10463.81)
rs.push(10458.25)
rs.push(10542.76)
rs.push(10644.25)
rs.push(10601.24)
rs.push(10658.99)
rs.push(10621.82)
rs.push(10553.45)
rs.push(10614.37)
rs.push(10623.51)
rs.push(10578.18)
rs.push(10797.12)
rs.push(10597.52)
rs.push(10603.52)
rs.push(10509.29)
rs.push(10444.47)
rs.push(10084.96)
rs.push(10092.79)
rs.push(9843.67)
rs.push(9124.42)
rs.push(9000.31)
rs.push(8743.19)
rs.push(8183.78)
rs.push(7768.95)
rs.push(7456.12)
rs.push(6696.11)
rs.push(6202.96)
rs.push(5954.66)
rs.push(5712.57)
rs.push(5724.01)
rs.push(5703.67)
rs.push(5650.99)
rs.push(5485.79)
rs.push(5447.47)
rs.push(5688.41)
rs.push(5493.75)
rs.push(5557.53)
rs.push(5566.5)
rs.push(5588.97)
rs.push(5449.55)
rs.push(5676.86)
rs.push(5526.98)
rs.push(5290.42)
rs.push(5247.72)
rs.push(5411.22)
rs.push(5409.84)
rs.push(5688.5)
rs.push(5913.69)
rs.push(6084.98)
rs.push(6205.03)
rs.push(6426.22)
rs.push(6536.86)
rs.push(6800.36)
rs.push(6685.43)
rs.push(6659.51)
rs.push(6660.71)
rs.push(6803.4)
rs.push(6863.27)
rs.push(6725.03)
rs.push(6844.59)
rs.push(6884.42)
rs.push(6991.08)
rs.push(7045.36)

print('RC FULL DATA')
print('    count: {}'.format(rs.num_data_values()))
print('    mean: {}'.format(rs.mean()))
print('    variance: {}'.format(rs.variance()))
print('    std_dev: {}'.format(rs.std_dev()))
print('    skewness: {}'.format(rs.skewness()))
print('    kurtosis: {}'.format(rs.kurtosis()))
print('    exp_wt_mv_avg: {}'.format(rs.exp_wt_mv_avg()))

rs1 = Runningstats(120)
rs2 = Runningstats(120)
# D:\Sam NotExtreme\FDD_LAB_VOLT_LOGS\Analysis\Book2.xlsx Sheet3
rs1.push(1086.84)
rs1.push(1084.39)
rs1.push(1101.76)
rs1.push(1118.71)
rs1.push(1175.62)
rs1.push(1193.5)
rs1.push(1867.3)
rs1.push(4643.15)
rs1.push(9567.53)
rs1.push(10749.04)
rs1.push(13744.6)
rs1.push(13988.82)
rs1.push(18398.27)
rs1.push(15668.12)
rs1.push(16422.07)
rs1.push(14924.56)
rs1.push(13230.41)
rs1.push(13364.36)
rs1.push(13061.1)
rs1.push(12591.44)
rs1.push(12354.83)
rs1.push(12338.71)
rs1.push(12240.55)
rs1.push(11936.28)
rs1.push(11736.06)
rs1.push(11701.95)
rs1.push(11570.09)
rs1.push(11496.75)
rs1.push(11342.42)
rs1.push(11529.91)
rs1.push(11298.79)
rs1.push(11327.1)
rs1.push(11027.94)
rs1.push(11139.8)
rs1.push(10954.59)
rs1.push(11427.72)
rs1.push(10975.83)
rs1.push(10927.54)
rs1.push(10942.3)
rs1.push(10924.17)
rs1.push(10788.68)
rs1.push(10836.77)
rs1.push(10784.29)
rs1.push(10837.6)
rs1.push(10827.91)
rs1.push(10930.52)
rs1.push(10973.06)
rs1.push(10749.2)
rs1.push(10852.98)
rs1.push(10879.52)
rs1.push(10733.53)
rs2.push(10792.81)
rs2.push(10795.36)
rs2.push(10764.67)
rs2.push(10546.55)
rs2.push(10734.5)
rs2.push(10456.08)
rs2.push(10463.81)
rs2.push(10458.25)
rs2.push(10542.76)
rs2.push(10644.25)
rs2.push(10601.24)
rs2.push(10658.99)
rs2.push(10621.82)
rs2.push(10553.45)
rs2.push(10614.37)
rs2.push(10623.51)
rs2.push(10578.18)
rs2.push(10797.12)
rs2.push(10597.52)
rs2.push(10603.52)
rs2.push(10509.29)
rs2.push(10444.47)
rs2.push(10084.96)
rs2.push(10092.79)
rs2.push(9843.67)
rs2.push(9124.42)
rs2.push(9000.31)
rs2.push(8743.19)
rs2.push(8183.78)
rs2.push(7768.95)
rs2.push(7456.12)
rs2.push(6696.11)
rs2.push(6202.96)
rs2.push(5954.66)
rs2.push(5712.57)
rs2.push(5724.01)
rs2.push(5703.67)
rs2.push(5650.99)
rs2.push(5485.79)
rs2.push(5447.47)
rs2.push(5688.41)
rs2.push(5493.75)
rs2.push(5557.53)
rs2.push(5566.5)
rs2.push(5588.97)
rs2.push(5449.55)
rs2.push(5676.86)
rs2.push(5526.98)
rs2.push(5290.42)
rs2.push(5247.72)
rs2.push(5411.22)
rs2.push(5409.84)
rs2.push(5688.5)
rs2.push(5913.69)
rs2.push(6084.98)
rs2.push(6205.03)
rs2.push(6426.22)
rs2.push(6536.86)
rs2.push(6800.36)
rs2.push(6685.43)
rs2.push(6659.51)
rs2.push(6660.71)
rs2.push(6803.4)
rs2.push(6863.27)
rs2.push(6725.03)
rs2.push(6844.59)
rs2.push(6884.42)
rs2.push(6991.08)
rs2.push(7045.36)

print('\nRC DATA-1')
print('    count: {}'.format(rs1.num_data_values()))
print('    mean: {}'.format(rs1.mean()))
print('    variance: {}'.format(rs1.variance()))
print('    std_dev: {}'.format(rs1.std_dev()))
print('    skewness: {}'.format(rs1.skewness()))
print('    kurtosis: {}'.format(rs1.kurtosis()))
print('    exp_wt_mv_avg: {}'.format(rs1.exp_wt_mv_avg()))

print('\nRC DATA-2')
print('    count: {}'.format(rs2.num_data_values()))
print('    mean: {}'.format(rs2.mean()))
print('    variance: {}'.format(rs2.variance()))
print('    std_dev: {}'.format(rs2.std_dev()))
print('    skewness: {}'.format(rs2.skewness()))
print('    kurtosis: {}'.format(rs2.kurtosis()))
print('    exp_wt_mv_avg: {}'.format(rs2.exp_wt_mv_avg()))

combined = rs1 + rs2
print('\nRC combined')
print('    count: {}'.format(combined.num_data_values()))
print('    mean: {}'.format(combined.mean()))
print('    variance: {}'.format(combined.variance()))
print('    std_dev: {}'.format(combined.std_dev()))
print('    skewness: {}'.format(combined.skewness()))
print('    kurtosis: {}'.format(combined.kurtosis()))
print('    exp_wt_mv_avg: {}'.format(combined.exp_wt_mv_avg()))
