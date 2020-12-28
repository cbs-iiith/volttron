print('dict')
wt_factors = {'plug1': 20, 'plug2': 30}

# only keys
for k in wt_factors:
    print('k: {}'.format(k))

print('i, k, v')
for i, (k, v) in enumerate(wt_factors.items()):
    print(str(i), str(k), str(v))

print('k, v')
for k, v in wt_factors.items():
    print(str(k), str(v))

print('list')
my_list = wt_factors.values()

my_keys = wt_factors.keys()

print('v')
for v in my_list:
    print(str(v))

print('i, v')
for i, v in enumerate(my_list):
    print(str(i), str(v))

print('\nfirst item value: {}'.format(list(wt_factors.values())[0]))
