#include <stdio.h>
#include "mraa.h"
#include <unistd.h>
#include <math.h>


#define DEVICE_ADDRESS_1 0x4b
#define DEVICE_ADDRESS_2 0x4a
#define EDISON_I2C_BUS_OUTSIDE 1
#define EDISON_I2C_BUS_INSIDE 6

double getVisibleLux(uint8_t ValueMsb,uint8_t ValueLsb)
{
	uint8_t exponent = (( ValueMsb & 0xF0 ) >> 4);
	uint8_t mantissa = (( ValueMsb & 0x0F ) <<4) | ( ValueLsb & 0x0F );
	double result_1 = pow((double)2,(double)(exponent));
	double result = result_1 * mantissa * 0.045;
	return result;
}


void main()
{
    
    mraa_i2c_context i2c_outside = mraa_i2c_init(EDISON_I2C_BUS_OUTSIDE);
	mraa_i2c_context i2c_inside = mraa_i2c_init(EDISON_I2C_BUS_INSIDE);
    uint8_t LuxHighByte,LuxLowByte;
    int i=1;
    double lux_data;
    while(1)
    {

        printf("\n Reading Data : %d",i);
        mraa_i2c_address(i2c_outside, DEVICE_ADDRESS_1);
        mraa_i2c_write_byte(i2c_outside,0x03);
        mraa_i2c_address(i2c_outside,DEVICE_ADDRESS_1);
        LuxHighByte = mraa_i2c_read_byte(i2c_outside);
	mraa_i2c_address(i2c_outside,DEVICE_ADDRESS_1);
	mraa_i2c_write_byte(i2c_outside,0x04);
	mraa_i2c_address(i2c_outside,DEVICE_ADDRESS_1);
	LuxLowByte = mraa_i2c_read_byte(i2c_outside);
	lux_data = getVisibleLux( LuxHighByte , LuxLowByte );
	printf("\nLUX LOW BYTE : %d",LuxLowByte);
	printf("\nLUX HIGH BYTE : %d",LuxHighByte);


	printf("\nLux Data OUTSIDE Sensor  : %f ",lux_data);
	mraa_i2c_address(i2c_inside, DEVICE_ADDRESS_2);
        mraa_i2c_write_byte(i2c_inside,0x03);
        mraa_i2c_address(i2c_inside,DEVICE_ADDRESS_2);
        LuxHighByte = mraa_i2c_read_byte(i2c_inside);
	mraa_i2c_address(i2c_inside,DEVICE_ADDRESS_2);
	mraa_i2c_write_byte(i2c_inside,0x04);
	mraa_i2c_address(i2c_inside,DEVICE_ADDRESS_2);
	LuxLowByte = mraa_i2c_read_byte(i2c_inside);
	lux_data = getVisibleLux( LuxHighByte , LuxLowByte );
	printf("\nLUX LOW BYTE : %d",LuxLowByte);
	printf("\nLUX HIGH BYTE : %d",LuxHighByte);


	printf("\nLux Data INSIDE  : %f ",lux_data);

	sleep(5);
	i++;
	mraa_i2c_stop(i2c_inside);
	mraa_i2c_stop(i2c_outside);

     }
}
