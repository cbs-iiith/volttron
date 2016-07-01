#include "stdio.h"
#include "unistd.h"
#include "mraa.h"
//#define GPIO_128 13
//#define GPIO_110 23
//#define GPIO_114 24
//#define GPIO_129 25
//#define GPIO_44 31
//#define GPIO_46 32
//#define GPIO_48 33
//#define MAX_MRAA_PINS 7
/*static const int MRAA_PINS[]={
	GPIO_46,
	GPIO_48,
	-1
};
*/
#define iopin 13

void delay_ms(int delay)
{
	int i,j;
	for (i=0;i<delay;i++)
		for(j=0;j<1000;j++);
}
	
int main(int argc, char** argv)
{
	mraa_result_t r = MRAA_SUCCESS;
	
	mraa_gpio_context gpio;
	gpio = mraa_gpio_init(iopin);
	mraa_gpio_write(gpio,0);
	delay_ms(5000);
	mraa_gpio_write(gpio,1);
	delay_ms(5000);
	mraa_gpio_write(gpio,0);
	mraa_gpio_close(gpio);


	return 0;
}



