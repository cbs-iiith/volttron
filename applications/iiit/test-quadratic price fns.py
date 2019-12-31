import math

def mround(num, multipleOf):
    return math.floor((num + multipleOf / 2) / multipleOf) * multipleOf

#def mround(num, multipleOf):
#    return math.ceil((num + multipleOf / 2) / multipleOf) * multipleOf

#def mround(num, multipleOf):
#    return int((num + multipleOf - 1) / multipleOf) * multipleOf

#def mround(num, multipleOf):
#    return math.floor((num + multipleOf - 1) / multipleOf) * multipleOf

def i_tsp(a, b, c, v):
    pp = 0
    print('0%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .1
    print('10%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .2
    print('20%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .3
    print('30%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .4
    print('40%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .5
    print('50%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .6
    print('60%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .7
    print('70%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .8
    print('80%: ', mround(a*pp*pp + b*pp + c, v))

    pp = .9
    print('90%: ', mround(a*pp*pp + b*pp + c, v))

    pp = 1
    print('100%: ', mround(a*pp*pp + b*pp + c, v))
    return

print("RM_LSP")
a = -35
b = -35
c = 100
v = 5
i_tsp(a, b, c, v)

print("RM_TSP")
a = 7.5
b = -1.5
c = 24
v = .5
i_tsp(a, b, c, v)

print("RC_SUR_TSP_Warm")
v = 0.5
a = 1
b = -3.5
c = 25
i_tsp(a, b, c, v)

print("RC_SUR_TSP_Normal")
v = 0.5
a = 1
b = -3.5
c = 24
i_tsp(a, b, c, v)


print("RC_SUR_TSP_Cool")
v = 0.5
a = 1
b = -3.5
c = 23
i_tsp(a, b, c, v)

print("FAN_SPEED_HIGH")
v = 10
a = 35
b = 29.75
c = 40
i_tsp(a, b, c, v)

print("FAN_SPEED_NORMAL")
v = 10
a = 60
b = 10
c = 30
i_tsp(a, b, c, v)

print("FAN_SPEED_LOW")
v = 10
a = 70
b = 5
c = 20
i_tsp(a, b, c, v)







