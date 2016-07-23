#include "mraa.h"
#include <stdio.h>
#include <unistd.h>
void main()
{
	mraa_pwm_context pwm = mraa_pwm_init(0);
	mraa_pwm_period_us(pwm,50);
	mraa_pwm_pulsewidth_us(pwm,25);
	mraa_pwm_enable(pwm,1);
}

