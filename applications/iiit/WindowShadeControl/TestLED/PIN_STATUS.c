#include "mraa.h"
#include "unistd.h"
#include "stdio.h"
int main()
{
        
	mraa_init();
	mraa_gpio_context gpio;
	gpio=mraa_gpio_init(13);
	
	mraa_gpio_dir(gpio,MRAA_GPIO_IN);
	int read=mraa_gpio_read(gpio);
	printf("\nStatus=%d\n",read);
	mraa_gpio_close(gpio);
		
}
