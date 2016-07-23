#include <stdio.h>
#include <unistd.h>
#include "mraa.h"

int getCO2Data(uint8_t UpperByte, uint8_t LowerByte)
{
	return (UpperByte*256 + LowerByte);
}
void main()
{
	//char buf_status[8]={"0x15","0x04","0x13","0x8A","0x00","0x01","0x17","0xB0"};
	const uint8_t buf_status[8]={0x15,0x04,0x13,0x8b,0x00,0x01,0x46,0x70};
	int i=0,sensor_data;
	uint8_t buf[7];
	mraa_uart_context dev;
	dev=mraa_uart_init(0);
	mraa_uart_set_baudrate(dev,19200);
	mraa_uart_set_mode(dev,8,MRAA_UART_PARITY_EVEN,1);
	while(1)
	{
	i++;
	mraa_uart_write(dev,buf_status,8);
	usleep(500);
	mraa_uart_read(dev,buf,7);
	sensor_data = getCO2Data(buf[3],buf[4]);
	printf("\nSensor Data_%d :  %d",i,sensor_data);
	sleep(10);
	}
	
	
}

