#include "mraa.h"
#include "unistd.h"
#include "stdio.h"
int main()
{
        
	mraa_init();
	mraa_gpio_context gpio_1,gpio_2;
	gpio_1=mraa_gpio_init(0);
	gpio_2=mraa_gpio_init(13);
	mraa_gpio_dir(gpio_1,MRAA_GPIO_OUT);
	mraa_gpio_write(gpio_1,0);
	mraa_gpio_dir(gpio_2,MRAA_GPIO_OUT);
	mraa_gpio_write(gpio_2,0);
	mraa_gpio_close(gpio_1);
	mraa_gpio_close(gpio_2);
}
