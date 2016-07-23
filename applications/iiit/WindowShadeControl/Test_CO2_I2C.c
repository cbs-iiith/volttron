#include <stdio.h>
#include "mraa.h"
#include <unistd.h>

#define DEVICE_ADDRESS 0x15
#define EDISON_I2c_BUS 1
int main()
{
    mraa_i2c_context i2c = mraa_i2c_init(EDISON_I2c_BUS);
    uint8_t byte1,byte2,byte3,byte4;
    while(1)
    {

        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        mraa_i2c_write_byte(i2c,0x04);
        mraa_i2c_address(i2c,DEVICE_ADDRESS);
        mraa_i2c_write_byte(i2c,0x13);
        mraa_i2c_address(i2c,DEVICE_ADDRESS);
        mraa_i2c_write_byte(i2c,0x8A);
        mraa_i2c_address(i2c,DEVICE_ADDRESS);
        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        mraa_i2c_write_byte(i2c,0x00);
        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        byte1 = mraa_i2c_read_byte(i2c);
        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        byte2 = mraa_i2c_read_byte(i2c);
        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        byte3 = mraa_i2c_read_byte(i2c);
        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        byte4 = mraa_i2c_read_byte(i2c);

        mraa_i2c_stop(i2c);
        printf("\nByte 1 : %d",byte1);
        printf("\nByte 2 : %d",byte2);
        printf("\nByte 3 : %d",byte3);
        printf("\nByte 4 : %d",byte4);

     }
}
