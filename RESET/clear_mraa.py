import mraa


myMRAA_Pins=[13,23,24,25]

for i in myMRAA_Pins:
   myLED=mraa.Gpio(i)
   myLED.dir(mraa.DIR_OUT)
   myLED.write(0)
   

	

