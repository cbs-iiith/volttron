#include <unistd.h>
#include "mraa.h"

void main()
{

    mraa_init();
    mraa_gpio_context gpio;
    gpio = mraa_gpio_init(0);
    mraa_gpio_dir( gpio, MRAA_GPIO_OUT );
    int i,j;
    int steps = 1000;
    for (  i=0 ; i<steps ; i++ )
    {
            mraa_gpio_write(gpio,1);
            for(j=0;j<10000;j++);
            mraa_gpio_write(gpio,0);
            for(j=0;j<10000;j++);
    }
    mraa_gpio_close(gpio);
}
