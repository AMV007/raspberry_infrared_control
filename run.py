#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys

import RPi.GPIO as GPIO
import math
from datetime import datetime
from time import sleep
import numpy as np
import pigpio

# This is for revision 1 of the Raspberry Pi, Model B
# This pin is also referred to as GPIO23
INPUT_WIRE = 27

def print_array(commands):
    print ("----------Start----------")
    for (val, pulseLength) in commands:
        print (f"{val}, {pulseLength} microseconds")
    print ("-----------End-----------\n")
    print ("Size of array is " + str(len(commands)))


def find_nearest(array, value):
    n = [abs(i-value) for i in array]
    idx = n.index(min(n))
    return array[idx]

def decode_data(commands):
    #Compute the average low pulse width
    #Ignore the first two readings it's start bit
    commands=commands[2:]
    analyzed_len=len(commands)-len(commands)%16

    if len(commands)%16 !=1: #1 - stop bit at the end
        print(f"warning, got unknown bits: {len(commands)%16}")

    threshold = 0
    for counter in range(0,analyzed_len,2):
        val, pulseLength = commands[counter]
        threshold += pulseLength
    threshold /= (((analyzed_len-1)/2)-1)

    bands=[110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200, 128000 ]
    possible_band=int(1e6/threshold)
    bandwidth=find_nearest(bands, possible_band)
    print(f"threshold={threshold}, possible_band:{possible_band} bps")

    #ignoring first 3 commands - empirically


    data_len=int(analyzed_len/16)
    data = bytearray(data_len)

    #due to gaps, need to increase it's threshold value
    threshold*=1.5

    
    for counter in range(1,analyzed_len,2):
        val, pulseLength = commands[counter]
        index = int((counter)/16)
        data[index] >>=1
        if pulseLength>=threshold:
            #One bit for long pulse.
            data[index] |=(0x1<<7)
        #Else zero bit for short pulse.

    return bandwidth, data

def read_input():
    GPIO.setup(INPUT_WIRE, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    while True:
        value = 1
        # Loop until we read a 0, actually values inverted - 1 mean 0 and 0 - mean 1
        while value:
            value = GPIO.input(INPUT_WIRE)

        # Grab the start time of the commands
        startTime = datetime.now()

        # Used to buffer the commands pulses
        commands = []

        # The end of the "commands" happens when we read more than
        # a certain number of 1s (1 is off for my IR receiver)
        numOnes = 0

        # Used to keep track of transitions from 1 to 0
        previousVal = 0

        while True:

            if value != previousVal:
                # The value has changed, so calculate the length of this run
                now = datetime.now()
                pulseLength = now - startTime
                startTime = now

                #commands.append((previousVal, pulseLength.microseconds))
                #becasue inverted
                commands.append((value, pulseLength.microseconds))

            if value:
                numOnes = numOnes + 1
            else:
                numOnes = 0

            # 10000 is arbitrary, adjust as necessary
            if numOnes > 100000:
                break

            previousVal = value
            value = GPIO.input(INPUT_WIRE)

        print_array(commands)

        if len(commands)>=(3+16):
            return decode_data(commands)

def write_one_IR(pi, timeout_mks):
    pi.hardware_PWM(OUTPUT_WIRE, 38000, 500000)
    sleep(timeout_mks)
    pi.hardware_PWM(OUTPUT_WIRE, 0, 0)

def write_zero_IR(timeout_mks):
    sleep(timeout_mks)

#OUTPUT_WIRE = 17
OUTPUT_WIRE = 18
def write_output(bandwidth, data):

    status = os.system('systemctl is-active --quiet pigpiod')
    if status !=0:
        print(f"service status={status}")
        os.system("sudo service pigpiod start")
        sleep(1)

    ir_freq=38400
    GPIO.setup(OUTPUT_WIRE, GPIO.OUT, initial=GPIO.LOW)
    pi = pigpio.pi()
    data_bits=""
    wait_timeout_mks=(1/bandwidth)
    wait_timeout_mks-=(100e-6) # because python latencies
    print(f"wait_timeout_mks={int(wait_timeout_mks*1e6)}")

    write_one_IR(pi, wait_timeout_mks*8)
    write_zero_IR(wait_timeout_mks*3)

    for counter in range(0,len(data)*8):
        index = int(counter/8)
        offset=(counter%8)
        bit = (data[index]>>offset) & 0x1

        write_one_IR(pi, wait_timeout_mks)
        data_bits+=str(bit)
        if bit:
            write_zero_IR(wait_timeout_mks*3)
        else:
            write_zero_IR(wait_timeout_mks) 

    # last stop bit
    write_one_IR(pi, wait_timeout_mks)
    write_zero_IR(wait_timeout_mks)
    print(f"data_bits={data_bits}")
    pi.stop()

def get_conditioner_data_array(enabled, hvac_mode, temperature, fan, vanne):
    data=[0x23, 0xcb, 0x26, 0x01, 0x00] # header
    if enabled:
        data.append(0x24)
    else:
        data.append(0x20)

    if hvac_mode == "heat":
        data.append(0x1)
    elif hvac_mode == "dry":
        data.append(0x2)
    elif hvac_mode == "cool":
        data.append(0x3)
    elif hvac_mode == "feel":
        data.append(0x8)
    else:
        raise "unknown mode"
    
    if temperature>31 or temperature<16:
        raise "not possible temperature"
    
    temperature=31-temperature
    data.append(temperature)

    fan_vanne=0
    if fan == 'auto':
        fan_vanne|=0x0
    elif fan == '1':
        fan_vanne|=0x2
    elif fan == '2':
        fan_vanne|=0x3
    elif fan == '3':
        fan_vanne|=0x5
    else:
        raise "unknown fan value"

    if vanne== 'auto':
        fan_vanne|=0x0
    elif vanne == '1':
        fan_vanne|=0x8
    elif vanne == '2':
        fan_vanne|=0x10
    elif vanne == '3':
        fan_vanne|=0x18
    elif vanne == '4':
        fan_vanne|=0x20
    elif vanne == '5':
        fan_vanne|=0x28
    elif vanne == 'cruise':
        fan_vanne|=0x38
    else:
        raise "unknown vanne value"
    
    data.append (fan_vanne)
    # clock ?
    data.append(0)
    data.append(0)
    data.append(0)
    data.append(0)

    arr_sum = sum(data)
    data.append(arr_sum&0xff)

    return data

def check_conditioner_data_crc(data):
    print (f"check data[{len(data)}]: "+''.join('0x{:02x}, '.format(x) for x in data))
    recv_data=data[:-1]
    sum_arr=sum(data[:-1])&0xff
    if sum_arr != data[-1]:
        print(f"CRC ERROR !!! must be 0x{sum_arr:x} but we have 0x{data[-1]:x}")
    else:
        print("CRC OK")

#   MAIN
if __name__ == "__main__":
    GPIO.setmode(GPIO.BCM)

    if True:
        bandwidth, data=read_input()
        print(f"read bandwidth: {bandwidth}")
        check_conditioner_data_crc(data)

    if True:
        bandwidth=2400
        data=get_conditioner_data_array(enabled=False, hvac_mode='cool', temperature=26, fan='1', vanne='1')

        print(f"bandwidth: {bandwidth}")
        print (f"data [{len(data)}]: "+''.join('0x{:02x}, '.format(x) for x in data))

        write_output(bandwidth, data)

    GPIO.cleanup()
