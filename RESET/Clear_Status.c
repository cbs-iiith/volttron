#include "stdio.h"
#include "unistd.h"
#include "mraa.h"
#define GPIO_128 13
#define GPIO_110 23
#define GPIO_114 24
#define GPIO_129 25
#define GPIO_44 31
#define GPIO_46 32
#define GPIO_48 33
#define MAX_MRAA_PINS 7
static const int MRAA_PINS[]={
	GPIO_128,
	GPIO_110,
	GPIO_114,
	GPIO_129,
	GPIO_44,
	GPIO_46,
	GPIO_48,
	-1
};
int i=0;
int main(int argc, char** argv)
{
	mraa_result_t r =MRAA_SUCCESS;
	mraa_gpio_context gpio;
	for(i=0;i<MAX_MRAA_PINS;i++)
		{
			gpio=mraa_gpio_init(MRAA_PINS[i]);
			mraa_gpio_dir(gpio,MRAA_GPIO_OUT);
			mraa_gpio_write(gpio,0);
			mraa_gpio_close(gpio);
		}
	
	return 0;
}



