#include <stdio.h>
#include "mraa.h"
#include <unistd.h>
#include <math.h>


#define DEVICE_ADDRESS 0x4a
#define EDISON_I2C_BUS 1

/*void sleep()
{
	int i,j;
	for (i=0;i<1000;i++)
		for(j=0;j<1000;j++);

}
*/
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
    
    mraa_i2c_context i2c = mraa_i2c_init(EDISON_I2C_BUS);
    uint8_t LuxHighByte,LuxLowByte;
    int i=1;
    double lux_data;
    while(1)
    {

        printf("\n Reading Data : %d",i);
        mraa_i2c_address(i2c, DEVICE_ADDRESS);
        mraa_i2c_write_byte(i2c,0x03);
        mraa_i2c_address(i2c,DEVICE_ADDRESS);
        LuxHighByte = mraa_i2c_read_byte(i2c);
	mraa_i2c_address(i2c,DEVICE_ADDRESS);
	mraa_i2c_write_byte(i2c,0x04);
	mraa_i2c_address(i2c,DEVICE_ADDRESS);
	LuxLowByte = mraa_i2c_read_byte(i2c);
	lux_data = getVisibleLux( LuxHighByte , LuxLowByte );
	printf("\nLUX LOW BYTE : %d",LuxLowByte);
	printf("\nLUX HIGH BYTE : %d",LuxHighByte);


	printf("\nLux Data %d  : %f ",i,lux_data);
	sleep(5);
	i++;
	//mraa_i2c_stop(m_test_i2c);

     }
}
