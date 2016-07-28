#include "mraa.h"
#include "unistd.h"
#include "stdio.h"
int main()
{
        
	mraa_init();
	mraa_gpio_context gpio;
	gpio=mraa_gpio_init(0);
	mraa_gpio_dir(gpio,MRAA_GPIO_OUT);
	mraa_gpio_write(gpio,0);
	mraa_gpio_close(gpio);
}
